"""
Migration tests: older databases must open with the current code without losing anything,
and running the migration twice must change nothing the second time.
"""
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.core.auth import hash_password
from app.database.db_manager import DBManager, SCHEMA_VERSION

FIXTURES = Path(__file__).parent / "fixtures"
REPO_DATA = Path(__file__).resolve().parent.parent / "data"

UTC_STAMP = "2026-10-01 08:30:00"


def utc_to_local(stamp: str) -> str:
    dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def snapshot(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'user_sessions'")]
    data = {t: sorted(tuple(r) for r in con.execute(f"SELECT * FROM {t}")) for t in tables}
    data["__schema__"] = sorted(r[0] or "" for r in con.execute("SELECT sql FROM sqlite_master"))
    data["__version__"] = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    return data


class MigrationTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deskapp_migr_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_current_schema(self, db_path: Path):
        con = sqlite3.connect(db_path)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        for table in ("projects", "tasks"):
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            self.assertTrue({"is_deleted", "deleted_at", "deleted_by"} <= cols, table)
        self.assertIn("password_plain", {r[1] for r in con.execute("PRAGMA table_info(users)")})
        log_cols = {r[1] for r in con.execute("PRAGMA table_info(progress_logs)")}
        self.assertTrue({"discipline_id", "assigned_to", "entry_type", "revision_number"} <= log_cols)
        con.close()

    def assert_idempotent(self, db_path: Path):
        DBManager(central_db_path=db_path)
        first = snapshot(db_path)
        DBManager(central_db_path=db_path)
        second = snapshot(db_path)
        self.assertEqual(first, second, "second migration run changed the database")


class TestMigrationFromFixtures(MigrationTestBase):
    def _build(self, schema_file: str, with_disciplines: bool) -> Path:
        db_path = self.tmp / "legacy.db"
        con = sqlite3.connect(db_path)
        con.executescript((FIXTURES / schema_file).read_text(encoding="utf-8"))
        h, salt = hash_password("Legacy-Pass-1", iterations=100000)
        legacy_hex = h.split("$")[-1]  # old format: bare hex digest at 100k iterations
        con.execute("INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) "
                    "VALUES ('h1', 'Head One', ?, ?, 'HEAD', 0)", (legacy_hex, salt))
        # Never-used account whose password is still its user ID (its readable copy can be filled in)
        h2_hash, h2_salt = hash_password("h2")
        con.execute("INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) "
                    "VALUES ('h2', 'Head Two', ?, ?, 'HEAD', 1)", (h2_hash, h2_salt))
        con.execute("INSERT INTO projects (project_id, name) VALUES ('P1', 'Old project')")
        con.execute("INSERT INTO tasks (task_id, project_id, name) VALUES ('TSK-07', 'P1', 'Old task')")
        con.execute("""INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date, end_date,
                       progress_stage, entry_type, revision_number, submitted_at)
                       VALUES ('L-OLD', 'h1', 'P1', 'TSK-07', '2026-10-01', '2026-10-01', 'Revision', 'REVISION', 1, ?)""",
                    (UTC_STAMP,))
        # A row pointing at a user that no longer exists (allowed before FKs were enforced)
        con.execute("""INSERT INTO progress_logs (log_id, employee_id, project_id, task_id, start_date, end_date,
                       progress_stage, submitted_at) VALUES ('L-ORPHAN', 'gone', 'P1', 'TSK-07', '2026-10-01',
                       '2026-10-01', 'Done', ?)""", (UTC_STAMP,))
        con.commit()
        con.close()
        return db_path

    def _check_migrated(self, db_path: Path):
        db = DBManager(central_db_path=db_path)
        self.assert_current_schema(db_path)
        logs = {l["log_id"]: l for l in db.get_progress_logs()}
        self.assertEqual(set(logs), {"L-OLD", "L-ORPHAN"})  # orphan kept, never deleted
        self.assertEqual(logs["L-OLD"]["submitted_at"], utc_to_local(UTC_STAMP))
        self.assertEqual(logs["L-OLD"]["project_deleted"], 0)
        # Legacy password hash still works and is upgraded on login (production work factor patched in;
        # the test suite otherwise runs with a low iteration count)
        # Readable passwords: known only where it is still the user ID, until the user's next login
        plain = {u["user_id"]: u["password_plain"] for u in db.get_users(include_passwords=True)}
        self.assertEqual((plain["h1"], plain["h2"]), (None, "h2"))
        from unittest import mock
        from app.core import auth
        with mock.patch.object(auth, "PBKDF2_ITERATIONS", 600000):
            self.assertIsNotNone(db.authenticate("h1", "Legacy-Pass-1"))
        self.assertEqual(next(u for u in db.get_users(include_passwords=True)
                              if u["user_id"] == "h1")["password_plain"], "Legacy-Pass-1")
        self.assertTrue(db.get_user("h1")["password_hash"].startswith("pbkdf2_sha256$"))
        # Revision numbering continues from the existing data
        self.assertEqual(db.get_next_revision_number("h1", "P1", "TSK-07"), 2)
        # New task IDs continue after the highest existing one
        self.assertEqual(db.generate_next_task_id(), "TSK-08")
        return db

    def test_migrate_initial_version_schema(self):
        db_path = self._build("schema_v0_initial.sql", with_disciplines=False)
        self._check_migrated(db_path)
        self.assert_idempotent(db_path)

    def test_migrate_pre_stabilization_schema(self):
        db_path = self._build("schema_pre_m2.sql", with_disciplines=True)
        self._check_migrated(db_path)
        self.assert_idempotent(db_path)

    def test_fresh_database(self):
        db_path = self.tmp / "fresh.db"
        DBManager(central_db_path=db_path)
        self.assert_current_schema(db_path)
        self.assert_idempotent(db_path)


class TestMigrationOfRealDatabases(MigrationTestBase):
    """Runs against copies of the real databases in data/ when they exist (skipped elsewhere)."""
    def _migrate_copy(self, source: Path):
        if not source.exists():
            self.skipTest(f"{source.name} not present")
        db_path = self.tmp / source.name
        shutil.copy2(source, db_path)
        before = snapshot(db_path)
        DBManager(central_db_path=db_path)
        self.assert_current_schema(db_path)
        after = snapshot(db_path)
        for table, rows in before.items():
            if table.startswith("__"):
                continue
            self.assertGreaterEqual(len(after[table]), len(rows), f"rows lost in {table}")
        self.assert_idempotent(db_path)

    def test_current_production_db_copy(self):
        self._migrate_copy(REPO_DATA / "central_app.db")

    def test_oldest_backup_copy(self):
        self._migrate_copy(REPO_DATA / "backups" / "central_app_20261010.db")


if __name__ == "__main__":
    unittest.main()
