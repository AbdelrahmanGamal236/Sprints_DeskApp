import sys
import os
import tempfile
from pathlib import Path

APP_VERSION = "2.0.0"

# Compute canonical Base Directory so source code and PyInstaller bundle share the same database
if getattr(sys, 'frozen', False):
    exe_dir = Path(sys.executable).resolve().parent
    if exe_dir.name == "DeskApp" and exe_dir.parent.name == "dist":
        BASE_DIR = exe_dir.parent.parent
    else:
        BASE_DIR = exe_dir
else:
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

# DESKAPP_DATA_DIR overrides the data folder (used by tests and multi-instance local testing)
if os.environ.get("DESKAPP_DATA_DIR"):
    DATA_DIR = Path(os.environ["DESKAPP_DATA_DIR"])
elif os.environ.get("DESKAPP_DEMO") == "1":
    # --standalone demo mode keeps its sample data away from the real database
    DATA_DIR = BASE_DIR / "data_demo"
else:
    DATA_DIR = BASE_DIR / "data"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write_test_", delete=True):
            pass
        return True
    except OSError:
        return False


if not _writable(DATA_DIR) and not os.environ.get("DESKAPP_DATA_DIR"):
    # e.g. installed under C:\Program Files: keep data in the machine-wide ProgramData folder instead
    DATA_DIR = Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "DeskApp" / DATA_DIR.name
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR = DATA_DIR / "logs"
BACKUPS_DIR = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
SEED_HEADS_PATH = DATA_DIR / "seed_heads.json"

# Database Paths
CENTRAL_DB_PATH = DATA_DIR / "central_app.db"
CLIENT_QUEUE_DB_PATH = DATA_DIR / "client_queue.db"

# Networking Configuration
DEFAULT_WS_PORT = 8765
DEFAULT_HOST = "0.0.0.0"

# Progress Stages / Task Statuses
PROGRESS_STAGES = [
    "In Progress",
    "Revision",
    "Hold",
    "Done"
]

# Entry Types
ENTRY_TYPE_NEW = "NEW"
ENTRY_TYPE_CONTINUATION = "CONTINUATION"
ENTRY_TYPE_REVISION = "REVISION"

# User Roles
ROLE_HEAD = "HEAD"
ROLE_ADMIN = "ADMIN"
ROLE_COO = "COO"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"

ALL_ROLES = [ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN]

# Default Disciplines (idempotent seeding list in specified display order)
DEFAULT_DISCIPLINES = [
    ("URB", "Urban"),
    ("STR", "Structure"),
    ("INT", "Interior"),
    ("ARC", "Architectural"),
    ("BIM", "BIM"),
    ("MEC", "Mechanical"),
    ("ELE", "Electrical"),
    ("AI", "AI"),
    ("QC", "QC"),
    ("Infrastructure", "Infrastructure")
]
