"""Server maintenance: scheduled backups, restore from a backup, and log file setup."""
import asyncio
import logging
import shutil
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupScheduler:
    """
    Runs inside the Central Server:
    - at startup, makes a backup if none was made today;
    - then every day at the Super Admin's 'backup_time' setting (re-read before each wait).
    `clock` and `sleep` are injectable for tests.
    """
    def __init__(self, db, run_in_executor=None, clock=datetime.now, sleep=asyncio.sleep, max_wait: float = 300):
        self.db = db
        self.run_in_executor = run_in_executor
        self.clock = clock
        self.sleep = sleep
        self.max_wait = max_wait  # wake up regularly so a changed backup time or clock jump is noticed

    async def _backup(self):
        if self.run_in_executor:
            return await self.run_in_executor(self.db.backup_database)
        return self.db.backup_database()

    def made_today(self) -> bool:
        today = self.clock().strftime("%Y%m%d")
        return any(p.name.startswith(f"central_app_{today}_") for p in self.db.list_backups())

    async def run(self):
        if not self.made_today():
            await self._backup()
        start = self.clock()
        # A server started after today's backup time waits for tomorrow's slot (the startup copy covers today)
        done_for = start.date() if start >= self._slot(start) else None
        while True:
            now = self.clock()
            slot = self._slot(now)
            if now >= slot and done_for != now.date():
                await self._backup()
                done_for = now.date()
            upcoming = slot if now < slot else slot + timedelta(days=1)
            await self.sleep(max(1.0, min((upcoming - now).total_seconds(), self.max_wait)))

    def _slot(self, now: datetime) -> datetime:
        """Today's backup time; the setting is re-read every time so changes apply without a restart."""
        hour, minute = (int(x) for x in self.db.get_settings()["backup_time"].split(":"))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def restore_database(backup_file: Path, db_path: Path, backups_dir: Path) -> Path:
    """
    Replace the live database with a backup. The server must NOT be running.
    The current database is first saved as central_app_pre_restore_<timestamp>.db.
    Returns the path of that safety copy.
    """
    from app.database.db_manager import DBManager
    backup_file = Path(backup_file)
    if not backup_file.is_file():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    if not DBManager.check_integrity(backup_file):
        raise ValueError(f"The backup file is damaged and was not restored: {backup_file.name}")

    backups_dir.mkdir(parents=True, exist_ok=True)
    safety = backups_dir / f"central_app_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    if db_path.exists():
        import sqlite3
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(safety)
        try:
            src.backup(dst)  # includes any data still in the WAL file
        finally:
            dst.close()
            src.close()
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(backup_file, db_path)
    return safety


def setup_logging(log_dir: Path, name: str, level=logging.INFO):
    """Console + rotating file log (5 files x 5 MB) in data/logs/<name>.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    file_handler = RotatingFileHandler(log_dir / f"{name}.log", maxBytes=5 * 1024 * 1024, backupCount=5,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    if sys.stderr is not None:  # windowed exe has no console
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    def log_uncaught(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            logging.getLogger("deskapp").critical("Unhandled error", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = log_uncaught
    return log_dir / f"{name}.log"
