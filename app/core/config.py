import sys
import os
from pathlib import Path

# Compute canonical Base Directory so source code and PyInstaller bundle share the same database
if getattr(sys, 'frozen', False):
    exe_dir = Path(sys.executable).resolve().parent
    if exe_dir.name == "DeskApp" and exe_dir.parent.name == "dist":
        BASE_DIR = exe_dir.parent.parent
    else:
        BASE_DIR = exe_dir
else:
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

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
