import asyncio
import json
import logging
import base64
import websockets
from datetime import datetime
from app.core.config import DEFAULT_WS_PORT, DEFAULT_HOST, ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
from app.database.db_manager import DBManager
from app.services.excel_service import ExcelExportService

logger = logging.getLogger(__name__)

class CentralWebSocketServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_WS_PORT, standalone: bool = False):
        self.host = host
        self.port = port
        self.standalone = standalone
        self.db = DBManager(standalone=standalone)
        self.excel_service = ExcelExportService(self.db)
        # Active connections: websocket -> {"user_id": str, "role": str, "discipline_id": str}
        self.clients = {}

        # Perform daily database backup on server start
        self.db.backup_database()

    async def register(self, websocket):
        self.clients[websocket] = {"user_id": None, "role": None, "discipline_id": None}
        logger.info(f"Client connected from {websocket.remote_address}")

    async def unregister(self, websocket):
        if websocket in self.clients:
            user_id = self.clients[websocket].get("user_id")
            logger.info(f"Client disconnected: {user_id} ({websocket.remote_address})")
            del self.clients[websocket]

    async def broadcast(self, message_dict: dict, target_roles: list = None, exclude_ws=None):
        payload = json.dumps(message_dict)
        for ws, info in list(self.clients.items()):
            if ws == exclude_ws:
                continue
            if target_roles is None or info.get("role") in target_roles:
                try:
                    await ws.send(payload)
                except Exception as e:
                    logger.error(f"Error broadcasting to {info.get('user_id')}: {e}")

    async def send_to_user(self, user_id: str, message_dict: dict):
        payload = json.dumps(message_dict)
        sent = False
        for ws, info in list(self.clients.items()):
            if info.get("user_id") == user_id:
                try:
                    await ws.send(payload)
                    sent = True
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")
        return sent

    async def handle_message(self, websocket, raw_message: str):
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON packet")
            return

        action = data.get("action")
        payload = data.get("payload", {})
        request_msg_id = data.get("msg_id") # optional correlation ID

        client_info = self.clients.get(websocket, {})
        actor_user_id = client_info.get("user_id")
        actor_role = client_info.get("role")

        logger.info(f"Server action '{action}' from user '{actor_user_id}' (role='{actor_role}')")

        # ----------------- 1. AUTHENTICATION (B1) -----------------
        if action == "LOGIN":
            uid = payload.get("user_id", "").strip()
            pwd = payload.get("password", "")
            user = self.db.get_user(uid)

            if user and self.db.verify_password(pwd, user["password_hash"], user["password_salt"]):
                # Update websocket info
                self.clients[websocket]["user_id"] = user["user_id"]
                self.clients[websocket]["role"] = user["role"]
                self.clients[websocket]["discipline_id"] = user["discipline_id"]

                resp = {
                    "type": "LOGIN_RESPONSE",
                    "success": True,
                    "msg_id": request_msg_id,
                    "user": {
                        "user_id": user["user_id"],
                        "full_name": user["full_name"],
                        "role": user["role"],
                        "discipline_id": user["discipline_id"],
                        "discipline_name": user.get("discipline_name"),
                        "must_change_password": user["must_change_password"]
                    }
                }
            else:
                resp = {
                    "type": "LOGIN_RESPONSE",
                    "success": False,
                    "msg_id": request_msg_id,
                    "error": "Invalid User ID or Password."
                }
            await websocket.send(json.dumps(resp))

        elif action == "CHANGE_PASSWORD":
            uid = payload.get("user_id")
            old_pwd = payload.get("old_password")
            new_pwd = payload.get("new_password")
            force = payload.get("force", False)

            try:
                self.db.change_password(uid, new_pwd, old_pwd, force=force)
                await websocket.send(json.dumps({
                    "type": "CHANGE_PASSWORD_RESPONSE",
                    "success": True,
                    "msg_id": request_msg_id
                }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "CHANGE_PASSWORD_RESPONSE",
                    "success": False,
                    "msg_id": request_msg_id,
                    "error": str(e)
                }))

        elif action == "IDENTIFY":
            uid = payload.get("user_id")
            role = payload.get("role")
            user = self.db.get_user(uid)
            disc_id = user["discipline_id"] if user else None

            self.clients[websocket]["user_id"] = uid
            self.clients[websocket]["role"] = role
            self.clients[websocket]["discipline_id"] = disc_id

            await self.send_initial_snapshot(websocket, uid, role, disc_id)

        # ----------------- 2. PROGRESS LOGS & ACKS (B4) -----------------
        elif action == "SUBMIT_LOG":
            log_id = payload.get("log_id")
            try:
                saved_log = self.db.submit_progress_log(payload)
                # Send reliable ACK back to client so client deletes from queue
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "SUBMIT_LOG",
                    "id": log_id,
                    "status": "SUCCESS"
                }))

                # Broadcast to COO, Admin, SuperAdmin
                await self.broadcast({
                    "type": "NEW_LOG_EVENT",
                    "log": saved_log
                }, target_roles=[ROLE_COO, ROLE_ADMIN, ROLE_SUPER_ADMIN])

            except Exception as e:
                logger.error(f"Error in SUBMIT_LOG: {e}")
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "SUBMIT_LOG",
                    "id": log_id,
                    "status": "ERROR",
                    "error": str(e)
                }))

        # ----------------- 3. REVISION NUMBER & TASK ID REQUESTS -----------------
        elif action == "CALCULATE_NEXT_REVISION":
            emp_id = payload.get("employee_id")
            prj_id = payload.get("project_id")
            tsk_id = payload.get("task_id")
            rev = self.db.get_next_revision_number(emp_id, prj_id, tsk_id)
            await websocket.send(json.dumps({
                "type": "NEXT_REVISION_RESPONSE",
                "msg_id": request_msg_id,
                "revision_number": rev
            }))

        elif action == "GENERATE_NEXT_TASK_ID":
            prj_id = payload.get("project_id")
            t_id = self.db.generate_next_task_id(prj_id)
            await websocket.send(json.dumps({
                "type": "NEXT_TASK_ID_RESPONSE",
                "msg_id": request_msg_id,
                "task_id": t_id
            }))

        # ----------------- 4. TASK PROPOSALS (A1) -----------------
        elif action == "PROPOSE_TASK":
            try:
                prop = self.db.create_task_proposal(
                    project_id=payload.get("project_id"),
                    task_name=payload.get("task_name"),
                    proposed_by_id=payload.get("proposed_by_id"),
                    discipline_id=payload.get("discipline_id"),
                    planned_start_date=payload.get("planned_start_date"),
                    planned_end_date=payload.get("planned_end_date"),
                    proposal_id=payload.get("proposal_id")
                )
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "PROPOSE_TASK",
                    "id": prop["proposal_id"],
                    "status": "SUCCESS"
                }))
                await self.broadcast({
                    "type": "NEW_TASK_PROPOSAL_EVENT",
                    "proposal": prop
                })
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "PROPOSE_TASK",
                    "id": payload.get("proposal_id"),
                    "status": "ERROR",
                    "error": str(e)
                }))

        elif action == "APPROVE_TASK_PROPOSAL":
            try:
                prop = self.db.approve_task_proposal(payload.get("proposal_id"), payload.get("admin_id"))
                await self.broadcast({
                    "type": "TASK_PROPOSAL_DECIDED_EVENT",
                    "proposal": prop
                })
                await self.broadcast({
                    "type": "GLOBAL_DATA_REFRESH",
                    "reason": "TASK_PROPOSAL_APPROVED"
                })
            except Exception as e:
                logger.error(f"Error approving task proposal: {e}")

        elif action == "REJECT_TASK_PROPOSAL":
            try:
                prop = self.db.reject_task_proposal(
                    payload.get("proposal_id"),
                    payload.get("admin_id"),
                    payload.get("reason", "No reason provided")
                )
                await self.broadcast({
                    "type": "TASK_PROPOSAL_DECIDED_EVENT",
                    "proposal": prop
                })
                await self.broadcast({
                    "type": "GLOBAL_DATA_REFRESH",
                    "reason": "TASK_PROPOSAL_REJECTED"
                })
            except Exception as e:
                logger.error(f"Error rejecting task proposal: {e}")

        elif action == "GET_TASK_PROPOSALS":
            props = self.db.get_task_proposals(
                project_id=payload.get("project_id"),
                proposed_by_id=payload.get("proposed_by_id"),
                status=payload.get("status")
            )
            await websocket.send(json.dumps({
                "type": "TASK_PROPOSALS_RESPONSE",
                "msg_id": request_msg_id,
                "proposals": props
            }))

        # ----------------- 5. TASK DATE CHANGE REQUESTS (A2) -----------------
        elif action == "REQUEST_TASK_DATE_CHANGE":
            req_id = payload.get("request_id")
            try:
                req = self.db.create_task_date_change_request(
                    task_id=payload.get("task_id"),
                    requested_by_id=payload.get("requested_by_id"),
                    new_start_date=payload.get("new_start_date"),
                    new_end_date=payload.get("new_end_date"),
                    reason=payload.get("reason"),
                    request_id=req_id
                )
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "REQUEST_TASK_DATE_CHANGE",
                    "id": req["request_id"],
                    "status": "SUCCESS"
                }))
                await self.broadcast({
                    "type": "TASK_DATE_CHANGE_EVENT",
                    "request": req,
                    "event": "CREATED"
                }, target_roles=[ROLE_ADMIN, ROLE_SUPER_ADMIN])
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "REQUEST_TASK_DATE_CHANGE",
                    "id": req_id,
                    "status": "ERROR",
                    "error": str(e)
                }))

        elif action == "APPROVE_DATE_CHANGE":
            try:
                dec = self.db.approve_task_date_change_request(payload.get("request_id"), payload.get("admin_id"))
                await self.broadcast({
                    "type": "TASK_DATE_CHANGE_EVENT",
                    "request": dec,
                    "event": "APPROVED"
                })
                await self.broadcast({
                    "type": "GLOBAL_DATA_REFRESH",
                    "reason": "DATE_CHANGE_APPROVED"
                })
            except Exception as e:
                logger.error(f"Error approving date change: {e}")

        elif action == "REJECT_DATE_CHANGE":
            try:
                dec = self.db.reject_task_date_change_request(
                    payload.get("request_id"),
                    payload.get("admin_id"),
                    payload.get("reason", "No reason provided")
                )
                await self.broadcast({
                    "type": "TASK_DATE_CHANGE_EVENT",
                    "request": dec,
                    "event": "REJECTED"
                })
            except Exception as e:
                logger.error(f"Error rejecting date change: {e}")

        elif action == "GET_DATE_CHANGE_REQUESTS":
            reqs = self.db.get_task_date_change_requests(
                status=payload.get("status"),
                task_id=payload.get("task_id"),
                requested_by_id=payload.get("requested_by_id")
            )
            await websocket.send(json.dumps({
                "type": "DATE_CHANGE_REQUESTS_RESPONSE",
                "msg_id": request_msg_id,
                "requests": reqs
            }))

        # ----------------- 6. COO PRIORITY NOTIFICATIONS -----------------
        elif action == "COO_NOTIFY":
            notif = self.db.create_priority_notification(
                payload.get("coo_id"),
                payload.get("target_employee_id"),
                payload.get("message")
            )
            # Dispatch urgent alert to target user if connected
            delivered = await self.send_to_user(payload.get("target_employee_id"), {
                "type": "COO_PRIORITY_ALERT",
                "notification": notif
            })
            await websocket.send(json.dumps({
                "type": "NOTIFY_DISPATCH_CONFIRMATION",
                "notification_id": notif["notification_id"],
                "target_employee_id": payload.get("target_employee_id"),
                "delivered": delivered
            }))

        elif action == "RESPOND_NOTIFICATION":
            notif_id = payload.get("notification_id")
            try:
                res = self.db.respond_priority_notification(
                    notif_id,
                    payload.get("employee_id"),
                    payload.get("response_status")
                )
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "RESPOND_NOTIFICATION",
                    "id": notif_id,
                    "status": "SUCCESS"
                }))
                await self.broadcast({
                    "type": "NOTIFICATION_RESPONSE_EVENT",
                    "notification": res
                }, target_roles=[ROLE_COO, ROLE_SUPER_ADMIN])
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "ACK",
                    "action": "RESPOND_NOTIFICATION",
                    "id": notif_id,
                    "status": "ERROR",
                    "error": str(e)
                }))

        # ----------------- 7. DISCIPLINES CRUD (A1) -----------------
        elif action == "GET_DISCIPLINES":
            discs = self.db.get_disciplines(include_hidden=payload.get("include_hidden", False))
            await websocket.send(json.dumps({
                "type": "DISCIPLINES_RESPONSE",
                "msg_id": request_msg_id,
                "disciplines": discs
            }))

        elif action == "ADD_DISCIPLINE":
            try:
                d = self.db.add_discipline(payload.get("discipline_id"), payload.get("name"))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "DISCIPLINE_ADDED"})
            except Exception as e:
                logger.error(f"Error adding discipline: {e}")

        elif action == "TOGGLE_HIDE_DISCIPLINE":
            try:
                self.db.toggle_hide_discipline(payload.get("discipline_id"), payload.get("current_hidden"))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "DISCIPLINE_VISIBILITY_CHANGED"})
            except Exception as e:
                logger.error(f"Error hiding discipline: {e}")

        # ----------------- 8. USER MANAGEMENT & ROLE ENFORCEMENT (B5) -----------------
        elif action == "GET_USERS":
            users = self.db.get_users(role=payload.get("role"), discipline_id=payload.get("discipline_id"))
            await websocket.send(json.dumps({
                "type": "USERS_RESPONSE",
                "msg_id": request_msg_id,
                "users": users
            }))

        elif action == "CREATE_USER":
            try:
                new_u = self.db.create_user(
                    actor_role=actor_role,
                    user_id=payload.get("user_id"),
                    full_name=payload.get("full_name"),
                    role=payload.get("role"),
                    discipline_id=payload.get("discipline_id")
                )
                await websocket.send(json.dumps({
                    "type": "CREATE_USER_RESPONSE",
                    "success": True,
                    "msg_id": request_msg_id,
                    "user": new_u
                }))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "USER_CREATED"})
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "CREATE_USER_RESPONSE",
                    "success": False,
                    "msg_id": request_msg_id,
                    "error": str(e)
                }))

        elif action == "UPDATE_USER":
            try:
                up_u = self.db.update_user(
                    actor_role=actor_role,
                    user_id=payload.get("user_id"),
                    full_name=payload.get("full_name"),
                    discipline_id=payload.get("discipline_id"),
                    role=payload.get("role")
                )
                await websocket.send(json.dumps({
                    "type": "UPDATE_USER_RESPONSE",
                    "success": True,
                    "msg_id": request_msg_id,
                    "user": up_u
                }))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "USER_UPDATED"})
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "UPDATE_USER_RESPONSE",
                    "success": False,
                    "msg_id": request_msg_id,
                    "error": str(e)
                }))

        elif action == "RESET_PASSWORD":
            try:
                res = self.db.reset_user_password(actor_role=actor_role, user_id=payload.get("user_id"))
                await websocket.send(json.dumps({
                    "type": "RESET_PASSWORD_RESPONSE",
                    "success": True,
                    "msg_id": request_msg_id
                }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "RESET_PASSWORD_RESPONSE",
                    "success": False,
                    "msg_id": request_msg_id,
                    "error": str(e)
                }))

        # ----------------- 9. PROJECT & TASK LIFECYCLE -----------------
        elif action == "GET_PROJECTS":
            prjs = self.db.get_projects(include_hidden=payload.get("include_hidden", False))
            await websocket.send(json.dumps({
                "type": "PROJECTS_RESPONSE",
                "msg_id": request_msg_id,
                "projects": prjs
            }))

        elif action == "ADD_PROJECT":
            try:
                p = self.db.add_project(
                    payload.get("project_id"),
                    payload.get("name"),
                    payload.get("description", "")
                )
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "PROJECT_ADDED"})
            except Exception as e:
                logger.error(f"Error adding project: {e}")

        elif action == "TOGGLE_HIDE_PROJECT":
            try:
                self.db.toggle_hide_project(payload.get("project_id"), payload.get("current_hidden"))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "PROJECT_VISIBILITY_CHANGED"})
            except Exception as e:
                logger.error(f"Error toggling project: {e}")

        elif action == "GET_TASKS":
            # If requesting user is HEAD, enforce discipline & assigned_head filter!
            req_disc = payload.get("discipline_id")
            req_head = payload.get("assigned_head_id")
            if actor_role == ROLE_HEAD:
                req_disc = client_info.get("discipline_id")
                req_head = actor_user_id
            tasks = self.db.get_tasks(
                project_id=payload.get("project_id"),
                discipline_id=req_disc,
                assigned_head_id=req_head,
                include_hidden=payload.get("include_hidden", False)
            )
            await websocket.send(json.dumps({
                "type": "TASKS_RESPONSE",
                "msg_id": request_msg_id,
                "tasks": tasks
            }))

        elif action == "ADD_TASK":
            try:
                t = self.db.add_task(
                    project_id=payload.get("project_id"),
                    task_id=payload.get("task_id"),
                    name=payload.get("name"),
                    discipline_id=payload.get("discipline_id"),
                    planned_start_date=payload.get("planned_start_date"),
                    planned_end_date=payload.get("planned_end_date"),
                    description=payload.get("description", ""),
                    proposed_by_id=payload.get("proposed_by_id"),
                    assigned_head_id=payload.get("assigned_head_id")
                )
                await websocket.send(json.dumps({
                    "type": "ADD_TASK_RESPONSE",
                    "success": True,
                    "task": t,
                    "msg_id": request_msg_id
                }))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "TASK_ADDED"})
            except Exception as e:
                logger.error(f"Error adding task: {e}")
                await websocket.send(json.dumps({
                    "type": "ADD_TASK_RESPONSE",
                    "success": False,
                    "error": str(e),
                    "msg_id": request_msg_id
                }))

        elif action == "UPDATE_TASK":
            try:
                self.db.update_task(
                    task_id=payload.get("task_id"),
                    name=payload.get("name"),
                    discipline_id=payload.get("discipline_id"),
                    assigned_head_id=payload.get("assigned_head_id"),
                    planned_start_date=payload.get("planned_start_date"),
                    planned_end_date=payload.get("planned_end_date"),
                    description=payload.get("description")
                )
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "TASK_UPDATED"})
            except Exception as e:
                logger.error(f"Error updating task: {e}")

        elif action == "UPDATE_TASK_DATES":
            try:
                self.db.update_task_dates(
                    payload.get("task_id"),
                    payload.get("planned_start_date"),
                    payload.get("planned_end_date")
                )
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "TASK_DATES_UPDATED"})
            except Exception as e:
                logger.error(f"Error updating task dates: {e}")

        elif action == "TOGGLE_HIDE_TASK":
            try:
                self.db.toggle_hide_task(payload.get("task_id"), payload.get("current_hidden"))
                await self.broadcast({"type": "GLOBAL_DATA_REFRESH", "reason": "TASK_VISIBILITY_CHANGED"})
            except Exception as e:
                logger.error(f"Error toggling task: {e}")

        elif action == "GET_PROJECT_TIMELINE":
            prj_id = payload.get("project_id")
            tl_data = self.db.get_project_timeline_data(prj_id)
            await websocket.send(json.dumps({
                "type": "PROJECT_TIMELINE_RESPONSE",
                "msg_id": request_msg_id,
                "data": tl_data
            }))

        # ----------------- 10. ANALYTICS & EXCEL EXPORTS (A4, B2) -----------------
        elif action == "GET_ANALYTICS":
            data_an = self.db.get_analytics_data()
            await websocket.send(json.dumps({
                "type": "ANALYTICS_RESPONSE",
                "msg_id": request_msg_id,
                "data": data_an
            }))

        elif action == "EXPORT_EXCEL_REQUEST":
            try:
                raw_bytes = self.excel_service.export_logs_to_excel(
                    project_id=payload.get("project_id"),
                    discipline_id=payload.get("discipline_id"),
                    employee_id=payload.get("employee_id"),
                    start_date=payload.get("start_date"),
                    end_date=payload.get("end_date")
                )
                b64_content = base64.b64encode(raw_bytes).decode("utf-8")
                await websocket.send(json.dumps({
                    "type": "EXPORT_EXCEL_RESPONSE",
                    "msg_id": request_msg_id,
                    "success": True,
                    "data_b64": b64_content,
                    "filename": f"Progress_Logs_{payload.get('discipline_id') or 'ALL'}.xlsx"
                }))
            except Exception as e:
                logger.error(f"Error in EXPORT_EXCEL_REQUEST: {e}")
                await websocket.send(json.dumps({
                    "type": "EXPORT_EXCEL_RESPONSE",
                    "msg_id": request_msg_id,
                    "success": False,
                    "error": str(e)
                }))

        elif action == "GET_RECENT_LOGS":
            # Used for COO live feed initial load
            recent = self.db.get_progress_logs()[:100]
            await websocket.send(json.dumps({
                "type": "RECENT_LOGS_RESPONSE",
                "msg_id": request_msg_id,
                "logs": recent
            }))

    async def send_initial_snapshot(self, websocket, user_id: str, role: str, discipline_id: str = None):
        projects = self.db.get_projects(include_hidden=False)
        disciplines = self.db.get_disciplines(include_hidden=False)

        # Filter tasks for Head based on discipline (A3 requirement) and assigned_head_id
        if role == ROLE_HEAD:
            if discipline_id:
                tasks = self.db.get_tasks(discipline_id=discipline_id, assigned_head_id=user_id, include_hidden=False)
            else:
                tasks = [] # Empty if Head has no discipline assigned
        else:
            tasks = self.db.get_tasks(include_hidden=False)

        pending_notifs = []
        if role == ROLE_HEAD:
            pending_notifs = self.db.get_priority_notifications(employee_id=user_id, status="PENDING")

        snapshot = {
            "type": "INITIAL_SNAPSHOT",
            "projects": projects,
            "disciplines": disciplines,
            "tasks": tasks,
            "pending_notifications": pending_notifs
        }
        await websocket.send(json.dumps(snapshot))

    async def handler(self, websocket):
        await self.register(websocket)
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.ConnectionClosedError:
            pass
        finally:
            await self.unregister(websocket)

    async def start(self):
        logger.info(f"Starting Central WebSocket Server on ws://{self.host}:{self.port} (LAN-only)")
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()
