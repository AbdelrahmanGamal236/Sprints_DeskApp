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
