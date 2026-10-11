import asyncio
import json
import logging
import uuid

from PySide6.QtCore import QObject, Signal

from app.database.db_manager import ClientQueueDBManager
from app.network import protocol as P
from app.network.client import NetworkClient, ServerError, OfflineError, deliver

logger = logging.getLogger(__name__)

# Head actions that go through the persistent outbox, and the payload field holding their unique ID.
QUEUED_ACTIONS = {
    "SUBMIT_LOG": ("log_id", "LOG"),
    "PROPOSE_TASK": ("proposal_id", "PROP"),
    "REQUEST_TASK_DATE_CHANGE": ("request_id", "DCR"),
    "RESPOND_NOTIFICATION": ("notification_id", None),  # ID comes from the server-issued alert
}

RETRY_INTERVAL_SECONDS = 30


class SyncService(QObject):
    """
    Reliable outbox for a logged-in Head:
    every item is written to client_queue.db first, sent when connected, and deleted only after the
    Central Server confirms it. Items the server permanently rejects are kept as FAILED and shown to
    the user (retry or discard). Transient failures stay PENDING and are retried automatically.
    """
    item_synced = Signal(str, str, dict)  # (action, item_id, server reply)
    item_failed = Signal(str, str, str)   # (action, item_id, error message)
    queue_changed = Signal(int, int)      # (pending_count, failed_count)

    def __init__(self, network_client: NetworkClient, user_id: str, queue_db: ClientQueueDBManager = None):
        super().__init__()
        self.net_client = network_client
        self.user_id = user_id
        self.queue_db = queue_db or ClientQueueDBManager()
        self._flush_lock = asyncio.Lock()
        self._retry_task = None
        self.net_client.connection_status_changed.connect(self.on_connection_status_changed)

    # ------------------------------------------------------------------ public API
    @staticmethod
    def new_id(action: str) -> str:
        prefix = QUEUED_ACTIONS[action][1] or "ID"
        return f"{prefix}-{uuid.uuid4().hex.upper()}"

    def submit(self, action: str, payload: dict) -> str:
        """Persist the item, then try to send it. Returns the item's unique ID."""
        id_field, _ = QUEUED_ACTIONS[action]
        if not payload.get(id_field):
            payload[id_field] = self.new_id(action)
        item_id = payload[id_field]
        self.queue_db.enqueue(self.user_id, action, item_id, payload)
        self._notify_counts()
        self.schedule_flush()
        return item_id

    # Convenience wrappers used by the Head workspace
    def submit_progress_log(self, payload: dict) -> str:
        return self.submit("SUBMIT_LOG", payload)

    def propose_task(self, payload: dict) -> str:
        return self.submit("PROPOSE_TASK", payload)

    def request_date_change(self, payload: dict) -> str:
        return self.submit("REQUEST_TASK_DATE_CHANGE", payload)

    def respond_priority_notification(self, payload: dict) -> str:
        return self.submit("RESPOND_NOTIFICATION", payload)

    def pending_count(self) -> int:
        return self.queue_db.count(self.user_id, "PENDING")

    def failed_count(self) -> int:
        return self.queue_db.count(self.user_id, "FAILED")

    def get_pending_queue_count(self) -> int:
        return self.pending_count()

    def failed_items(self) -> list[dict]:
        items = self.queue_db.get_items(self.user_id, "FAILED")
        for it in items:
            it["payload"] = json.loads(it["payload_json"])
        return items

    def retry_failed(self, queue_id: int):
        self.queue_db.retry_item(queue_id)
        self._notify_counts()
        self.schedule_flush()

    def discard_failed(self, queue_id: int):
        self.queue_db.delete_item(queue_id)
        self._notify_counts()

    # ------------------------------------------------------------------ sending
    def on_connection_status_changed(self, is_connected: bool, status_msg: str):
        if is_connected:
            self.schedule_flush()
            if self._retry_task is None or self._retry_task.done():
                self._retry_task = asyncio.ensure_future(self._periodic_retry())

    def schedule_flush(self):
        if self.net_client.is_connected:
            asyncio.ensure_future(self.flush_offline_queue())

    async def _periodic_retry(self):
        while self.net_client.running:
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)
            if self.net_client.is_connected and self.pending_count():
                await self.flush_offline_queue()

    async def flush_offline_queue(self):
        """Send PENDING items in order. Stops at the first transient failure to preserve ordering."""
        if self._flush_lock.locked():
            return
        async with self._flush_lock:
            for item in self.queue_db.get_items(self.user_id, "PENDING"):
                if not self.net_client.is_connected:
                    break
                action = item["event_type"]
                payload = json.loads(item["payload_json"])
                self.queue_db.mark_attempt(item["queue_id"])
                try:
                    reply = await self.net_client.request(action, payload, timeout=20)
                except ServerError as e:
                    if e.code in P.PERMANENT_ERROR_CODES:
                        logger.warning("Server rejected queued %s %s: %s", action, item["item_id"], e)
                        self.queue_db.mark_failed(item["queue_id"], str(e))
                        self._notify_counts()
                        deliver_signal(self.item_failed, action, item["item_id"], str(e))
                        continue
                    logger.info("Queued %s %s will be retried: %s", action, item["item_id"], e)
                    break
                except (OfflineError, TimeoutError, ConnectionError) as e:
                    logger.info("Sync paused: %s", e)
                    break
                self.queue_db.delete_item(item["queue_id"])
                self._notify_counts()
                deliver_signal(self.item_synced, action, item["item_id"], reply)

    def _notify_counts(self):
        deliver_signal(self.queue_changed, self.pending_count(), self.failed_count())

    def stop(self):
        if self._retry_task is not None:
            self._retry_task.cancel()



def deliver_signal(signal, *args):
    deliver(signal.emit, *args)
