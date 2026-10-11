import sys
import os
import tempfile

# Add workspace root directory to python path for pytest
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Isolate every test run from the real data/ folder (DB, queue, backups, seed file).
# Must happen before any `app.*` import, because config paths are resolved at import time.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="deskapp_test_data_")
os.environ["DESKAPP_DATA_DIR"] = _TEST_DATA_DIR
