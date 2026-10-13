"""M2 data-integrity rules enforced in the database layer."""
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import ROLE_HEAD, ROLE_SUPER_ADMIN
from app.database.db_manager import DBManager


class IntegrityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deskapp_integrity_"))
        self.db = DBManager(central_db_path=self.tmp / "c.db")
        db = self.db
        db.create_user(ROLE_SUPER_ADMIN, "h1", "Head One", ROLE_HEAD, "URB")
        db.create_user(ROLE_SUPER_ADMIN, "h2", "Head Two", ROLE_HEAD, "URB")
        db.create_user(ROLE_SUPER_ADMIN, "h3", "Head Three", ROLE_HEAD, "STR")
        db.add_project("P1", "Project One")
        db.add_project("P2", "Project Two")
        db.add_task("P1", "T1", "Urban task", "URB", "2026-10-01", "2026-10-10")
        db.add_task("P2", "T2", "Urban task 2", "URB", "2026-10-01", "2026-10-10")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self, employee="h1", task="T1", project="P1", **extra):
        p = {"log_id": f"LOG-{uuid.uuid4().hex}", "employee_id": employee, "project_id": project, "task_id": task,
             "start_date": "2026-10-02", "end_date": "2026-10-02", "progress_stage": "In Progress"}
        p.update(extra)
        return self.db.submit_progress_log(p)


class TestSqliteConfiguration(IntegrityBase):
    def test_wal_and_foreign_keys(self):
        con = sqlite3.connect(self.db.db_path)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        con.close()
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date,
                                end_date, progress_stage) VALUES ('X', 'nobody', 'P1', 'T1', 'a', 'b', 'Done')""")


class TestRevisionCounter(IntegrityBase):
    def setUp(self):
        super().setUp()
        # Each task's first entry is its New Task entry; revisions come after it
        self.log(entry_type="NEW")
        self.log(task="T2", project="P2", entry_type="NEW")

    def test_server_assigns_revision_per_task(self):
        r1 = self.log(entry_type="REVISION", revision_number=1)
        r2 = self.log(employee="h2", entry_type="REVISION", revision_number=1)  # stale client value ignored
        other = self.log(task="T2", project="P2", entry_type="REVISION", revision_number=9)
        cont = self.log(entry_type="CONTINUATION", revision_number=5)
        self.assertEqual((r1["revision_number"], r2["revision_number"]), (1, 2))
        self.assertEqual(other["revision_number"], 1)
        self.assertEqual(cont["revision_number"], 0)
        self.assertEqual(self.db.get_next_revision_number("h1", "P1", "T1"), 3)

    def test_concurrent_revisions_are_unique(self):
        results, errors = [], []

        def worker(emp):
            try:
                db = DBManager.__new__(DBManager)  # separate connections, same file, no re-init
                db.db_path = self.db.db_path
                results.append(self.log_with(db, emp)["revision_number"])
            except Exception as e:  # pragma: no cover - surfaced below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=("h1" if i % 2 else "h2",)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), list(range(1, 13)))

    @staticmethod
    def log_with(db, emp):
        return db.submit_progress_log({"log_id": f"LOG-{uuid.uuid4().hex}", "employee_id": emp, "project_id": "P1",
                                       "task_id": "T1", "start_date": "2026-10-02", "end_date": "2026-10-02",
                                       "progress_stage": "Revision", "entry_type": "REVISION"})

    def test_resend_keeps_original_revision(self):
        payload = {"log_id": "LOG-SAME", "employee_id": "h1", "project_id": "P1", "task_id": "T1",
                   "start_date": "2026-10-02", "end_date": "2026-10-02", "progress_stage": "Revision",
                   "entry_type": "REVISION"}
        first = self.db.submit_progress_log(dict(payload))
        again = self.db.submit_progress_log(dict(payload))
        self.assertEqual(first["revision_number"], again["revision_number"])
        self.assertEqual(len([l for l in self.db.get_progress_logs() if l["log_id"] == "LOG-SAME"]), 1)


class TestApprovalStateMachine(IntegrityBase):
    def test_double_approve_creates_one_task(self):
        p = self.db.create_task_proposal("P1", "New idea", "h1", "URB", "2026-10-05", "2026-10-09", "PROP-1")
        self.assertIsNone(p["task_id"])  # IDs are no longer reserved at proposal time
        a1 = self.db.approve_task_proposal("PROP-1", "adm")
        a2 = self.db.approve_task_proposal("PROP-1", "adm")
        self.assertEqual(a1["task_id"], a2["task_id"])
        self.assertEqual(len([t for t in self.db.get_tasks() if t["name"] == "New idea"]), 1)
        self.assertEqual(a1["proposed_by_id"], "h1")
        with self.assertRaises(ValueError):
            self.db.reject_task_proposal("PROP-1", "adm", "too late")

    def test_rejected_cannot_be_approved(self):
        self.db.create_task_proposal("P1", "Bad idea", "h1", proposal_id="PROP-2")
        r = self.db.reject_task_proposal("PROP-2", "adm", "Out of scope")
        self.assertEqual(r["proposed_by_id"], "h1")
        with self.assertRaises(ValueError):
            self.db.approve_task_proposal("PROP-2", "adm")
        with self.assertRaises(ValueError):
            self.db.reject_task_proposal("PROP-2", "adm", "   ")
        self.assertFalse(any(t["name"] == "Bad idea" for t in self.db.get_tasks()))

    def test_date_change_transitions(self):
        self.db.create_task_date_change_request("T1", "h1", "2026-10-03", "2026-10-20", "Client delay", "DCR-1")
        a1 = self.db.approve_task_date_change_request("DCR-1", "adm")
        self.assertEqual(a1["requested_by_id"], "h1")
        self.db.approve_task_date_change_request("DCR-1", "adm")  # idempotent
        with self.assertRaises(ValueError):
            self.db.reject_task_date_change_request("DCR-1", "adm", "no")
        t = next(t for t in self.db.get_tasks() if t["task_id"] == "T1")
        self.assertEqual((t["planned_start_date"], t["planned_end_date"]), ("2026-10-03", "2026-10-20"))
        with self.assertRaises(ValueError):
            self.db.create_task_date_change_request("T1", "h1", "2026-10-20", "2026-10-03", "backwards")

    def test_concurrent_task_ids_are_unique(self):
        ids, errors = [], []

        def worker(i):
            try:
                db = DBManager.__new__(DBManager)
                db.db_path = self.db.db_path
                ids.append(db.add_task("P1", name=f"Parallel {i}", discipline_id="URB")["task_id"])
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 10)


class TestSoftDelete(IntegrityBase):
    def test_delete_task_keeps_logs(self):
        lg = self.log()
        self.db.delete_task("T1", "adm")
        self.assertFalse(any(t["task_id"] == "T1" for t in self.db.get_tasks(include_hidden=True)))
        self.assertTrue(any(t["task_id"] == "T1" for t in self.db.get_tasks(include_hidden=True, include_deleted=True)))
        row = next(l for l in self.db.get_progress_logs() if l["log_id"] == lg["log_id"])
        self.assertEqual(row["task_deleted"], 1)
        with self.assertRaises(ValueError):
            self.log()
        with self.assertRaises(ValueError):
            self.db.add_task("P1", "T1", "Reuse id", "URB")
        with self.assertRaises(ValueError):
            self.db.delete_task("T1", "adm")

    def test_delete_project_hides_its_tasks(self):
        lg = self.log()
        self.db.delete_project("P1", "adm")
        self.assertEqual([p["project_id"] for p in self.db.get_projects(include_hidden=True)], ["P2"])
        self.assertFalse(any(t["project_id"] == "P1" for t in self.db.get_tasks(include_hidden=True)))
        self.assertEqual(self.db.get_project_timeline_data("P1"), {})
        row = next(l for l in self.db.get_progress_logs() if l["log_id"] == lg["log_id"])
        self.assertEqual(row["project_deleted"], 1)
        with self.assertRaises(ValueError):
            self.db.add_project("P1", "Again")
        with self.assertRaises(ValueError):
            self.db.create_task_proposal("P1", "x", "h1")

    def test_hidden_task_rejects_new_logs(self):
        self.db.toggle_hide_task("T1", 0)
        with self.assertRaises(ValueError):
            self.log()
        self.db.toggle_hide_task("T1", 1)
        self.log()


class TestEntryTypeRule(IntegrityBase):
    def test_new_task_only_for_the_first_entry(self):
        with self.assertRaises(ValueError) as ctx:
            self.log(entry_type="CONTINUATION")
        self.assertIn("must be New Task", str(ctx.exception))
        with self.assertRaises(ValueError):
            self.log(entry_type="REVISION")
        self.assertEqual(self.db.get_tasks(project_id="P1")[0]["log_count"], 0)
        first = self.log(entry_type="NEW")
        self.assertTrue(first["first_entry"])
        # Shared by all Heads of the task: another Head cannot add a second New Task entry
        with self.assertRaises(ValueError) as ctx:
            self.log(employee="h2", entry_type="NEW")
        self.assertIn("Continuation or Revision", str(ctx.exception))
        self.assertEqual(self.log(employee="h2", entry_type="CONTINUATION")["entry_type"], "CONTINUATION")
        self.assertEqual(self.log(entry_type="REVISION")["revision_number"], 1)
        self.assertEqual(self.db.get_tasks(project_id="P1")[0]["log_count"], 3)
        # A resend of the stored New Task entry is still accepted (idempotent), not rejected
        again = self.db.submit_progress_log({"log_id": first["log_id"], "employee_id": "h1", "project_id": "P1",
                                             "task_id": "T1", "progress_stage": "In Progress", "entry_type": "NEW"})
        self.assertEqual(again["log_id"], first["log_id"])

    def test_missing_entry_type_is_chosen_from_history(self):
        """Older clients that send no entry type get New first, then Continuation."""
        self.assertEqual(self.log(entry_type=None)["entry_type"], "NEW")
        self.assertEqual(self.log(entry_type=None)["entry_type"], "CONTINUATION")


class TestValidation(IntegrityBase):
    def test_log_validation(self):
        bad = [
            {"progress_stage": "Almost"},
            {"entry_type": "OTHER"},
            {"notes": "x" * 5001},
            {"assigned_to": "y" * 101},
            {"task_id": "T2"},          # task belongs to P2
            {"task_id": "NOPE"},
        ]
        for extra in bad:
            with self.assertRaises(ValueError, msg=str(extra)[:60]):
                self.log(**extra)
        with self.assertRaises(PermissionError):
            self.log(employee="h3")     # STR head on URB task
        ok = self.log(notes="fine", assigned_to="Eng. X")
        self.assertEqual((ok["notes"], ok["assigned_to"]), ("fine", "Eng. X"))

    def test_log_takes_task_dates_and_stage_progress(self):
        """Dates and % sent by a client are ignored: the log carries the task's planned period."""
        lg = self.log(start_date="2020-01-01", end_date="2030-12-31", progress_percentage=55)
        self.assertEqual((lg["start_date"], lg["end_date"]), ("2026-10-01", "2026-10-10"))
        self.assertEqual(lg["progress_percentage"], 0)
        done = self.log(progress_stage="Done")  # old clients that still send no dates are accepted too
        self.assertEqual(done["progress_percentage"], 100)
        # An approved date change applies to later logs only; earlier logs keep their dates
        self.db.update_task("T1", planned_end_date="2026-10-20")
        later = self.log()
        self.assertEqual(later["end_date"], "2026-10-20")
        stored = {l["log_id"]: l for l in self.db.get_progress_logs()}
        self.assertEqual(stored[lg["log_id"]]["end_date"], "2026-10-10")
        # The task's own dates are never changed by logging
        task = next(t for t in self.db.get_tasks() if t["task_id"] == "T1")
        self.assertEqual((task["planned_start_date"], task["planned_end_date"]), ("2026-10-01", "2026-10-20"))

    def test_timestamps_are_local(self):
        lg = self.log()
        stored = next(l for l in self.db.get_progress_logs() if l["log_id"] == lg["log_id"])["submitted_at"]
        delta = abs((datetime.now() - datetime.strptime(stored, "%Y-%m-%d %H:%M:%S")).total_seconds())
        self.assertLess(delta, 60)

    def test_task_and_user_validation(self):
        with self.assertRaises(ValueError):
            self.db.add_task("P1", name="x", discipline_id="NOPE")
        with self.assertRaises(ValueError):
            self.db.add_task("P1", name="x", discipline_id="URB", assigned_head_id="h3")  # STR head
        with self.assertRaises(ValueError):
            self.db.add_task("P1", name="x", discipline_id="URB", planned_start_date="2026-10-09",
                             planned_end_date="2026-10-01")
        with self.assertRaises(ValueError):
            self.db.create_user(ROLE_SUPER_ADMIN, "hx", "X", ROLE_HEAD, "NOPE")

    def test_seed_file_skips_unknown_discipline(self):
        f = self.tmp / "seed.json"
        f.write_text(json.dumps([{"user_id": "s1", "full_name": "Good", "discipline_id": "URB"},
                                 {"user_id": "s2", "full_name": "Bad", "discipline_id": "XYZ"}]), encoding="utf-8")
        self.db.seed_heads_from_file(f)
        self.assertIsNotNone(self.db.get_user("s1"))
        self.assertIsNone(self.db.get_user("s2"))


if __name__ == "__main__":
    unittest.main()
