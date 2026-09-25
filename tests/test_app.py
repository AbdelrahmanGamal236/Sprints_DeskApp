import unittest
import os
import tempfile
import asyncio
from pathlib import Path
from app.core.auth import hash_password, verify_password
from app.database.db_manager import DBManager, ClientQueueDBManager
from app.services.excel_service import ExcelExportService

class TestOfflineApp(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_central.db"
        self.queue_db_path = Path(self.temp_dir.name) / "test_queue.db"
        
        self.db = DBManager(central_db_path=self.db_path)
        self.queue_db = ClientQueueDBManager(queue_db_path=self.queue_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_auth_hashing(self):
        pwd = "SecretPassword123"
        pwd_hash, pwd_salt = hash_password(pwd)
        self.assertTrue(verify_password(pwd, pwd_hash, pwd_salt))
        self.assertFalse(verify_password("WrongPassword", pwd_hash, pwd_salt))

    def test_database_seeding_and_soft_delete(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check default seed users
            cursor.execute("SELECT * FROM users WHERE user_id = 'admin'")
            admin = cursor.fetchone()
            self.assertIsNotNone(admin)
            self.assertEqual(admin["role"], "ADMIN")

            # Check soft-delete on project
            cursor.execute("UPDATE projects SET is_hidden = 1 WHERE project_id = 'PRJ-01'")
            conn.commit()

            cursor.execute("SELECT * FROM projects WHERE project_id = 'PRJ-01'")
            prj = cursor.fetchone()
            self.assertEqual(prj["is_hidden"], 1)

    def test_offline_queue(self):
        self.queue_db.add_to_queue("SUBMIT_LOG", '{"log_id": "LOG-TEST", "employee_id": "1001"}')
        queued = self.queue_db.get_all_queued()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["event_type"], "SUBMIT_LOG")

        self.queue_db.delete_queued(queued[0]["queue_id"])
        self.assertEqual(len(self.queue_db.get_all_queued()), 0)

    def test_excel_export(self):
        excel_service = ExcelExportService(self.db)
        output_xlsx = Path(self.temp_dir.name) / "test_report.xlsx"
        result_path = excel_service.export_logs_to_excel(str(output_xlsx))
        self.assertTrue(os.path.exists(result_path))

    def test_revision_counter(self):
        # Initial revision count should be 1
        rev1 = self.db.get_next_revision_number("1001", "PRJ-01", "TSK-01")
        self.assertEqual(rev1, 1)

        # Insert a REVISION log
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date, end_date, progress_stage, entry_type, revision_number)
            VALUES ('LOG-REV1', '1001', 'PRJ-01', 'TSK-01', '2026-09-23', '2026-09-23', 'Revision', 'REVISION', 1)
            """)
            conn.commit()

        # Next revision count should be 2
        rev2 = self.db.get_next_revision_number("1001", "PRJ-01", "TSK-01")
        self.assertEqual(rev2, 2)

    def test_analysis_queries(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert sample logs for analysis testing
            cursor.execute("""
            INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date, end_date, progress_stage, entry_type, revision_number)
            VALUES ('LOG-A1', '1001', 'PRJ-01', 'TSK-01', '2026-09-24', '2026-09-24', 'Done', 'NEW', 0)
            """)
            cursor.execute("""
            INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date, end_date, progress_stage, entry_type, revision_number)
            VALUES ('LOG-A2', '1001', 'PRJ-01', 'TSK-01', '2026-09-25', '2026-09-25', 'Revision', 'REVISION', 1)
            """)
            conn.commit()

            cursor.execute("SELECT COUNT(*) AS count FROM progress_logs WHERE entry_type = 'REVISION'")
            total_revs = cursor.fetchone()["count"]
            self.assertEqual(total_revs, 1)

            cursor.execute("""
            SELECT u.user_id,
                   COUNT(l.log_id) AS total_logs,
                   SUM(CASE WHEN l.entry_type = 'REVISION' THEN 1 ELSE 0 END) AS rev_logs
            FROM users u
            LEFT JOIN progress_logs l ON u.user_id = l.employee_id
            WHERE u.user_id = '1001'
            GROUP BY u.user_id
            """)
            emp_stat = cursor.fetchone()
            self.assertEqual(emp_stat["total_logs"], 2)
            self.assertEqual(emp_stat["rev_logs"], 1)

if __name__ == "__main__":
    unittest.main()

