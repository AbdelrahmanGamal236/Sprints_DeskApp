"""
End-to-end offline queue test with the real NetworkClient and SyncService:
server + two protocol clients, one of them behind a link that is cut and restored.
Verifies: no loss, no duplicates, permanent rejections are surfaced (not retried forever),
and real-time events reach the other client.
"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

from app.database.db_manager import ClientQueueDBManager
from app.network.client import NetworkClient, OfflineError, ServerError
from app.services.sync_service import SyncService
from tests.helpers import start_server, CuttableProxy, wait_until, PASSWORD


def make_log(task_id="T-URB", project_id="P1"):
    return {"project_id": project_id, "task_id": task_id, "start_date": "2026-10-02",
            "end_date": "2026-10-02", "progress_stage": "In Progress", "notes": "offline work"}


class TestOfflineQueueIntegration(unittest.TestCase):
    def test_disconnect_queue_reconnect_no_loss_no_duplicates(self):
        async def scenario():
            server = await start_server()
            proxy = await CuttableProxy(server.port).start()
            queue_path = Path(tempfile.mkdtemp()) / "client_queue.db"
            head = NetworkClient("127.0.0.1", proxy.port, ping_interval=1, ping_timeout=1)
            coo = NetworkClient("127.0.0.1", server.port)
            try:
                await head.login("h_urb", PASSWORD)
                await coo.login("coo1", PASSWORD)
                sync = SyncService(head, "h_urb", ClientQueueDBManager(queue_path))
                live_events = []
                coo.log_event_received.connect(lambda d: live_events.append(d["log"]["log_id"]))
                synced, failed = [], []
                sync.item_synced.connect(lambda a, i, r: synced.append(i))
                sync.item_failed.connect(lambda a, i, e: failed.append((i, e)))

                # Online submit works end to end
                first = sync.submit_progress_log(make_log())
                self.assertTrue(await wait_until(lambda: first in synced))

                # --- LAN outage ---
                proxy.cut()
                self.assertTrue(await wait_until(lambda: not head.is_connected, timeout=10))
                with self.assertRaises(OfflineError):
                    await head.request("GET_SNAPSHOT")

                offline_ids = [sync.submit_progress_log(make_log()) for _ in range(20)]
                prop_id = sync.propose_task({"project_id": "P1", "task_name": "Offline proposal",
                                             "planned_start_date": "2026-10-05", "planned_end_date": "2026-10-09"})
                dcr_id = sync.request_date_change({"task_id": "T-URB", "new_start_date": "2026-10-03",
                                                   "new_end_date": "2026-10-20", "reason": "Client delay"})
                bad_id = sync.submit_progress_log(make_log(task_id="T-STR"))  # other discipline -> permanent rejection
                self.assertEqual(sync.pending_count(), 23)

                # Same items "resent" by a second outbox (e.g. app restarted mid-flush) must not duplicate
                dup_queue = ClientQueueDBManager(Path(tempfile.mkdtemp()) / "dup.db")
                for it in ClientQueueDBManager(queue_path).get_items("h_urb", "PENDING")[:5]:
                    import json
                    dup_queue.enqueue("h_urb", it["event_type"], it["item_id"], json.loads(it["payload_json"]))

                # --- link restored ---
                proxy.restore()
                self.assertTrue(await wait_until(lambda: head.is_connected, timeout=20))
                self.assertTrue(await wait_until(lambda: sync.pending_count() == 0, timeout=20))

                dup_sync = SyncService(head, "h_urb", dup_queue)
                await dup_sync.flush_offline_queue()
                self.assertEqual(dup_sync.pending_count(), 0)

                logs = [l for l in server.db.get_progress_logs() if l["employee_id"] == "h_urb"]
                ids = [l["log_id"] for l in logs]
                self.assertEqual(len(ids), len(set(ids)), "duplicate log rows")
                self.assertEqual(set(ids), {first, *offline_ids})
                self.assertTrue(any(p["proposal_id"] == prop_id for p in server.db.get_task_proposals()))
                self.assertTrue(any(r["request_id"] == dcr_id for r in server.db.get_task_date_change_requests()))

                # Permanent rejection is surfaced and parked, not retried forever
                self.assertEqual(sync.failed_count(), 1)
                self.assertEqual([i for i, _ in failed], [bad_id])
                self.assertIn("Discipline mismatch", failed[0][1])
                await sync.flush_offline_queue()
                self.assertEqual(sync.failed_count(), 1)
                sync.discard_failed(sync.failed_items()[0]["queue_id"])
                self.assertEqual(sync.failed_count(), 0)

                # COO received every log in real time
                self.assertTrue(await wait_until(lambda: set(offline_ids) <= set(live_events), timeout=10))
            finally:
                await head.close()
                await coo.close()
                await proxy.stop()
                await server.stop()
        asyncio.run(scenario())

    def test_queue_is_per_user(self):
        async def scenario():
            server = await start_server()
            queue = ClientQueueDBManager(Path(tempfile.mkdtemp()) / "q.db")
            # Items left by another user on this PC must not be sent by the next user's session
            queue.enqueue("h_urb2", "SUBMIT_LOG", "LOG-OTHER", dict(make_log(), log_id="LOG-OTHER"))
            client = NetworkClient("127.0.0.1", server.port)
            try:
                await client.login("h_urb", PASSWORD)
                sync = SyncService(client, "h_urb", queue)
                await sync.flush_offline_queue()
                self.assertEqual(len(queue.get_items("h_urb2", "PENDING")), 1)
                self.assertFalse(any(l["log_id"] == "LOG-OTHER" for l in server.db.get_progress_logs()))
            finally:
                await client.close()
                await server.stop()
        asyncio.run(scenario())

    def test_client_request_errors(self):
        async def scenario():
            server = await start_server()
            client = NetworkClient("127.0.0.1", server.port)
            try:
                with self.assertRaises(ServerError):
                    await client.login("h_urb", "wrong")
                await client.login("h_urb", PASSWORD)
                with self.assertRaises(ServerError) as ctx:
                    await client.request("GET_ANALYTICS")
                self.assertEqual(ctx.exception.code, "FORBIDDEN")
            finally:
                await client.close()
                await server.stop()
            bad = NetworkClient("127.0.0.1", 1)
            with self.assertRaises(OfflineError):
                await bad.login("x", "y")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
