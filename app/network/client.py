import asyncio
import concurrent.futures
import json
import logging
import uuid
from PySide6.QtCore import QObject, Signal
import websockets
from app.core.config import DEFAULT_WS_PORT

logger = logging.getLogger(__name__)

class NetworkClient(QObject):
    # PySide6 Signals for UI binding
    connection_status_changed = Signal(bool, str) # (is_connected, status_message)
    initial_snapshot_received = Signal(dict)
    priority_alert_received = Signal(dict)
    log_event_received = Signal(dict)
    notification_response_received = Signal(dict)
    task_proposal_event = Signal(dict)
    task_date_change_event = Signal(dict)
    global_refresh_received = Signal()
    ack_received = Signal(dict)
    response_received = Signal(str, dict) # (response_type, full_packet)

    def __init__(self, user_id: str, role: str, server_ip: str = "127.0.0.1", port: int = DEFAULT_WS_PORT):
        super().__init__()
        self.user_id = user_id
        self.role = role
        self.server_ip = server_ip
        self.port = port
        self.ws_url = f"ws://{self.server_ip}:{self.port}"
        self.websocket = None
        self.is_connected = False
        self.running = False
        self._send_queue = asyncio.Queue()
        self._pending_futures = {} # msg_id -> asyncio.Future

    async def start(self):
        self.running = True
        while self.running:
            try:
                self.connection_status_changed.emit(False, f"Connecting to LAN Server ({self.server_ip})...")
                async with websockets.connect(self.ws_url, ping_interval=10, ping_timeout=5) as ws:
                    self.websocket = ws
                    self.is_connected = True
                    self.connection_status_changed.emit(True, "Connected to LAN Central Server")

                    # Identify to server
                    identify_pkt = {
                        "action": "IDENTIFY",
                        "payload": {"user_id": self.user_id, "role": self.role}
                    }
                    await ws.send(json.dumps(identify_pkt))

                    # Start send and receive tasks
                    consumer_task = asyncio.create_task(self._receive_loop(ws))
                    producer_task = asyncio.create_task(self._send_loop(ws))
                    
                    done, pending = await asyncio.wait(
                        [consumer_task, producer_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()

            except (websockets.ConnectionClosed, OSError, Exception) as e:
                self.is_connected = False
                self.websocket = None
                self.connection_status_changed.emit(False, f"Disconnected / Reconnecting ({e})")
                await asyncio.sleep(3)

    async def _receive_loop(self, ws):
        async for message in ws:
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                msg_id = data.get("msg_id")

                # Resolve any pending future
                if msg_id and msg_id in self._pending_futures:
                    fut = self._pending_futures.pop(msg_id)
                    if not fut.done():
                        fut.set_result(data)

                # Signal dispatches
                if msg_type == "INITIAL_SNAPSHOT":
                    self.initial_snapshot_received.emit(data)
                elif msg_type == "COO_PRIORITY_ALERT":
                    self.priority_alert_received.emit(data)
                elif msg_type == "NEW_LOG_EVENT":
                    self.log_event_received.emit(data)
                elif msg_type == "NOTIFICATION_RESPONSE_EVENT":
                    self.notification_response_received.emit(data)
                elif msg_type in ("NEW_TASK_PROPOSAL_EVENT", "TASK_PROPOSAL_DECIDED_EVENT"):
                    self.task_proposal_event.emit(data)
                elif msg_type == "TASK_DATE_CHANGE_EVENT":
                    self.task_date_change_event.emit(data)
                elif msg_type == "GLOBAL_DATA_REFRESH":
                    self.global_refresh_received.emit()
                elif msg_type == "ACK":
                    self.ack_received.emit(data)
                
                # Emit generic response for UI components waiting on data
                self.response_received.emit(msg_type, data)

            except json.JSONDecodeError:
                pass

    async def _send_loop(self, ws):
        while self.is_connected:
            packet = await self._send_queue.get()
            try:
                await ws.send(json.dumps(packet))
            except Exception as e:
                logger.error(f"Error sending frame over WS: {e}")
                break
            finally:
                self._send_queue.task_done()

    def send_action(self, action: str, payload: dict, msg_id: str = None) -> str:
        """Thread-safe queuing of action frames to send to server."""
        if not msg_id:
            msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        packet = {"action": action, "payload": payload, "msg_id": msg_id}
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._send_queue.put(packet), loop)
        except Exception as e:
            logger.error(f"Failed to queue action packet: {e}")
        return msg_id

    async def request_async(self, action: str, payload: dict, timeout: float = 5.0) -> dict:
        """Async request-response helper awaiting the server's reply."""
        msg_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_futures[msg_id] = fut
        await self._send_queue.put({"action": action, "payload": payload, "msg_id": msg_id})
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_futures.pop(msg_id, None)
            raise TimeoutError(f"Request '{action}' timed out after {timeout}s")

    def stop(self):
        self.running = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())

    @staticmethod
    async def authenticate_server(server_ip: str, port: int, user_id: str, password: str, timeout: float = 4.0) -> dict:
        """
        Standalone async login verification directly with the central server (B1).
        Used by LoginDialog before opening a workspace.
        """
        ws_url = f"ws://{server_ip}:{port}"
        async with websockets.connect(ws_url, open_timeout=timeout) as ws:
            msg_id = f"AUTH-{uuid.uuid4().hex[:8].upper()}"
            pkt = {
                "action": "LOGIN",
                "payload": {"user_id": user_id, "password": password},
                "msg_id": msg_id
            }
            await ws.send(json.dumps(pkt))
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            return data

    @staticmethod
    async def change_password_server(server_ip: str, port: int, user_id: str, new_password: str, old_password: str = None, force: bool = False, timeout: float = 4.0) -> dict:
        """Standalone async password change directly with the central server."""
        ws_url = f"ws://{server_ip}:{port}"
        async with websockets.connect(ws_url, open_timeout=timeout) as ws:
            msg_id = f"CHPASS-{uuid.uuid4().hex[:8].upper()}"
            pkt = {
                "action": "CHANGE_PASSWORD",
                "payload": {"user_id": user_id, "new_password": new_password, "old_password": old_password, "force": force},
                "msg_id": msg_id
            }
            await ws.send(json.dumps(pkt))
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            return data

    @staticmethod
    def sync_authenticate_server(server_ip: str, port: int, user_id: str, password: str, timeout: float = 4.0) -> dict:
        """
        Synchronously authenticate directly with the central server via worker thread (B1).
        Safe to call from within running event loops such as qasync.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                lambda: asyncio.run(
                    NetworkClient.authenticate_server(server_ip, port, user_id, password, timeout=timeout)
                )
            ).result()

    @staticmethod
    def sync_change_password_server(server_ip: str, port: int, user_id: str, new_password: str, old_password: str = None, force: bool = False, timeout: float = 4.0) -> dict:
        """
        Synchronously change password via worker thread.
        Safe to call from within running event loops such as qasync.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                lambda: asyncio.run(
                    NetworkClient.change_password_server(server_ip, port, user_id, new_password, old_password=old_password, force=force, timeout=timeout)
                )
            ).result()

