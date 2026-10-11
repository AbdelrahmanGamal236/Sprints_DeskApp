import asyncio
import base64
import json
import logging
import uuid

import websockets
from PySide6.QtCore import QObject, Signal

from app.core.config import DEFAULT_WS_PORT
from app.network import protocol as P

logger = logging.getLogger(__name__)


class ServerError(Exception):
    """The server processed the request and rejected it."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OfflineError(ConnectionError):
    """Not connected to the Central Server (or the connection dropped mid-request)."""


def deliver(callback, *args):
    """
    Run a UI callback from the event loop's ready queue instead of inside an asyncio task.
    Qt dialogs that call exec() spin a nested event loop; doing that inside a task would
    freeze every other task (network receive loop, offline sync) until the dialog closes.
    """
    if callback is None:
        return
    asyncio.get_event_loop().call_soon(callback, *args)


def run_async(coro, on_ok=None, on_err=None):
    """Schedule a coroutine from Qt code; on_ok(result) / on_err(exception) are delivered safely."""
    async def runner():
        try:
            result = await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if on_err is None:
                logger.error("Background request failed: %s", e)
            deliver(on_err, e)
        else:
            deliver(on_ok, result)
    return asyncio.ensure_future(runner())


class NetworkClient(QObject):
    """Persistent, authenticated WebSocket connection from a workstation to the Central Server."""
    connection_status_changed = Signal(bool, str)  # (is_connected, status_message)
    session_expired = Signal(str)                  # server no longer accepts our session; must log in again
    priority_alert_received = Signal(dict)
    log_event_received = Signal(dict)
    notification_response_received = Signal(dict)
    task_proposal_event = Signal(dict)
    task_date_change_event = Signal(dict)
    data_changed = Signal(list)                    # scopes that changed on the server (see server.notify_changed)

    def __init__(self, server_ip: str = "127.0.0.1", port: int = DEFAULT_WS_PORT,
                 ping_interval: float = 10, ping_timeout: float = 20):
        super().__init__()
        self.server_ip = server_ip
        self.port = port
        self.ws_url = f"ws://{self.server_ip}:{self.port}"
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.user: dict | None = None
        self.user_id: str | None = None
        self.role: str | None = None
        self.session_token: str | None = None
        self.policy: dict = {}
        self.websocket = None
        self.is_connected = False  # connected AND authenticated
        self.running = False
        self._pending: dict[str, asyncio.Future] = {}
        self._export_chunks: dict[str, list] = {}
        self._send_lock = asyncio.Lock()
        self._main_task = None

    # ------------------------------------------------------------------ signals
    def _emit(self, signal, *args):
        deliver(signal.emit, *args)

    # ------------------------------------------------------------------ connection
    async def _open(self):
        return await websockets.connect(self.ws_url, open_timeout=5, max_size=P.MAX_FRAME_BYTES,
                                        ping_interval=self.ping_interval, ping_timeout=self.ping_timeout)

    async def login(self, user_id: str, password: str) -> dict:
        """Connect, authenticate and start the background session loop. Returns the user dict."""
        try:
            ws = await self._open()
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
            raise OfflineError(f"Cannot reach Central Server at {self.server_ip}:{self.port}") from e
        recv_task = asyncio.ensure_future(self._receive_loop(ws))
        try:
            reply = await self._request_on(ws, "LOGIN", {"user_id": user_id, "password": password,
                                                          "protocol": P.PROTOCOL_VERSION}, timeout=15)
        except Exception:
            recv_task.cancel()
            await ws.close()
            raise
        self._set_user(reply["user"])
        self.session_token = reply["session_token"]
        self.policy = reply.get("policy") or {}
        self.running = True
        # Usable immediately, before the session loop task gets its first turn
        self.websocket = ws
        self.is_connected = True
        self._main_task = asyncio.ensure_future(self._session_loop(ws, recv_task))
        return self.user

    def _set_user(self, user: dict):
        self.user = user
        self.user_id = user["user_id"]
        self.role = user["role"]

    async def _session_loop(self, ws, recv_task):
        """Keeps the session alive: on disconnect, reconnects and resumes with the session token."""
        backoff = 1
        while self.running:
            if ws is None:
                self._emit(self.connection_status_changed, False, f"Connecting to Central Server ({self.server_ip})...")
                try:
                    ws = await self._open()
                except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
                    self._emit(self.connection_status_changed, False, f"Server unreachable, retrying ({type(e).__name__})")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 15)
                    continue
                recv_task = asyncio.ensure_future(self._receive_loop(ws))
                try:
                    reply = await self._request_on(ws, "RESUME", {"session_token": self.session_token,
                                                                   "protocol": P.PROTOCOL_VERSION}, timeout=15)
                    self._set_user(reply["user"])
                except ServerError as e:
                    recv_task.cancel()
                    await ws.close()
                    self.running = False
                    self._emit(self.session_expired, str(e))
                    break
                except Exception:
                    recv_task.cancel()
                    await ws.close()
                    ws = None
                    await asyncio.sleep(backoff)
                    continue

            backoff = 1
            self.websocket = ws
            self.is_connected = True
            self._emit(self.connection_status_changed, True, "Connected to Central Server")
            try:
                await recv_task
            except asyncio.CancelledError:
                if not self.running:
                    break
            except Exception:
                pass
            close_code = getattr(ws, "close_code", None)
            self.is_connected = False
            self.websocket = None
            self._fail_pending(OfflineError("Connection to Central Server lost."))
            ws = None
            if close_code == P.CLOSE_SESSION_REVOKED:
                self.running = False
                self._emit(self.session_expired, "Your session was ended by an administrator. Please log in again.")
                break
            if self.running:
                self._emit(self.connection_status_changed, False, "Disconnected - reconnecting...")
                await asyncio.sleep(1)
        self.is_connected = False

    def _fail_pending(self, exc: Exception):
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        self._export_chunks.clear()

    async def _receive_loop(self, ws):
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type", "")
                msg_id = data.get("msg_id")

                if msg_type == "EXPORT_EXCEL_CHUNK":
                    if msg_id in self._export_chunks:
                        self._export_chunks[msg_id].append(data)
                    continue

                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        fut.set_result(data)
                    continue

                self._dispatch_event(msg_type, data)
        except websockets.ConnectionClosed:
            pass

    def _dispatch_event(self, msg_type: str, data: dict):
        if msg_type == "COO_PRIORITY_ALERT":
            self._emit(self.priority_alert_received, data)
        elif msg_type == "NEW_LOG_EVENT":
            self._emit(self.log_event_received, data)
        elif msg_type == "NOTIFICATION_RESPONSE_EVENT":
            self._emit(self.notification_response_received, data)
        elif msg_type in ("NEW_TASK_PROPOSAL_EVENT", "TASK_PROPOSAL_DECIDED_EVENT"):
            self._emit(self.task_proposal_event, data)
        elif msg_type == "TASK_DATE_CHANGE_EVENT":
            self._emit(self.task_date_change_event, data)
        elif msg_type == "DATA_CHANGED":
            self._emit(self.data_changed, list(data.get("scopes") or []))

    # ------------------------------------------------------------------ requests
    async def _request_on(self, ws, action: str, payload: dict, timeout: float) -> dict:
        msg_id = f"REQ-{uuid.uuid4().hex}"
        fut = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        try:
            async with self._send_lock:
                await ws.send(json.dumps({"action": action, "payload": payload, "msg_id": msg_id}))
            reply = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"The Central Server did not answer '{action}' in time.")
        except websockets.ConnectionClosed as e:
            raise OfflineError("Connection to Central Server lost.") from e
        finally:
            self._pending.pop(msg_id, None)
        if not reply.get("ok", reply.get("success", False)):
            raise ServerError(reply.get("code", P.ERR_INTERNAL), reply.get("error") or "Request failed.")
        return reply

    async def request(self, action: str, payload: dict = None, timeout: float = 15.0) -> dict:
        """Send one request and await its reply. Raises OfflineError, TimeoutError or ServerError."""
        if not self.is_connected or self.websocket is None:
            raise OfflineError("Not connected to the Central Server. Check the network and try again.")
        return await self._request_on(self.websocket, action, payload or {}, timeout)

    def call(self, action: str, payload: dict = None, on_ok=None, on_err=None, timeout: float = 15.0):
        """Fire a request from Qt code; callbacks receive the reply dict or the exception."""
        return run_async(self.request(action, payload, timeout), on_ok, on_err)

    async def export_excel(self, filters: dict, timeout: float = 600.0) -> tuple[bytes, str]:
        """Request a server-side Excel export and reassemble the chunked workbook."""
        if not self.is_connected or self.websocket is None:
            raise OfflineError("Not connected to the Central Server.")
        msg_id = f"EXP-{uuid.uuid4().hex}"
        fut = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        self._export_chunks[msg_id] = []
        try:
            async with self._send_lock:
                await self.websocket.send(json.dumps({"action": "EXPORT_EXCEL_REQUEST", "payload": filters, "msg_id": msg_id}))
            reply = await asyncio.wait_for(fut, timeout=timeout)
            chunks = self._export_chunks.get(msg_id, [])
        except asyncio.TimeoutError:
            raise TimeoutError("The export took too long. Try narrower filters.")
        finally:
            self._pending.pop(msg_id, None)
            self._export_chunks.pop(msg_id, None)
        if not reply.get("ok"):
            raise ServerError(reply.get("code", P.ERR_INTERNAL), reply.get("error") or "Export failed.")
        chunks.sort(key=lambda c: c["index"])
        if len(chunks) != reply.get("total_chunks"):
            raise ServerError(P.ERR_INTERNAL, "Export was incomplete. Please try again.")
        data = b"".join(base64.b64decode(c["data_b64"]) for c in chunks)
        return data, reply.get("filename") or "Progress_Logs.xlsx"

    async def change_password(self, new_password: str, old_password: str = None) -> dict:
        reply = await self.request("CHANGE_PASSWORD", {"new_password": new_password, "old_password": old_password})
        self._set_user(reply["user"])
        return self.user

    # ------------------------------------------------------------------ shutdown
    async def logout(self):
        if self.is_connected:
            try:
                await self.request("LOGOUT", {}, timeout=3)
            except Exception:
                pass
        await self.close()

    async def close(self):
        self.running = False
        ws = self.websocket
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if self._main_task is not None:
            self._main_task.cancel()
            try:
                await self._main_task
            except (asyncio.CancelledError, Exception):
                pass
        self.is_connected = False
