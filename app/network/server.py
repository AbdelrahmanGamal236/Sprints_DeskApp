import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime
import websockets
from app.core.config import DEFAULT_WS_PORT, DEFAULT_HOST
from app.database.db_manager import DBManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class CentralWebSocketServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_WS_PORT):
        self.host = host
        self.port = port
        self.db = DBManager()
        # Active connections: websocket -> {"user_id": str, "role": str}
        self.clients = {}

    async def register(self, websocket):
        self.clients[websocket] = {"user_id": None, "role": None}
        logging.info(f"New client connected from {websocket.remote_address}")

    async def unregister(self, websocket):
        if websocket in self.clients:
            user_id = self.clients[websocket].get("user_id")
            logging.info(f"Client disconnected: {user_id} ({websocket.remote_address})")
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
                    logging.error(f"Error broadcasting to {info.get('user_id')}: {e}")

    async def send_to_user(self, user_id: str, message_dict: dict):
        payload = json.dumps(message_dict)
        sent = False
        for ws, info in list(self.clients.items()):
            if info.get("user_id") == user_id:
                try:
                    await ws.send(payload)
                    sent = True
                except Exception as e:
                    logging.error(f"Error sending message to {user_id}: {e}")
        return sent

    async def handle_message(self, websocket, raw_message: str):
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logging.error("Failed to parse JSON packet")
            return

        action = data.get("action")
        payload = data.get("payload", {})
        logging.info(f"Received action '{action}' with payload {payload}")

        if action == "IDENTIFY":
            user_id = payload.get("user_id")
            role = payload.get("role")
            self.clients[websocket]["user_id"] = user_id
            self.clients[websocket]["role"] = role
            logging.info(f"Client identified as user_id='{user_id}', role='{role}'")
            
            # Send initial state snapshot
            await self.send_initial_snapshot(websocket, user_id, role)

        elif action == "SUBMIT_LOG":
            log_id = payload.get("log_id") or f"LOG-{uuid.uuid4().hex[:8].upper()}"
            employee_id = payload.get("employee_id")
            project_id = payload.get("project_id")
            task_id = payload.get("task_id")
            start_date = payload.get("start_date")
            end_date = payload.get("end_date")
            progress_percentage = int(payload.get("progress_percentage", 0))
            progress_stage = payload.get("progress_stage", "")
            entry_type = payload.get("entry_type", "NEW")
            revision_number = int(payload.get("revision_number", 0))
            notes = payload.get("notes", "")

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO progress_logs 
                (log_id, employee_id, project_id, task_id, start_date, end_date, progress_percentage, progress_stage, entry_type, revision_number, notes, submitted_at, sync_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'SYNCED')
                """, (log_id, employee_id, project_id, task_id, start_date, end_date, progress_percentage, progress_stage, entry_type, revision_number, notes))
                conn.commit()

            # Confirm submission back to sender
            await websocket.send(json.dumps({
                "type": "SUBMIT_CONFIRMATION",
                "status": "SUCCESS",
                "log_id": log_id
            }))

            # Broadcast new log event to all connected COOs, Admins, Super Admins
            await self.broadcast({
                "type": "NEW_LOG_EVENT",
                "log": {
                    "log_id": log_id,
                    "employee_id": employee_id,
                    "project_id": project_id,
                    "task_id": task_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "progress_percentage": progress_percentage,
                    "progress_stage": progress_stage,
                    "entry_type": entry_type,
                    "revision_number": revision_number,
                    "notes": notes,
                    "submitted_at": datetime.now().isoformat()
                }
            }, target_roles=["COO", "ADMIN", "SUPER_ADMIN"])

        elif action == "COO_NOTIFY":
            coo_id = payload.get("coo_id")
            target_employee_id = payload.get("target_employee_id")
            message = payload.get("message")
            notification_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO priority_notifications (notification_id, coo_id, target_employee_id, message, status)
                VALUES (?, ?, ?, ?, 'PENDING')
                """, (notification_id, coo_id, target_employee_id, message))
                conn.commit()

            # Send priority alert to target employee if online
            alert_packet = {
                "type": "COO_PRIORITY_ALERT",
                "notification_id": notification_id,
                "coo_id": coo_id,
                "message": message,
                "created_at": datetime.now().isoformat()
            }
            delivered = await self.send_to_user(target_employee_id, alert_packet)

            # Confirm to COO
            await websocket.send(json.dumps({
                "type": "NOTIFY_DISPATCH_CONFIRMATION",
                "notification_id": notification_id,
                "target_employee_id": target_employee_id,
                "delivered": delivered
            }))

        elif action == "RESPOND_NOTIFICATION":
            notification_id = payload.get("notification_id")
            employee_id = payload.get("employee_id")
            response_status = payload.get("response_status") # ACCEPTED or DENIED
            responded_at = datetime.now().isoformat()

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                UPDATE priority_notifications 
                SET status = ?, responded_at = CURRENT_TIMESTAMP
                WHERE notification_id = ?
                """, (response_status, notification_id))
                conn.commit()

            # Notify COOs in real-time
            await self.broadcast({
                "type": "NOTIFICATION_RESPONSE_EVENT",
                "notification_id": notification_id,
                "target_employee_id": employee_id,
                "status": response_status,
                "responded_at": responded_at
            }, target_roles=["COO", "SUPER_ADMIN"])

        elif action == "DATA_UPDATE_EVENT":
            # Broadcast state changes (new project, hidden project, password reset, etc.)
            await self.broadcast({
                "type": "GLOBAL_DATA_REFRESH",
                "reason": payload.get("reason", "DATA_UPDATED")
            })

    async def send_initial_snapshot(self, websocket, user_id: str, role: str):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch active projects
            cursor.execute("SELECT * FROM projects WHERE is_hidden = 0")
            projects = [dict(row) for row in cursor.fetchall()]

            # Fetch active tasks
            cursor.execute("SELECT * FROM tasks WHERE is_hidden = 0")
            tasks = [dict(row) for row in cursor.fetchall()]

            # Fetch pending priority notifications for this employee if HEAD
            pending_notifs = []
            if role == "HEAD":
                cursor.execute("""
                SELECT * FROM priority_notifications 
                WHERE target_employee_id = ? AND status = 'PENDING'
                """, (user_id,))
                pending_notifs = [dict(row) for row in cursor.fetchall()]

            snapshot = {
                "type": "INITIAL_SNAPSHOT",
                "projects": projects,
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
        logging.info(f"Starting Central WebSocket Server on ws://{self.host}:{self.port} (LAN-only)")
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()  # Run forever
