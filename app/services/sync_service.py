import json
import logging
from app.database.db_manager import ClientQueueDBManager
from app.network.client import NetworkClient

class SyncService:
    def __init__(self, network_client: NetworkClient):
        self.net_client = network_client
        self.queue_db = ClientQueueDBManager()
        # Connect to network status signal
        self.net_client.connection_status_changed.connect(self.on_connection_status_changed)

    def submit_progress_log(self, log_payload: dict) -> bool:
        """
        Submits progress log. Returns True if sent directly over LAN, 
        or False if queued locally (offline mode).
        """
        if self.net_client.is_connected:
            self.net_client.send_action("SUBMIT_LOG", log_payload)
            return True
        else:
            # Save to offline queue
            payload_str = json.dumps(log_payload)
            self.queue_db.add_to_queue("SUBMIT_LOG", payload_str)
            logging.info(f"Offline: Progress log queued locally for user {log_payload.get('employee_id')}")
            return False

    def respond_priority_notification(self, response_payload: dict) -> bool:
        """
        Responds to COO priority notification (ACCEPTED or DENIED).
        Returns True if sent directly, False if queued offline.
        """
        if self.net_client.is_connected:
            self.net_client.send_action("RESPOND_NOTIFICATION", response_payload)
            return True
        else:
            payload_str = json.dumps(response_payload)
            self.queue_db.add_to_queue("RESPOND_NOTIFICATION", payload_str)
            logging.info(f"Offline: Notification response queued locally")
            return False

    def get_pending_queue_count(self) -> int:
        return len(self.queue_db.get_all_queued())

    def on_connection_status_changed(self, is_connected: bool, status_msg: str):
        if is_connected:
            self.flush_offline_queue()

    def flush_offline_queue(self):
        queued_items = self.queue_db.get_all_queued()
        if not queued_items:
            return

        logging.info(f"Reconnected: Flushing {len(queued_items)} queued offline items to Central Server...")
        for item in queued_items:
            q_id = item["queue_id"]
            event_type = item["event_type"]
            try:
                payload = json.loads(item["payload_json"])
                self.net_client.send_action(event_type, payload)
                self.queue_db.delete_queued(q_id)
                logging.info(f"Successfully flushed queued item {q_id} ({event_type})")
            except Exception as e:
                logging.error(f"Error flushing queued item {q_id}: {e}")
