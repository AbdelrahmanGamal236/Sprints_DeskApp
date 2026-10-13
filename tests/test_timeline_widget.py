"""
The project timeline must actually paint. A Python error inside paintEvent does not crash Qt; it is
reported to sys.excepthook and the canvas stays blank, so this test fails on any such error.
"""
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.core.config import ROLE_HEAD, ROLE_SUPER_ADMIN
from app.database.db_manager import DBManager


class TestTimelinePaints(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix="deskapp_tl_"))
        db = self.db = DBManager(central_db_path=self.tmp / "c.db")
        db.create_user(ROLE_SUPER_ADMIN, "h1", "Head One", ROLE_HEAD, "Infrastructure")
        db.add_project("P1", "Tower")
        db.add_task("P1", "T1", "Infrastructure Drainage & Trench Cabling for the whole site", "Infrastructure",
                    "2026-10-11", "2026-10-18")
        db.add_task("P1", "T2", "Short", "URB", "2026-10-13", "2026-10-20")
        db.add_task("P1", "T3", "No dates yet", "URB")
        db.submit_progress_log({"log_id": str(uuid.uuid4()), "employee_id": "h1", "project_id": "P1",
                                "task_id": "T1", "progress_stage": "Done"})
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda *exc: self.errors.append(exc)

    def tearDown(self):
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timeline_renders_tasks_without_errors(self):
        from app.ui.timeline_widget import ProjectProgressiveTimelineWidget
        w = ProjectProgressiveTimelineWidget()
        w.resize(1200, 600)
        w.load_timeline_data(self.db.get_project_timeline_data("P1"))
        w.show()
        self.app.processEvents()
        w.grab()
        self.assertEqual(self.errors, [], "timeline paintEvent raised an error")
        self.assertEqual(len(w.canvas.tasks), 3)
        self.assertEqual(w.lbl_total_tasks.text(), "Tasks: 3")
        # Bars sit inside the chart, later dates further right
        from datetime import datetime
        x1 = w.canvas._date_to_x(datetime(2026, 10, 11), 800)
        x2 = w.canvas._date_to_x(datetime(2026, 10, 18), 800)
        self.assertLess(w.canvas.left_margin - 1, x1)
        self.assertLess(x1, x2)
        # A discipline filter is dropped when the next project has no task of that discipline
        w.on_discipline_filter("Infrastructure")
        self.assertEqual(len(w.canvas.tasks), 1)
        self.db.add_project("P2", "Mall")
        self.db.add_task("P2", "T9", "Mall task", "URB", "2026-10-01", "2026-10-05")
        w.load_timeline_data(self.db.get_project_timeline_data("P2"))
        self.assertEqual(len(w.canvas.tasks), 1)
        w.grab()
        self.assertEqual(self.errors, [])
        w.close()


if __name__ == "__main__":
    unittest.main()
