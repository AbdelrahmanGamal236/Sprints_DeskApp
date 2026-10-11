import unittest
import os
import tempfile
import json
from pathlib import Path
from openpyxl import load_workbook
import io

from app.core.auth import hash_password, verify_password
from app.core.config import ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN, DEFAULT_DISCIPLINES
from app.database.db_manager import DBManager, ClientQueueDBManager
from app.services.excel_service import ExcelExportService

class TestDeskAppSystem(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_central.db"
        self.queue_db_path = Path(self.temp_dir.name) / "test_queue.db"
        
        self.db = DBManager(central_db_path=self.db_path, standalone=True)
        self.queue_db = ClientQueueDBManager(queue_db_path=self.queue_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_discipline_seeding(self):
        """Discipline seeding: idempotent, correct display order, all default items exist."""
        disciplines = self.db.get_disciplines()
        disc_ids = [d["discipline_id"] for d in disciplines]
        for expected_id, expected_name in DEFAULT_DISCIPLINES:
            self.assertIn(expected_id, disc_ids)

        # Idempotence test
        self.db.seed_disciplines()
        disciplines_after = self.db.get_disciplines()
        self.assertEqual(len(disciplines), len(disciplines_after))

    def test_multiple_heads_per_discipline(self):
        """A discipline can have more than one Head (A3)."""
        h1 = self.db.create_user(ROLE_SUPER_ADMIN, "bim_head_1", "Khalid Elsheikh", ROLE_HEAD, "BIM")
        h2 = self.db.create_user(ROLE_SUPER_ADMIN, "bim_head_2", "Fawzy Refaat", ROLE_HEAD, "BIM")

        self.assertEqual(h1["discipline_id"], "BIM")
        self.assertEqual(h2["discipline_id"], "BIM")

        bim_heads = self.db.get_users(role=ROLE_HEAD, discipline_id="BIM")
        u_ids = [u["user_id"] for u in bim_heads]
        self.assertIn("bim_head_1", u_ids)
        self.assertIn("bim_head_2", u_ids)

    def test_seed_heads_json_handling(self):
        """seed_heads.json handling: placeholder skip, duplicate skip, no overwrite (A3.1)."""
        json_file = Path(self.temp_dir.name) / "test_seed_heads.json"
        seed_data = [
            {"user_id": "<FINGERPRINT_ID>", "full_name": "Placeholder Guy", "discipline_id": "URB"},
            {"user_id": "", "full_name": "Empty Guy", "discipline_id": "STR"},
            {"user_id": "valid_head_1", "full_name": "Valid Head One", "discipline_id": "ARC"},
            {"user_id": "valid_head_1", "full_name": "Duplicate Head", "discipline_id": "ARC"},
            {"user_id": "valid_head_2", "full_name": "Valid Head Two", "discipline_id": "ELE"}
        ]
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(seed_data, f)

        self.db.seed_heads_from_file(json_file)

        # Placeholders and empty IDs should not be in DB
        self.assertIsNone(self.db.get_user("<FINGERPRINT_ID>"))
        self.assertIsNone(self.db.get_user(""))

        # Valid ones should exist
        u1 = self.db.get_user("valid_head_1")
        self.assertIsNotNone(u1)
        self.assertEqual(u1["full_name"], "Valid Head One")
        self.assertEqual(u1["discipline_id"], "ARC")

        # Duplicate should not have overwritten u1
        self.assertNotEqual(u1["full_name"], "Duplicate Head")

        # Re-seeding should never overwrite existing user
        seed_data_overwrite = [
            {"user_id": "valid_head_1", "full_name": "Overwritten Name", "discipline_id": "INT"}
        ]
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(seed_data_overwrite, f)
        self.db.seed_heads_from_file(json_file)

        u1_after = self.db.get_user("valid_head_1")
        self.assertEqual(u1_after["full_name"], "Valid Head One")
        self.assertEqual(u1_after["discipline_id"], "ARC")

    def test_discipline_filtering_server_side(self):
        """Server-side discipline filtering for Head vs Admin/COO (A1, A3)."""
        # Create tasks in different disciplines
        self.db.add_task("PRJ-01", "TSK-ARC-01", "Floor Plan Design", "ARC", "2026-10-01", "2026-10-10")
        self.db.add_task("PRJ-01", "TSK-ELE-01", "Wiring Layout", "ELE", "2026-10-01", "2026-10-10")

        # Head belonging to ARC
        arc_tasks = self.db.get_tasks(project_id="PRJ-01", discipline_id="ARC")
        self.assertTrue(all(t["discipline_id"] == "ARC" for t in arc_tasks))
        t_ids = [t["task_id"] for t in arc_tasks]
        self.assertIn("TSK-ARC-01", t_ids)
        self.assertNotIn("TSK-ELE-01", t_ids)

        # Admin query (no discipline filter) gets all
        all_tasks = self.db.get_tasks(project_id="PRJ-01")
        all_t_ids = [t["task_id"] for t in all_tasks]
        self.assertIn("TSK-ARC-01", all_t_ids)
        self.assertIn("TSK-ELE-01", all_t_ids)

    def test_date_change_request_approve_reject(self):
        """Per-task planned dates with change request approval/rejection flow (A2)."""
        self.db.add_task("PRJ-01", "TSK-DCR", "Substation Wiring", "ELE", "2026-10-01", "2026-10-15")

        # Head requests date change
        req = self.db.create_task_date_change_request(
            task_id="TSK-DCR",
            requested_by_id="1001",
            new_start_date="2026-10-05",
            new_end_date="2026-10-25",
            reason="Cable shipment delayed by supplier."
        )
        self.assertEqual(req["status"], "PENDING")
        self.assertEqual(req["new_start_date"], "2026-10-05")
        self.assertEqual(req["new_end_date"], "2026-10-25")

        # Admin approves
        appr = self.db.approve_task_date_change_request(req["request_id"], "admin")
        self.assertEqual(appr["status"], "APPROVED")

        # Verify task planned dates were updated in tasks table
        task_after = self.db.get_tasks(project_id="PRJ-01", discipline_id="ELE")[0]
        self.assertEqual(task_after["planned_start_date"], "2026-10-05")
        self.assertEqual(task_after["planned_end_date"], "2026-10-25")

        # Test Rejection flow
        req2 = self.db.create_task_date_change_request(
            task_id="TSK-DCR",
            requested_by_id="1001",
            new_start_date="2026-11-01",
            new_end_date="2026-11-30",
            reason="Requesting another month."
        )
        rej = self.db.reject_task_date_change_request(req2["request_id"], "admin", "Deadline cannot slip past October.")
        self.assertEqual(rej["status"], "REJECTED")
        self.assertEqual(rej["rejection_reason"], "Deadline cannot slip past October.")

        # Dates should remain unchanged
        task_still = self.db.get_tasks(project_id="PRJ-01", discipline_id="ELE")[0]
        self.assertEqual(task_still["planned_start_date"], "2026-10-05")
        self.assertEqual(task_still["planned_end_date"], "2026-10-25")

    def test_head_discipline_enforcement_on_submit_log(self):
        """Server rejects SUBMIT_LOG for a task outside the Head's discipline (A3)."""
        # Create head in STR
        self.db.create_user(ROLE_SUPER_ADMIN, "head_str", "Structural Head", ROLE_HEAD, "STR")
        # Create head with no discipline
        with self.db.get_connection() as conn:
            pwd_hash, pwd_salt = hash_password("head_nodisc")
            conn.execute("INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                         ("head_nodisc", "No Disc Head", pwd_hash, pwd_salt, ROLE_HEAD, 0))
            conn.commit()

        self.db.add_task("PRJ-01", "TSK-MEC", "HVAC Ducting", "MEC", "2026-10-01", "2026-10-10")
        self.db.add_task("PRJ-01", "TSK-STR", "Foundation Column", "STR", "2026-10-01", "2026-10-10")

        # STR head logging against MEC task -> must raise PermissionError
        with self.assertRaises(PermissionError):
            self.db.submit_progress_log({
                "employee_id": "head_str",
                "project_id": "PRJ-01",
                "task_id": "TSK-MEC",
                "start_date": "2026-10-02",
                "progress_stage": "In Progress", "end_date": "2026-10-02"
            })

        # Head with no discipline -> must raise PermissionError
        with self.assertRaises(PermissionError):
            self.db.submit_progress_log({
                "employee_id": "head_nodisc",
                "project_id": "PRJ-01",
                "task_id": "TSK-STR",
                "start_date": "2026-10-02",
                "progress_stage": "In Progress", "end_date": "2026-10-02"
            })

        # STR head logging against STR task -> succeeds
        log = self.db.submit_progress_log({
            "employee_id": "head_str",
            "project_id": "PRJ-01",
            "task_id": "TSK-STR",
            "start_date": "2026-10-02",
            "progress_stage": "In Progress", "end_date": "2026-10-02",
            "assigned_to": "Worker John"
        })
        self.assertEqual(log["discipline_id"], "STR")
        self.assertEqual(log["assigned_to"], "Worker John")

    def test_excel_export_with_discipline_filters_and_sheets(self):
        """Excel export with discipline categorization and multi-sheet structure (A4)."""
        self.db.create_user(ROLE_SUPER_ADMIN, "head_urb", "Urban Head", ROLE_HEAD, "URB")
        self.db.create_user(ROLE_SUPER_ADMIN, "head_bim", "BIM Head", ROLE_HEAD, "BIM")
        self.db.add_task("PRJ-01", "TSK-URB", "City Master Plan", "URB", "2026-10-01", "2026-10-10")
        self.db.add_task("PRJ-01", "TSK-BIM", "Revit Coordination", "BIM", "2026-10-01", "2026-10-10")

        self.db.submit_progress_log({
            "employee_id": "head_urb", "project_id": "PRJ-01", "task_id": "TSK-URB",
            "start_date": "2026-10-01", "progress_stage": "In Progress", "end_date": "2026-10-01", "assigned_to": "Planner Ali"
        })
        self.db.submit_progress_log({
            "employee_id": "head_bim", "project_id": "PRJ-01", "task_id": "TSK-BIM",
            "start_date": "2026-10-01", "progress_stage": "In Progress", "end_date": "2026-10-01", "assigned_to": "Modeller Sam"
        })

        excel_service = ExcelExportService(self.db)
        out_bytes = excel_service.export_logs_to_excel(discipline_id=None)

        wb = load_workbook(io.BytesIO(out_bytes))
        sheet_names = wb.sheetnames
        self.assertIn("All Logs", sheet_names)
        self.assertIn("Urban", sheet_names)
        self.assertIn("BIM", sheet_names)

        # Check headers of All Logs
        ws_all = wb["All Logs"]
        headers = [cell.value for cell in ws_all[1]]
        self.assertIn("Head Discipline", headers)
        self.assertIn("Discipline", headers)
        self.assertIn("Assigned To", headers)

    def test_assigned_to_persistence(self):
        """Assigned To field persistence on progress_logs (A5)."""
        self.db.create_user(ROLE_SUPER_ADMIN, "h_qc", "QC Head", ROLE_HEAD, "QC")
        self.db.add_task("PRJ-01", "TSK-QC", "Quality Audit", "QC", "2026-10-01", "2026-10-05")

        log = self.db.submit_progress_log({
            "log_id": "LOG-ASSIGN-01",
            "employee_id": "h_qc",
            "project_id": "PRJ-01",
            "task_id": "TSK-QC",
            "start_date": "2026-10-02",
            "progress_stage": "In Progress", "end_date": "2026-10-02",
            "assigned_to": "Eng. Tarek"
        })
        self.assertEqual(log["assigned_to"], "Eng. Tarek")

        # Query from DB
        logs = self.db.get_progress_logs(project_id="PRJ-01")
        logged_assign = next(l["assigned_to"] for l in logs if l["log_id"] == "LOG-ASSIGN-01")
        self.assertEqual(logged_assign, "Eng. Tarek")

    def test_server_side_login(self):
        """Server-side login verification and password changes (B1)."""
        u = self.db.get_user("admin")
        self.assertTrue(verify_password("admin", u["password_hash"], u["password_salt"]))
        self.assertFalse(verify_password("wrong", u["password_hash"], u["password_salt"]))

        # Password change
        self.db.change_password("admin", "new_admin_pass", old_password="admin")
        u_after = self.db.get_user("admin")
        self.assertTrue(verify_password("new_admin_pass", u_after["password_hash"], u_after["password_salt"]))
        self.assertEqual(u_after["must_change_password"], 0)

    def test_ack_based_queue_with_duplicate_resend(self):
        """Reliable offline queue with ACK deletion and duplicate resilience (B4)."""
        payload = {
            "log_id": "LOG-UUID-UNIQUE-1",
            "employee_id": "1001",
            "project_id": "PRJ-01",
            "task_id": "TSK-02",
            "start_date": "2026-10-01",
            "progress_stage": "In Progress", "end_date": "2026-10-01"
        }
        # Client enqueues before sending
        self.queue_db.add_to_queue("SUBMIT_LOG", json.dumps(payload))
        self.assertEqual(len(self.queue_db.get_all_queued()), 1)

        # Server writes
        self.db.submit_progress_log(payload)
        # Server writes duplicate resend -> idempotent, no error or extra record
        self.db.submit_progress_log(payload)

        # Verify only 1 record exists in DB
        logs = [l for l in self.db.get_progress_logs() if l["log_id"] == "LOG-UUID-UNIQUE-1"]
        self.assertEqual(len(logs), 1)

        # Client receives ACK and deletes from queue
        self.queue_db.delete_queued_by_payload_id("SUBMIT_LOG", "LOG-UUID-UNIQUE-1")
        self.assertEqual(len(self.queue_db.get_all_queued()), 0)

    def test_role_permissions_enforced(self):
        """Admin can only create/manage HEAD accounts. Super Admin can manage all (B5)."""
        # Admin trying to create another ADMIN -> must raise PermissionError
        with self.assertRaises(PermissionError):
            self.db.create_user(ROLE_ADMIN, "admin_new", "Admin Two", ROLE_ADMIN)

        # Admin trying to create COO -> must raise PermissionError
        with self.assertRaises(PermissionError):
            self.db.create_user(ROLE_ADMIN, "coo_new", "COO Two", ROLE_COO)

        # Admin creating HEAD -> succeeds
        head = self.db.create_user(ROLE_ADMIN, "head_permitted", "Allowed Head", ROLE_HEAD, "URB")
        self.assertEqual(head["role"], ROLE_HEAD)

        # Super Admin creating ADMIN -> succeeds
        adm = self.db.create_user(ROLE_SUPER_ADMIN, "super_created_adm", "Created Admin", ROLE_ADMIN)
        self.assertEqual(adm["role"], ROLE_ADMIN)

    def test_database_backup(self):
        """Automatic daily SQLite database backup API (B6)."""
        backup_path = self.db.backup_database()
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))

    def test_task_assigned_to_head_and_autoid(self):
        """Verify Admin task creation with assigned_head_id, auto-ID generation, and Head visibility filtering."""
        self.db.create_user(ROLE_SUPER_ADMIN, "5026", "Abdallah Behiry", ROLE_HEAD, "MEC")
        # 1. Test auto-generation when task_id starts with MSG-
        t1 = self.db.add_task(
            project_id="PRJ-01",
            name="HVAC Zone 1 Ducting",
            discipline_id="MEC",
            planned_start_date="2026-10-01",
            planned_end_date="2026-10-10",
            assigned_head_id="5026"  # Abdallah Behiry
        )
        self.assertTrue(t1["task_id"].startswith("TSK-"))
        self.assertEqual(t1["assigned_head_id"], "5026")

        # 2. Test get_tasks filtering by assigned_head_id
        tasks_for_5026 = self.db.get_tasks(project_id="PRJ-01", discipline_id="MEC", assigned_head_id="5026")
        self.assertTrue(any(t["task_id"] == t1["task_id"] for t in tasks_for_5026))

        # Another head in same or other discipline should NOT see specifically assigned task
        tasks_for_other = self.db.get_tasks(project_id="PRJ-01", discipline_id="MEC", assigned_head_id="9999")
        self.assertFalse(any(t["task_id"] == t1["task_id"] for t in tasks_for_other))

        # 3. Test update_task
        upd = self.db.update_task(t1["task_id"], name="HVAC Zone 1 Ducting (Updated)", assigned_head_id=None)
        self.assertEqual(upd["name"], "HVAC Zone 1 Ducting (Updated)")
        self.assertIsNone(upd["assigned_head_id"])

        # Now that assigned_head_id is None, it is visible to any head in MEC
        tasks_now = self.db.get_tasks(project_id="PRJ-01", discipline_id="MEC", assigned_head_id="9999")
        self.assertTrue(any(t["task_id"] == t1["task_id"] for t in tasks_now))

    def test_project_timeline_data_structure(self):
        """Verify get_project_timeline_data returns progressive timeline metrics and task details."""
        self.db.add_task("PRJ-01", "TSK-TL-01", "Timeline Arch Task", "ARC", "2026-10-01", "2026-10-15")
        tl_data = self.db.get_project_timeline_data("PRJ-01")
        self.assertIn("project_id", tl_data)
        self.assertIn("tasks", tl_data)
        self.assertIn("overall_progress_percentage", tl_data)
        self.assertTrue(any(t["task_id"] == "TSK-TL-01" for t in tl_data["tasks"]))

if __name__ == "__main__":
    unittest.main()


class TestDataIsolation(unittest.TestCase):
    def test_tests_never_use_real_data_dir(self):
        """conftest.py redirects DATA_DIR away from the repo's data/ folder."""
        from app.core import config
        repo_data = (Path(__file__).resolve().parent.parent / "data").resolve()
        self.assertNotEqual(config.DATA_DIR.resolve(), repo_data)
        self.assertNotEqual(config.BACKUPS_DIR.resolve().parent, repo_data)


class TestBootstrapAndPasswords(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "prod.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fresh_production_db_has_no_default_accounts(self):
        db = DBManager(central_db_path=self.db_path)
        users = {u["user_id"]: u for u in db.get_users()}
        self.assertNotIn("admin", users)
        self.assertNotIn("coo", users)
        self.assertIn("superadmin", users)
        self.assertEqual(users["superadmin"]["must_change_password"], 1)
        (uid, pwd), = db.bootstrap_credentials
        self.assertEqual(uid, "superadmin")
        self.assertIsNone(db.authenticate("superadmin", "superadmin"))
        self.assertIsNotNone(db.authenticate("superadmin", pwd))
        # Second start: nothing new issued, password unchanged
        db2 = DBManager(central_db_path=self.db_path)
        self.assertEqual(db2.bootstrap_credentials, [])
        self.assertIsNotNone(db2.authenticate("superadmin", pwd))

    def test_legacy_default_accounts_are_rotated(self):
        import sqlite3
        db = DBManager(central_db_path=self.db_path)
        legacy_hash, legacy_salt = hash_password("admin", iterations=100000)
        legacy_hex = legacy_hash.split("$")[-1]  # old storage format: bare hex, 100k iterations
        con = sqlite3.connect(self.db_path)
        con.execute("INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES ('admin','A',?,?,'ADMIN',1)",
                    (legacy_hex, legacy_salt))
        con.commit(); con.close()
        self.assertIsNotNone(db.authenticate("admin", "admin"))  # legacy hash still verifies...
        db2 = DBManager(central_db_path=self.db_path)              # ...until the next server start rotates it
        issued = dict(db2.bootstrap_credentials)
        self.assertIn("admin", issued)
        self.assertIsNone(db2.authenticate("admin", "admin"))
        self.assertIsNotNone(db2.authenticate("admin", issued["admin"]))

    def test_used_accounts_are_never_rotated_and_hashes_upgrade(self):
        db = DBManager(central_db_path=self.db_path)
        db.create_user(ROLE_SUPER_ADMIN, "coo", "COO", ROLE_COO)
        db.change_password("coo", "MyRealPassw0rd", require_old=False)
        db2 = DBManager(central_db_path=self.db_path)
        self.assertNotIn("coo", dict(db2.bootstrap_credentials))
        self.assertIsNotNone(db2.authenticate("coo", "MyRealPassw0rd"))

    def test_anonymous_actor_cannot_manage_users(self):
        db = DBManager(central_db_path=self.db_path)
        with self.assertRaises(PermissionError):
            db.create_user(None, "x", "X", ROLE_ADMIN)
        with self.assertRaises(PermissionError):
            db.create_user(ROLE_HEAD, "x", "X", ROLE_HEAD, "URB")
        with self.assertRaises(PermissionError):
            db.reset_user_password(None, "superadmin")
