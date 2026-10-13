"""
Headless test of the Admin "Manage Tasks" tab: the "+ Add New Task Directly" button must open the dialog,
send ADD_TASK and show the new task in its discipline tab once the server confirms.
"""
import argparse
import asyncio
import unittest

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QMessageBox

from tests.helpers import start_server, wait_until, PASSWORD


class TestAdminAddTaskDialog(unittest.TestCase):
    def test_add_task_directly(self):
        from qasync import QEventLoop
        app = QApplication.instance() or QApplication([])
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)
        import main as main_module

        errors = []
        orig_critical, orig_warning = QMessageBox.critical, QMessageBox.warning
        QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[1:]))
        QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[1:]))
        orig_exec = QDialog.exec

        def fake_exec(dlg):
            # Fill the dialog like a user would, then click "Create & Assign Task"
            dlg.findChild(QLineEdit).setText("Directly added task")
            btn = next(b for b in dlg.findChildren(QPushButton) if b.text().startswith("Create"))
            btn.click()
            return dlg.result()

        async def scenario():
            server = await start_server()
            ctrl = main_module.AppController(app, argparse.Namespace(server_ip="127.0.0.1", port=server.port,
                                                                     standalone=False))
            ctrl.quit = lambda: None
            try:
                ctrl.show_login()
                dlg = ctrl.login_dialog
                dlg.txt_id.setText("adm")
                dlg.txt_pwd.setText(PASSWORD)
                dlg.txt_ip.setText("127.0.0.1")
                dlg.on_login()
                self.assertTrue(await wait_until(lambda: ctrl.workspace is not None, timeout=15))
                ws = ctrl.workspace.panel
                self.assertTrue(await wait_until(lambda: ws.cmb_task_prj.count() >= 1))
                self.assertTrue(await wait_until(lambda: ws.tabs_disciplines.count() >= 1))
                ws.cmb_task_prj.setCurrentIndex(ws.cmb_task_prj.findData("P1"))
                btn = next(b for b in ws.findChildren(QPushButton) if b.text() == "+ Add New Task Directly")
                QDialog.exec = fake_exec
                btn.click()
                QDialog.exec = orig_exec
                ok = await wait_until(lambda: any(t["name"] == "Directly added task"
                                                  for t in server.db.get_tasks()), timeout=10)
                self.assertTrue(ok, f"task not created; dialogs shown: {errors}")
                self.assertTrue(await wait_until(lambda: any(t["name"] == "Directly added task"
                                                             for t in ws.tasks_data)))
                self.assertEqual(errors, [])

                # Approve a Head's request through the Approve button, renaming the task
                server.db.create_task_proposal("P1", "drainge stdy", "h_urb", "URB", "2026-10-01", "2026-10-14", "PROP-UI")
                await server.notify_changed("proposals")
                self.assertTrue(await wait_until(lambda: ws.tbl_pending_proposals.rowCount() == 1))
                from PySide6.QtWidgets import QInputDialog
                asked = []
                orig_get = QInputDialog.getText
                QInputDialog.getText = staticmethod(lambda *a, **k: (asked.append(a[-1]), ("Drainage Study", True))[1])
                try:
                    cell = ws.tbl_pending_proposals.cellWidget(0, 6)
                    next(b for b in cell.findChildren(QPushButton) if b.text() == "Approve").click()
                finally:
                    QInputDialog.getText = orig_get
                self.assertEqual(asked, ["drainge stdy"])  # dialog pre-filled with the requested name
                self.assertTrue(await wait_until(lambda: any(t["name"] == "Drainage Study" for t in server.db.get_tasks())))
                self.assertTrue(await wait_until(lambda: ws.tbl_pending_proposals.rowCount() == 0))
                self.assertEqual(errors, [])
            finally:
                QDialog.exec = orig_exec
                QMessageBox.critical, QMessageBox.warning = orig_critical, orig_warning
                if ctrl.workspace is not None:
                    ctrl.workspace.logout_requested = True
                    ctrl.workspace.close()
                await asyncio.sleep(0.2)
                await server.stop()

        with loop:
            loop.run_until_complete(scenario())


if __name__ == "__main__":
    unittest.main()
