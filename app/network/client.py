import asyncio
import json
import logging
from PySide6.QtCore import QObject, Signal
import websockets
from app.core.config import DEFAULT_WS_PORT

class NetworkClient(QObject):
    # PySide6 Signals for UI binding
    connection_status_changed = Signal(bool, str) # (is_connected, status_message)
    initial_snapshot_received = Signal(dict)
    priority_alert_received = Signal(dict)
    log_event_received = Signal(dict)
    notification_response_received = Signal(dict)
    global_refresh_received = Signal()

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

    async def start(self):
        self.running = True
        while self.running:
            try:
                self.connection_status_changed.emit(False, "Connecting to LAN Central Server...")
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
                self.connection_status_changed.emit(False, f"Disconnected / Reconnecting in 3s ({e})")
                await asyncio.sleep(3)

    async def _receive_loop(self, ws):
        async for message in ws:
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "INITIAL_SNAPSHOT":
                    self.initial_snapshot_received.emit(data)
                elif msg_type == "COO_PRIORITY_ALERT":
                    self.priority_alert_received.emit(data)
                elif msg_type == "NEW_LOG_EVENT":
                    self.log_event_received.emit(data)
                elif msg_type == "NOTIFICATION_RESPONSE_EVENT":
                    self.notification_response_received.emit(data)
                elif msg_type == "GLOBAL_DATA_REFRESH":
                    self.global_refresh_received.emit()

            except json.JSONDecodeError:
                pass

    async def _send_loop(self, ws):
        while self.is_connected:
            packet = await self._send_queue.get()
            try:
                await ws.send(json.dumps(packet))
            except Exception as e:
                logging.error(f"Error sending frame over WS: {e}")
                break
            finally:
                self._send_queue.task_done()

    def send_action(self, action: str, payload: dict):
        """Thread-safe queueing of action frames to send to server."""
        packet = {"action": action, "payload": payload}
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._send_queue.put(packet), loop)
        except Exception as e:
            logging.error(f"Failed to queue action packet: {e}")

    def stop(self):
        self.running = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())
