import sys
import os
import tempfile

# Add workspace root directory to python path for pytest
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Isolate every test run from the real data/ folder (DB, queue, backups, seed file).
# Must happen before any `app.*` import, because config paths are resolved at import time.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="deskapp_test_data_")
os.environ["DESKAPP_DATA_DIR"] = _TEST_DATA_DIR

# Fast password hashing for tests (production default is 600k iterations).
os.environ.setdefault("DESKAPP_PBKDF2_ITERATIONS", "1000")

# Keep UI settings (remembered server IP, layouts) out of the Windows registry during tests.
os.environ["DESKAPP_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="deskapp_test_settings_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
