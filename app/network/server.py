import asyncio
import base64
import functools
import json
import logging
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import websockets

from app.core.config import (
    DEFAULT_WS_PORT, DEFAULT_HOST, CENTRAL_DB_PATH,
    ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN, ALL_ROLES
)
from app.database.db_manager import DBManager
from app.network import protocol as P
from app.services.excel_service import ExcelExportService

logger = logging.getLogger(__name__)

MANAGERS = (ROLE_ADMIN, ROLE_SUPER_ADMIN)
OVERSIGHT = (ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN)

# Login throttling: after MAX_FAILED_LOGINS wrong passwords, the user ID is locked for LOCKOUT_SECONDS
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 60


class _AlreadyReplied(Exception):
    """Raised by a handler that already sent its own (error) reply."""


class Session:
    """Identity bound to one WebSocket after a successful LOGIN/RESUME. Always loaded from the DB."""
    def __init__(self, user: dict, token: str):
        self.user_id = user["user_id"]
        self.full_name = user.get("full_name")
        self.role = user["role"]
        self.discipline_id = user.get("discipline_id")
        self.discipline_name = user.get("discipline_name")
        self.must_change_password = bool(user.get("must_change_password"))
        self.token = token

    def public_user(self) -> dict:
        return {
            "user_id": self.user_id, "full_name": self.full_name, "role": self.role,
            "discipline_id": self.discipline_id, "discipline_name": self.discipline_name,
            "must_change_password": 1 if self.must_change_password else 0,
        }


class ActionSpec:
    def __init__(self, func, roles, public, allow_pending_password, response_type):
        self.func = func
        self.roles = roles
        self.public = public
        self.allow_pending_password = allow_pending_password
        self.response_type = response_type


ACTIONS: dict[str, ActionSpec] = {}


def action(name: str, roles=None, public: bool = False, allow_pending_password: bool = False,
           response_type: str = None):
    """
    Registers a server action.
    roles: tuple of roles allowed to call it (None = any logged-in role).
    public: callable without a session (LOGIN, RESUME, PING only).
    allow_pending_password: callable while the user still has to change their initial password.
    """
    def deco(func):
        ACTIONS[name] = ActionSpec(func, tuple(roles) if roles else None, public,
                                   allow_pending_password, response_type or f"{name}_RESPONSE")
        return func
    return deco


def _require(payload: dict, *keys):
    for k in keys:
        v = payload.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Missing required field '{k}'.")


class CentralWebSocketServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_WS_PORT, standalone: bool = False,
                 db_path: Path = None, export_chunk_bytes: int = P.EXPORT_CHUNK_BYTES):
        self.host = host
        self.port = port
        self.standalone = standalone
        self.export_chunk_bytes = export_chunk_bytes
        self.db = DBManager(central_db_path=db_path or CENTRAL_DB_PATH, standalone=standalone)
        self.excel_service = ExcelExportService(self.db)
        # All DB work runs on one worker thread so the event loop never blocks and writes are serialized.
        self._db_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deskapp-db")
        # Excel generation is slow and read-only; it gets its own thread so it never delays other requests.
        self._export_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deskapp-export")
        self.sessions: dict = {}  # websocket -> Session | None
        self._failed_logins: dict = {}  # user_id -> (count, locked_until)
        self._ws_server = None
        self._backup_task = None

    # ------------------------------------------------------------------ helpers
    async def db_call(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._db_executor, functools.partial(fn, *args, **kwargs))

    async def _send(self, ws, message: dict) -> bool:
        try:
            await ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.debug("send failed: %s", e)
            return False

    def _live_sessions(self):
        for ws, sess in list(self.sessions.items()):
            if sess is not None and not sess.must_change_password:
                yield ws, sess

    async def broadcast(self, message_dict: dict, target_roles=None, extra_user_ids=()):
        """Push an event to logged-in users with one of target_roles (None = everyone) and/or specific users."""
        for ws, sess in self._live_sessions():
            if (target_roles is None or sess.role in target_roles) or sess.user_id in extra_user_ids:
                await self._send(ws, message_dict)

    async def send_to_user(self, user_id: str, message_dict: dict) -> bool:
        sent = False
        for ws, sess in self._live_sessions():
            if sess.user_id == user_id:
                sent = await self._send(ws, message_dict) or sent
        return sent

    async def notify_changed(self, *scopes: str, roles=None, extra_user_ids=()):
        """
        Tell clients which kinds of data changed so they reload only that.
        Scopes: projects, tasks, disciplines, users, proposals, date_changes, settings.
        """
        await self.broadcast({"type": "DATA_CHANGED", "scopes": list(scopes)}, target_roles=roles,
                             extra_user_ids=extra_user_ids)

    async def _revoke_user_sessions(self, user_id: str, reason: str):
        for ws, sess in list(self.sessions.items()):
            if sess is not None and sess.user_id == user_id:
                self.sessions[ws] = None
                try:
                    await ws.close(code=P.CLOSE_SESSION_REVOKED, reason=reason)
                except Exception:
                    pass

    async def _refresh_user_sessions(self, user_id: str):
        user = await self.db_call(self.db.get_user, user_id)
        for ws, sess in list(self.sessions.items()):
            if sess is not None and sess.user_id == user_id and user:
                self.sessions[ws] = Session(user, sess.token)

    # ------------------------------------------------------------------ dispatch
    @staticmethod
    def _error(msg_id, code: str, error: str, response_type: str = "ERROR") -> dict:
        return {"type": response_type, "msg_id": msg_id, "ok": False, "success": False, "code": code, "error": error}

    async def handle_message(self, websocket, raw_message):
        try:
            data = json.loads(raw_message)
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, TypeError):
            await self._send(websocket, self._error(None, P.ERR_BAD_REQUEST, "Malformed message."))
            return

        action_name = data.get("action")
        payload = data.get("payload") or {}
        msg_id = data.get("msg_id")
        spec = ACTIONS.get(action_name)
        if spec is None:
            await self._send(websocket, self._error(msg_id, P.ERR_UNKNOWN_ACTION, f"Unknown action '{action_name}'."))
            return
        if not isinstance(payload, dict):
            await self._send(websocket, self._error(msg_id, P.ERR_BAD_REQUEST, "Payload must be an object.", spec.response_type))
            return

        session = self.sessions.get(websocket)
        if not spec.public:
            if session is None:
                await self._send(websocket, self._error(msg_id, P.ERR_AUTH_REQUIRED, "Please log in first.", spec.response_type))
                return
            if session.must_change_password and not spec.allow_pending_password:
                await self._send(websocket, self._error(msg_id, P.ERR_PASSWORD_CHANGE_REQUIRED,
                                                        "You must change your password before continuing.", spec.response_type))
                return
            if spec.roles and session.role not in spec.roles:
                logger.warning("Denied '%s' for user '%s' (role %s)", action_name, session.user_id, session.role)
                await self._send(websocket, self._error(msg_id, P.ERR_FORBIDDEN,
                                                        "Permission denied for your role.", spec.response_type))
                return

        logger.info("Action '%s' from '%s'", action_name, session.user_id if session else "-")
        try:
            result = await spec.func(self, websocket, session, payload, msg_id)
        except _AlreadyReplied:
            return
        except PermissionError as e:
            reply = self._error(msg_id, P.ERR_FORBIDDEN, str(e) or "Permission denied.", spec.response_type)
        except (ValueError, KeyError) as e:
            reply = self._error(msg_id, P.ERR_VALIDATION, str(e).strip("'\"") or "Invalid request.", spec.response_type)
        except sqlite3.IntegrityError as e:
            logger.warning("Integrity error in '%s': %s", action_name, e)
            reply = self._error(msg_id, P.ERR_VALIDATION, "The request conflicts with existing data.", spec.response_type)
        except Exception:
            ref = uuid.uuid4().hex[:8].upper()
            logger.exception("Unhandled error in '%s' (ref %s)", action_name, ref)
            reply = self._error(msg_id, P.ERR_INTERNAL, f"Internal server error (ref {ref}). Please contact the administrator.",
                                spec.response_type)
        else:
            reply = {"type": spec.response_type, "msg_id": msg_id, "ok": True, "success": True}
            reply.update(result or {})
        await self._send(websocket, reply)

    async def handler(self, websocket):
        self.sessions[websocket] = None
        logger.info("Client connected from %s", websocket.remote_address)
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.ConnectionClosed:
            pass
        except Exception:
            logger.exception("Connection handler crashed")
        finally:
            sess = self.sessions.pop(websocket, None)
            logger.info("Client disconnected: %s (%s)", sess.user_id if sess else "-", websocket.remote_address)

    async def start_background(self, backups: bool = True):
        """Starts listening and returns immediately (used by tests and embedded mode)."""
        self._ws_server = await websockets.serve(self.handler, self.host, self.port, max_size=P.MAX_FRAME_BYTES)
        if backups:
            from app.services.maintenance import BackupScheduler
            self.backup_scheduler = BackupScheduler(self.db, run_in_executor=self.db_call)
            self._backup_task = asyncio.ensure_future(self.backup_scheduler.run())
        if self.port == 0:
            self.port = self._ws_server.sockets[0].getsockname()[1]
        return self._ws_server

    async def stop(self):
        if self._backup_task:
            self._backup_task.cancel()
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        self._db_executor.shutdown(wait=False)
        self._export_executor.shutdown(wait=False)

    async def start(self):
        logger.info(f"Starting Central WebSocket Server on ws://{self.host}:{self.port} (LAN-only)")
        await self.start_background()
        await asyncio.Future()

    # ================================================================== ACTIONS
    # ---------------- authentication ----------------
    @action("PING", public=True, response_type="PONG")
    async def a_ping(self, ws, session, payload, msg_id):
        return {"protocol": P.PROTOCOL_VERSION}

    @action("LOGIN", public=True, response_type="LOGIN_RESPONSE")
    async def a_login(self, ws, session, payload, msg_id):
        if payload.get("protocol") != P.PROTOCOL_VERSION:
            raise PermissionError("This DeskApp version does not match the Central Server. "
                                  "Please install the same DeskApp version on this PC and the server.")
        uid = str(payload.get("user_id") or "").strip()
        pwd = payload.get("password") or ""
        if not uid or not pwd:
            raise ValueError("User ID and password are required.")

        count, locked_until = self._failed_logins.get(uid, (0, 0))
        if locked_until > time.monotonic():
            wait = int(locked_until - time.monotonic()) + 1
            await self._send(ws, self._error(msg_id, P.ERR_RATE_LIMITED,
                                             f"Too many failed attempts. Try again in {wait} seconds.", "LOGIN_RESPONSE"))
            raise _AlreadyReplied()

        user = await self.db_call(self.db.authenticate, uid, pwd)
        if not user:
            count += 1
            self._failed_logins[uid] = (count, time.monotonic() + LOCKOUT_SECONDS if count >= MAX_FAILED_LOGINS else 0)
            logger.warning("Failed login for '%s' from %s", uid, ws.remote_address)
            raise ValueError("Invalid User ID or Password.")
        self._failed_logins.pop(uid, None)

        token = await self.db_call(self.db.create_session, user["user_id"])
        sess = Session(user, token)
        self.sessions[ws] = sess
        settings = await self.db_call(self.db.get_settings)
        return {"user": sess.public_user(), "session_token": token, "protocol": P.PROTOCOL_VERSION,
                "policy": {"password_min_length": settings["password_min_length"]}}

    @action("RESUME", public=True, response_type="RESUME_RESPONSE")
    async def a_resume(self, ws, session, payload, msg_id):
        if payload.get("protocol") != P.PROTOCOL_VERSION:
            raise PermissionError("This DeskApp version does not match the Central Server.")
        token = payload.get("session_token")
        user = await self.db_call(self.db.resolve_session, token)
        if not user:
            await self._send(ws, self._error(msg_id, P.ERR_SESSION_EXPIRED,
                                             "Your session has expired. Please log in again.", "RESUME_RESPONSE"))
            raise _AlreadyReplied()
        sess = Session(user, token)
        self.sessions[ws] = sess
        return {"user": sess.public_user()}

    @action("LOGOUT", allow_pending_password=True)
    async def a_logout(self, ws, session, payload, msg_id):
        await self.db_call(self.db.delete_session, session.token)
        self.sessions[ws] = None
        return {}

    @action("CHANGE_PASSWORD", allow_pending_password=True, response_type="CHANGE_PASSWORD_RESPONSE")
    async def a_change_password(self, ws, session, payload, msg_id):
        # The old password is only waived for the forced first-login change on this authenticated session.
        await self.db_call(self.db.change_password, session.user_id, payload.get("new_password"),
                           payload.get("old_password"), require_old=not session.must_change_password)
        await self.db_call(self.db.delete_user_sessions, session.user_id, keep_token=session.token)
        session.must_change_password = False
        return {"user": session.public_user()}

    # ---------------- snapshot ----------------
    async def _head_tasks(self, session: Session, project_id: str = None) -> list:
        if not session.discipline_id:
            return []
        projects = await self.db_call(self.db.get_projects, include_hidden=False)
        visible = {p["project_id"] for p in projects}
        tasks = await self.db_call(self.db.get_tasks, project_id=project_id, discipline_id=session.discipline_id,
                                   assigned_head_id=session.user_id, include_hidden=False)
        return [t for t in tasks if t["project_id"] in visible]

    @action("GET_SNAPSHOT", response_type="INITIAL_SNAPSHOT")
    async def a_snapshot(self, ws, session, payload, msg_id):
        projects = await self.db_call(self.db.get_projects, include_hidden=False)
        disciplines = await self.db_call(self.db.get_disciplines, include_hidden=False)
        if session.role == ROLE_HEAD:
            tasks = await self._head_tasks(session)
            pending = await self.db_call(self.db.get_priority_notifications, employee_id=session.user_id, status="PENDING")
        else:
            tasks = await self.db_call(self.db.get_tasks, include_hidden=False)
            pending = []
        return {"projects": projects, "disciplines": disciplines, "tasks": tasks,
                "pending_notifications": pending, "user": session.public_user()}

    # ---------------- progress logs ----------------
    @action("SUBMIT_LOG", roles=(ROLE_HEAD,))
    async def a_submit_log(self, ws, session, payload, msg_id):
        _require(payload, "log_id", "project_id", "task_id", "start_date", "end_date", "progress_stage")
        data = dict(payload)
        data["employee_id"] = session.user_id  # never trust identity from the payload
        saved = await self.db_call(self.db.submit_progress_log, data)
        await self.broadcast({"type": "NEW_LOG_EVENT", "log": saved}, target_roles=OVERSIGHT)
        return {"id": saved["log_id"], "log": saved}

    @action("CALCULATE_NEXT_REVISION", roles=(ROLE_HEAD,), response_type="NEXT_REVISION_RESPONSE")
    async def a_next_revision(self, ws, session, payload, msg_id):
        rev = await self.db_call(self.db.get_next_revision_number, session.user_id,
                                 payload.get("project_id"), payload.get("task_id"))
        return {"revision_number": rev}

    @action("GENERATE_NEXT_TASK_ID", roles=MANAGERS, response_type="NEXT_TASK_ID_RESPONSE")
    async def a_next_task_id(self, ws, session, payload, msg_id):
        return {"task_id": await self.db_call(self.db.generate_next_task_id, payload.get("project_id"))}

    @action("GET_RECENT_LOGS", roles=OVERSIGHT, response_type="RECENT_LOGS_RESPONSE")
    async def a_recent_logs(self, ws, session, payload, msg_id):
        limit = min(int(payload.get("limit") or 100), 1000)
        return {"logs": await self.db_call(self.db.get_progress_logs, limit=limit)}

    # ---------------- task proposals ----------------
    @action("PROPOSE_TASK", roles=(ROLE_HEAD,))
    async def a_propose_task(self, ws, session, payload, msg_id):
        _require(payload, "proposal_id", "project_id", "task_name")
        if not session.discipline_id:
            raise PermissionError("Your account has no discipline. Ask the Admin to assign one.")
        prop = await self.db_call(
            self.db.create_task_proposal,
            project_id=payload.get("project_id"), task_name=str(payload.get("task_name")).strip(),
            proposed_by_id=session.user_id, discipline_id=session.discipline_id,
            planned_start_date=payload.get("planned_start_date"), planned_end_date=payload.get("planned_end_date"),
            proposal_id=payload.get("proposal_id"))
        await self.broadcast({"type": "NEW_TASK_PROPOSAL_EVENT", "proposal": prop}, target_roles=MANAGERS)
        await self.notify_changed("proposals", roles=MANAGERS)
        return {"id": prop["proposal_id"], "proposal": prop}

    @action("APPROVE_TASK_PROPOSAL", roles=MANAGERS)
    async def a_approve_proposal(self, ws, session, payload, msg_id):
        _require(payload, "proposal_id")
        prop = await self.db_call(self.db.approve_task_proposal, payload["proposal_id"], session.user_id)
        await self.broadcast({"type": "TASK_PROPOSAL_DECIDED_EVENT", "proposal": prop},
                             target_roles=MANAGERS, extra_user_ids=(prop.get("proposed_by_id"),))
        await self.notify_changed("tasks")
        await self.notify_changed("proposals", roles=MANAGERS, extra_user_ids=(prop.get("proposed_by_id"),))
        return {"proposal": prop}

    @action("REJECT_TASK_PROPOSAL", roles=MANAGERS)
    async def a_reject_proposal(self, ws, session, payload, msg_id):
        _require(payload, "proposal_id", "reason")
        prop = await self.db_call(self.db.reject_task_proposal, payload["proposal_id"], session.user_id, payload["reason"])
        await self.broadcast({"type": "TASK_PROPOSAL_DECIDED_EVENT", "proposal": prop},
                             target_roles=MANAGERS, extra_user_ids=(prop.get("proposed_by_id"),))
        await self.notify_changed("proposals", roles=MANAGERS, extra_user_ids=(prop.get("proposed_by_id"),))
        return {"proposal": prop}

    @action("GET_TASK_PROPOSALS", roles=(ROLE_HEAD,) + MANAGERS, response_type="TASK_PROPOSALS_RESPONSE")
    async def a_get_proposals(self, ws, session, payload, msg_id):
        proposed_by = session.user_id if session.role == ROLE_HEAD else payload.get("proposed_by_id")
        props = await self.db_call(self.db.get_task_proposals, project_id=payload.get("project_id"),
                                   proposed_by_id=proposed_by, status=payload.get("status"))
        return {"proposals": props}

    # ---------------- date change requests ----------------
    @action("REQUEST_TASK_DATE_CHANGE", roles=(ROLE_HEAD,))
    async def a_request_date_change(self, ws, session, payload, msg_id):
        _require(payload, "request_id", "task_id", "new_start_date", "new_end_date", "reason")
        visible = {t["task_id"] for t in await self._head_tasks(session)}
        if payload["task_id"] not in visible:
            raise PermissionError("You can only request date changes for tasks in your discipline.")
        req = await self.db_call(
            self.db.create_task_date_change_request,
            task_id=payload["task_id"], requested_by_id=session.user_id,
            new_start_date=payload["new_start_date"], new_end_date=payload["new_end_date"],
            reason=payload["reason"], request_id=payload["request_id"])
        await self.broadcast({"type": "TASK_DATE_CHANGE_EVENT", "request": req, "event": "CREATED"},
                             target_roles=MANAGERS)
        await self.notify_changed("date_changes", roles=MANAGERS)
        return {"id": req["request_id"], "request": req}

    @action("APPROVE_DATE_CHANGE", roles=MANAGERS)
    async def a_approve_date_change(self, ws, session, payload, msg_id):
        _require(payload, "request_id")
        dec = await self.db_call(self.db.approve_task_date_change_request, payload["request_id"], session.user_id)
        await self.broadcast({"type": "TASK_DATE_CHANGE_EVENT", "request": dec, "event": "APPROVED"},
                             target_roles=MANAGERS, extra_user_ids=(dec.get("requested_by_id"),))
        await self.notify_changed("tasks")
        await self.notify_changed("date_changes", roles=MANAGERS, extra_user_ids=(dec.get("requested_by_id"),))
        return {"request": dec}

    @action("REJECT_DATE_CHANGE", roles=MANAGERS)
    async def a_reject_date_change(self, ws, session, payload, msg_id):
        _require(payload, "request_id", "reason")
        dec = await self.db_call(self.db.reject_task_date_change_request, payload["request_id"],
                                 session.user_id, payload["reason"])
        await self.broadcast({"type": "TASK_DATE_CHANGE_EVENT", "request": dec, "event": "REJECTED"},
                             target_roles=MANAGERS, extra_user_ids=(dec.get("requested_by_id"),))
        await self.notify_changed("date_changes", roles=MANAGERS, extra_user_ids=(dec.get("requested_by_id"),))
        return {"request": dec}

    @action("GET_DATE_CHANGE_REQUESTS", roles=(ROLE_HEAD,) + MANAGERS, response_type="DATE_CHANGE_REQUESTS_RESPONSE")
    async def a_get_date_changes(self, ws, session, payload, msg_id):
        requested_by = session.user_id if session.role == ROLE_HEAD else payload.get("requested_by_id")
        reqs = await self.db_call(self.db.get_task_date_change_requests, status=payload.get("status"),
                                  task_id=payload.get("task_id"), requested_by_id=requested_by)
        return {"requests": reqs}

    # ---------------- COO priority alerts ----------------
    @action("COO_NOTIFY", roles=(ROLE_COO, ROLE_SUPER_ADMIN), response_type="NOTIFY_DISPATCH_CONFIRMATION")
    async def a_coo_notify(self, ws, session, payload, msg_id):
        _require(payload, "target_employee_id", "message")
        notif = await self.db_call(self.db.create_priority_notification, session.user_id,
                                   payload["target_employee_id"], payload["message"],
                                   notification_id=payload.get("notification_id"))
        delivered = await self.send_to_user(payload["target_employee_id"],
                                            {"type": "COO_PRIORITY_ALERT", "notification": notif})
        return {"notification_id": notif["notification_id"], "notification": notif,
                "target_employee_id": payload["target_employee_id"], "delivered": delivered}

    @action("RESPOND_NOTIFICATION", roles=(ROLE_HEAD,))
    async def a_respond_notification(self, ws, session, payload, msg_id):
        _require(payload, "notification_id", "response_status")
        res = await self.db_call(self.db.respond_priority_notification, payload["notification_id"],
                                 session.user_id, payload["response_status"])
        await self.broadcast({"type": "NOTIFICATION_RESPONSE_EVENT", "notification": res},
                             target_roles=(ROLE_COO, ROLE_SUPER_ADMIN))
        return {"id": payload["notification_id"], "notification": res}

    @action("GET_NOTIFICATIONS", roles=(ROLE_HEAD, ROLE_COO, ROLE_SUPER_ADMIN), response_type="NOTIFICATIONS_RESPONSE")
    async def a_get_notifications(self, ws, session, payload, msg_id):
        employee = session.user_id if session.role == ROLE_HEAD else payload.get("employee_id")
        notifs = await self.db_call(self.db.get_priority_notifications, employee_id=employee,
                                    status=payload.get("status"), limit=min(int(payload.get("limit") or 200), 1000))
        return {"notifications": notifs}

    # ---------------- disciplines ----------------
    @action("GET_DISCIPLINES", response_type="DISCIPLINES_RESPONSE")
    async def a_get_disciplines(self, ws, session, payload, msg_id):
        include_hidden = bool(payload.get("include_hidden")) and session.role in MANAGERS
        return {"disciplines": await self.db_call(self.db.get_disciplines, include_hidden=include_hidden)}

    @action("ADD_DISCIPLINE", roles=MANAGERS)
    async def a_add_discipline(self, ws, session, payload, msg_id):
        _require(payload, "discipline_id", "name")
        d = await self.db_call(self.db.add_discipline, payload["discipline_id"], payload["name"])
        await self.notify_changed("disciplines", "tasks")
        return {"discipline": d}

    @action("TOGGLE_HIDE_DISCIPLINE", roles=MANAGERS)
    async def a_toggle_discipline(self, ws, session, payload, msg_id):
        _require(payload, "discipline_id")
        d = await self.db_call(self.db.toggle_hide_discipline, payload["discipline_id"], payload.get("current_hidden"))
        await self.notify_changed("disciplines", "tasks")
        return {"discipline": d}

    # ---------------- users ----------------
    @action("GET_USERS", roles=OVERSIGHT, response_type="USERS_RESPONSE")
    async def a_get_users(self, ws, session, payload, msg_id):
        role = payload.get("role")
        if session.role in (ROLE_ADMIN, ROLE_COO):
            role = ROLE_HEAD  # Admin manages Heads only; COO only needs the Heads list
        return {"users": await self.db_call(self.db.get_users, role=role, discipline_id=payload.get("discipline_id"))}

    @action("CREATE_USER", roles=MANAGERS, response_type="CREATE_USER_RESPONSE")
    async def a_create_user(self, ws, session, payload, msg_id):
        new_u = await self.db_call(self.db.create_user, actor_role=session.role, user_id=payload.get("user_id"),
                                   full_name=payload.get("full_name"), role=payload.get("role"),
                                   discipline_id=payload.get("discipline_id"))
        await self.notify_changed("users", roles=OVERSIGHT)
        return {"user": new_u}

    @action("UPDATE_USER", roles=MANAGERS, response_type="UPDATE_USER_RESPONSE")
    async def a_update_user(self, ws, session, payload, msg_id):
        _require(payload, "user_id")
        up_u = await self.db_call(self.db.update_user, actor_role=session.role, user_id=payload["user_id"],
                                  full_name=payload.get("full_name"), discipline_id=payload.get("discipline_id"),
                                  role=payload.get("role"))
        await self._refresh_user_sessions(payload["user_id"])
        await self.notify_changed("users", "tasks")
        return {"user": up_u}

    @action("RESET_PASSWORD", roles=MANAGERS, response_type="RESET_PASSWORD_RESPONSE")
    async def a_reset_password(self, ws, session, payload, msg_id):
        _require(payload, "user_id")
        await self.db_call(self.db.reset_user_password, actor_role=session.role, user_id=payload["user_id"])
        if payload["user_id"] != session.user_id:
            await self._revoke_user_sessions(payload["user_id"], "Password was reset by an administrator")
        return {"user_id": payload["user_id"]}

    # ---------------- projects & tasks ----------------
    @action("GET_PROJECTS", response_type="PROJECTS_RESPONSE")
    async def a_get_projects(self, ws, session, payload, msg_id):
        include_hidden = bool(payload.get("include_hidden")) and session.role in MANAGERS
        return {"projects": await self.db_call(self.db.get_projects, include_hidden=include_hidden)}

    @action("ADD_PROJECT", roles=MANAGERS)
    async def a_add_project(self, ws, session, payload, msg_id):
        _require(payload, "project_id", "name")
        p = await self.db_call(self.db.add_project, payload["project_id"], payload["name"], payload.get("description", ""))
        await self.notify_changed("projects")
        return {"project": p}

    @action("TOGGLE_HIDE_PROJECT", roles=MANAGERS)
    async def a_toggle_project(self, ws, session, payload, msg_id):
        _require(payload, "project_id")
        p = await self.db_call(self.db.toggle_hide_project, payload["project_id"], payload.get("current_hidden"))
        await self.notify_changed("projects", "tasks")
        return {"project": p}

    @action("DELETE_PROJECT", roles=MANAGERS)
    async def a_delete_project(self, ws, session, payload, msg_id):
        _require(payload, "project_id")
        p = await self.db_call(self.db.delete_project, payload["project_id"], session.user_id)
        await self.notify_changed("projects", "tasks")
        return {"project": p}

    @action("GET_TASKS", response_type="TASKS_RESPONSE")
    async def a_get_tasks(self, ws, session, payload, msg_id):
        if session.role == ROLE_HEAD:
            tasks = await self._head_tasks(session, payload.get("project_id"))
        else:
            include_hidden = bool(payload.get("include_hidden")) and session.role in MANAGERS
            tasks = await self.db_call(self.db.get_tasks, project_id=payload.get("project_id"),
                                       discipline_id=payload.get("discipline_id"),
                                       assigned_head_id=payload.get("assigned_head_id"), include_hidden=include_hidden)
        return {"tasks": tasks}

    @action("ADD_TASK", roles=MANAGERS)
    async def a_add_task(self, ws, session, payload, msg_id):
        _require(payload, "project_id", "name", "discipline_id")
        t = await self.db_call(
            self.db.add_task, project_id=payload["project_id"], task_id=payload.get("task_id"), name=payload["name"],
            discipline_id=payload["discipline_id"], planned_start_date=payload.get("planned_start_date"),
            planned_end_date=payload.get("planned_end_date"), description=payload.get("description", ""),
            proposed_by_id=None, assigned_head_id=payload.get("assigned_head_id"))
        await self.notify_changed("tasks")
        return {"task": t}

    @action("UPDATE_TASK", roles=MANAGERS)
    async def a_update_task(self, ws, session, payload, msg_id):
        _require(payload, "task_id")
        kwargs = {k: payload.get(k) for k in ("name", "discipline_id", "planned_start_date",
                                              "planned_end_date", "description")}
        if "assigned_head_id" in payload:
            kwargs["assigned_head_id"] = payload.get("assigned_head_id")
        t = await self.db_call(self.db.update_task, task_id=payload["task_id"], **kwargs)
        await self.notify_changed("tasks")
        return {"task": t}

    @action("UPDATE_TASK_DATES", roles=MANAGERS)
    async def a_update_task_dates(self, ws, session, payload, msg_id):
        _require(payload, "task_id", "planned_start_date", "planned_end_date")
        t = await self.db_call(self.db.update_task_dates, payload["task_id"],
                               payload["planned_start_date"], payload["planned_end_date"])
        await self.notify_changed("tasks")
        return {"task": t}

    @action("TOGGLE_HIDE_TASK", roles=MANAGERS)
    async def a_toggle_task(self, ws, session, payload, msg_id):
        _require(payload, "task_id")
        t = await self.db_call(self.db.toggle_hide_task, payload["task_id"], payload.get("current_hidden"))
        await self.notify_changed("tasks")
        return {"task": t}

    @action("DELETE_TASK", roles=MANAGERS)
    async def a_delete_task(self, ws, session, payload, msg_id):
        _require(payload, "task_id")
        t = await self.db_call(self.db.delete_task, payload["task_id"], session.user_id)
        await self.notify_changed("tasks")
        return {"task": t}

    @action("GET_PROJECT_TIMELINE", response_type="PROJECT_TIMELINE_RESPONSE")
    async def a_timeline(self, ws, session, payload, msg_id):
        _require(payload, "project_id")
        if session.role == ROLE_HEAD:
            data = await self.db_call(self.db.get_project_timeline_data, payload["project_id"],
                                      discipline_id=session.discipline_id or "__none__",
                                      assigned_head_id=session.user_id)
        else:
            data = await self.db_call(self.db.get_project_timeline_data, payload["project_id"])
        return {"data": data}

    # ---------------- system settings ----------------
    @action("GET_SETTINGS", roles=(ROLE_SUPER_ADMIN,), response_type="SETTINGS_RESPONSE")
    async def a_get_settings(self, ws, session, payload, msg_id):
        from app.database.db_manager import SYSTEM_SETTINGS
        settings = await self.db_call(self.db.get_settings)
        info = await self.db_call(self.db.get_system_info)
        from app.core.config import APP_VERSION
        info.update({"port": self.port, "protocol": P.PROTOCOL_VERSION, "version": APP_VERSION,
                     "connected_users": sorted({s.user_id for _, s in self._live_sessions()})})
        labels = {k: spec[4] for k, spec in SYSTEM_SETTINGS.items()}
        return {"settings": settings, "labels": labels, "info": info}

    @action("UPDATE_SETTINGS", roles=(ROLE_SUPER_ADMIN,), response_type="SETTINGS_RESPONSE")
    async def a_update_settings(self, ws, session, payload, msg_id):
        settings = await self.db_call(self.db.update_settings, payload.get("settings") or {}, session.user_id)
        await self.notify_changed("settings", roles=(ROLE_SUPER_ADMIN,))
        return {"settings": settings}

    # ---------------- analytics & export ----------------
    @action("GET_ANALYTICS", roles=MANAGERS, response_type="ANALYTICS_RESPONSE")
    async def a_analytics(self, ws, session, payload, msg_id):
        return {"data": await self.db_call(self.db.get_analytics_data)}

    @action("EXPORT_EXCEL_REQUEST", roles=OVERSIGHT, response_type="EXPORT_EXCEL_RESPONSE")
    async def a_export(self, ws, session, payload, msg_id):
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(self._export_executor, functools.partial(
            self.excel_service.export_logs_to_excel,
            project_id=payload.get("project_id"), discipline_id=payload.get("discipline_id"),
            employee_id=payload.get("employee_id"), start_date=payload.get("start_date"),
            end_date=payload.get("end_date"), generated_by=f"{session.full_name or ''} ({session.user_id})".strip()))
        # Stream the workbook in chunks so no frame exceeds the WebSocket size limit.
        size = self.export_chunk_bytes
        total = max(1, (len(raw) + size - 1) // size)
        for i in range(total):
            chunk = raw[i * size:(i + 1) * size]
            ok = await self._send(ws, {"type": "EXPORT_EXCEL_CHUNK", "msg_id": msg_id, "index": i, "total": total,
                                       "data_b64": base64.b64encode(chunk).decode("ascii")})
            if not ok:
                raise ConnectionError("Client disconnected during export.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return {"filename": f"Progress_Logs_{payload.get('discipline_id') or 'ALL'}_{stamp}.xlsx",
                "total_chunks": total, "size": len(raw)}

