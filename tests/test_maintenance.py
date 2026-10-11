"""M6: backups (schedule, integrity, retention), restore and log files."""
import argparse
import asyncio
import logging
import shutil
import socket
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.database.db_manager import DBManager
from app.services.maintenance import BackupScheduler, restore_database, setup_logging


class MaintBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deskapp_maint_"))
        self.db = DBManager(central_db_path=self.tmp / "central_app.db")
        self.backups = self.tmp / "backups"
        self.assertEqual(self.db.backups_dir, self.backups)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBackups(MaintBase):
    def test_backup_is_consistent_and_checked(self):
        self.db.add_project("P1", "One")
        path = Path(self.db.backup_database(folder=self.backups))
        self.assertRegex(path.name, r"^central_app_\d{8}_\d{6}\.db$")
        self.assertTrue(DBManager.check_integrity(path))
        self.assertFalse(Path(str(path) + "-wal").exists())  # single self-contained file
        self.assertFalse(Path(str(path) + "-shm").exists())
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT name FROM projects WHERE project_id='P1'").fetchone()[0], "One")
        con.close()

    def test_retention_only_prunes_automatic_backups(self):
        self.backups.mkdir()
        legacy = [self.backups / "central_app_20261010.db", self.backups / "central_app_backup_pre_rebuild_1.db"]
        for f in legacy:
            f.write_bytes(b"")
        base = datetime(2026, 10, 1, 2, 0, 0)
        for i in range(6):
            self.db.backup_database(max_copies=3, now=base + timedelta(days=i), folder=self.backups)
        kept = [p.name for p in self.db.list_backups(self.backups)]
        self.assertEqual(kept, ["central_app_20261004_020000.db", "central_app_20261005_020000.db",
                                "central_app_20261006_020000.db"])
        self.assertTrue(all(f.exists() for f in legacy))

    def test_damaged_file_detected(self):
        bad = self.tmp / "bad.db"
        bad.write_bytes(b"this is not a database" * 100)
        self.assertFalse(DBManager.check_integrity(bad))


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


class TestBackupScheduler(MaintBase):
    def _run_until(self, clock, until: datetime, made: list):
        orig = self.db.backup_database
        self.db.backup_database = lambda: made.append(clock()) or orig(now=clock())

        async def scenario():
            task = asyncio.ensure_future(BackupScheduler(self.db, clock=clock, sleep=clock.sleep, max_wait=600).run())
            while clock() < until:
                await asyncio.sleep(0)
            task.cancel()
        asyncio.run(scenario())

    def test_startup_and_daily_schedule(self):
        self.db.update_settings({"backup_time": "02:00"}, "sa")
        clock = FakeClock(datetime(2026, 10, 1, 0, 30))
        made = []
        self._run_until(clock, datetime(2026, 10, 3, 3, 0), made)
        # startup copy (none existed today), then 02:00 on Oct 1, 2 and 3
        self.assertEqual([m.strftime("%m-%d %H:%M") for m in made][0], "10-01 00:30")
        scheduled = [m for m in made[1:]]
        self.assertEqual([(m.day, m.hour) for m in scheduled], [(1, 2), (2, 2), (3, 2)])

    def test_start_after_backup_time_waits_for_tomorrow(self):
        self.db.update_settings({"backup_time": "02:00"}, "sa")
        clock = FakeClock(datetime(2026, 10, 1, 9, 0))
        made = []
        self._run_until(clock, datetime(2026, 10, 2, 3, 0), made)
        self.assertEqual([(m.day, m.hour) for m in made], [(1, 9), (2, 2)])


class TestRestore(MaintBase):
    def test_restore_replaces_db_and_keeps_safety_copy(self):
        self.db.add_project("KEEP", "In backup")
        backup = Path(self.db.backup_database(folder=self.backups))
        self.db.add_project("LATE", "Added after backup")
        safety = restore_database(backup, self.db.db_path, self.backups)
        ids = {p["project_id"] for p in DBManager(central_db_path=self.db.db_path).get_projects()}
        self.assertEqual(ids, {"KEEP"})
        con = sqlite3.connect(safety)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM projects WHERE project_id='LATE'").fetchone()[0], 1)
        con.close()

    def test_restore_refuses_damaged_or_missing_file(self):
        bad = self.tmp / "bad.db"
        bad.write_bytes(b"garbage" * 50)
        with self.assertRaises(ValueError):
            restore_database(bad, self.db.db_path, self.backups)
        with self.assertRaises(FileNotFoundError):
            restore_database(self.tmp / "missing.db", self.db.db_path, self.backups)

    def test_cli_refuses_while_server_running(self):
        import main
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            port = s.getsockname()[1]
            args = argparse.Namespace(port=port, restore=str(self.tmp / "x.db"), yes=True)
            self.assertEqual(main.run_restore(args), 1)


class TestEmergencyReset(MaintBase):
    def test_reset_superadmin(self):
        from app.core.config import ROLE_SUPER_ADMIN, ROLE_ADMIN
        self.db.update_user(ROLE_SUPER_ADMIN, "superadmin", role=None)  # exists from bootstrap
        pwd = self.db.emergency_reset_superadmin()
        user = self.db.authenticate("superadmin", pwd)
        self.assertEqual(user["role"], ROLE_SUPER_ADMIN)
        self.assertEqual(user["must_change_password"], 1)


class TestLogging(unittest.TestCase):
    def test_rotating_log_file(self):
        folder = Path(tempfile.mkdtemp())
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            log_file = setup_logging(folder, "server")
            logging.getLogger("deskapp.test").info("hello log file")
            for h in logging.getLogger().handlers:
                h.flush()
            self.assertIn("hello log file", log_file.read_text(encoding="utf-8"))
        finally:
            for h in list(root.handlers):
                h.close()
                root.removeHandler(h)
            for h in saved:
                root.addHandler(h)
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
