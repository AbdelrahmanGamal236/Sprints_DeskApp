import json
import logging
import uuid
from app.database.db_manager import ClientQueueDBManager
from app.network.client import NetworkClient

logger = logging.getLogger(__name__)

class SyncService:
    def __init__(self, network_client: NetworkClient):
        self.net_client = network_client
        self.queue_db = ClientQueueDBManager()
        # Connect to network signals
        self.net_client.connection_status_changed.connect(self.on_connection_status_changed)
        self.net_client.ack_received.connect(self.on_ack_received)

    def submit_progress_log(self, log_payload: dict) -> bool:
        """
        Submits progress log. Generates UUID before queuing (B4).
        Always persists to queue first, transmits if connected,
        and deletes only after ACK from Central Server.
        """
        if not log_payload.get("log_id"):
            log_payload["log_id"] = f"LOG-{uuid.uuid4().hex[:8].upper()}"

        payload_str = json.dumps(log_payload)
        self.queue_db.add_to_queue("SUBMIT_LOG", payload_str)

        if self.net_client.is_connected:
            self.net_client.send_action("SUBMIT_LOG", log_payload)
            return True
        else:
            logger.info(f"Offline: Progress log queued locally for user {log_payload.get('employee_id')}")
            return False

    def respond_priority_notification(self, response_payload: dict) -> bool:
        """Responds to COO priority alert; deletes only upon server ACK."""
        payload_str = json.dumps(response_payload)
        self.queue_db.add_to_queue("RESPOND_NOTIFICATION", payload_str)

        if self.net_client.is_connected:
            self.net_client.send_action("RESPOND_NOTIFICATION", response_payload)
            return True
        else:
            logger.info("Offline: Priority notification response queued locally")
            return False

    def propose_task(self, proposal_payload: dict) -> bool:
        """Queues task proposal; deletes upon ACK."""
        if not proposal_payload.get("proposal_id"):
            proposal_payload["proposal_id"] = f"PROP-{uuid.uuid4().hex[:8].upper()}"

        payload_str = json.dumps(proposal_payload)
        self.queue_db.add_to_queue("PROPOSE_TASK", payload_str)

        if self.net_client.is_connected:
            self.net_client.send_action("PROPOSE_TASK", proposal_payload)
            return True
        return False

    def request_date_change(self, request_payload: dict) -> bool:
        """Queues task date change request; deletes upon ACK."""
        if not request_payload.get("request_id"):
            request_payload["request_id"] = f"DCR-{uuid.uuid4().hex[:8].upper()}"

        payload_str = json.dumps(request_payload)
        self.queue_db.add_to_queue("REQUEST_TASK_DATE_CHANGE", payload_str)

        if self.net_client.is_connected:
            self.net_client.send_action("REQUEST_TASK_DATE_CHANGE", request_payload)
            return True
        return False

    def on_ack_received(self, ack_data: dict):
        """
        Reliable ACK Handler (B4):
        Server confirmed write. Delete matching item from client_queue.db.
        """
        action = ack_data.get("action")
        item_id = ack_data.get("id")
        status = ack_data.get("status")

        if status == "SUCCESS" and action and item_id:
            self.queue_db.delete_queued_by_payload_id(action, item_id)
            logger.info(f"Received ACK for {action} id={item_id}; purged from local queue.")

    def get_pending_queue_count(self) -> int:
        return len(self.queue_db.get_all_queued())

    def on_connection_status_changed(self, is_connected: bool, status_msg: str):
        if is_connected:
            self.flush_offline_queue()

    def flush_offline_queue(self):
        queued_items = self.queue_db.get_all_queued()
        if not queued_items:
            return

        logger.info(f"Reconnected: Flushing {len(queued_items)} queued offline items to Central Server...")
        for item in queued_items:
            event_type = item["event_type"]
            try:
                payload = json.loads(item["payload_json"])
                self.net_client.send_action(event_type, payload)
            except Exception as e:
                logger.error(f"Error flushing queued item {item['queue_id']}: {e}")
