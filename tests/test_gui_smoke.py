"""
Headless GUI smoke test (QT_QPA_PLATFORM=offscreen): drives the real LoginDialog, AppController and
every role workspace against a live server, so wiring between widgets and the protocol is exercised.
"""
import argparse
import asyncio
import unittest

from PySide6.QtWidgets import QApplication

from tests.helpers import start_server, wait_until, PASSWORD


def _loop():
    from qasync import QEventLoop
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    return app, loop


class TestGuiSmoke(unittest.TestCase):
    def test_all_roles_end_to_end(self):
        app, loop = _loop()
        import main as main_module

        async def login(ctrl, user_id):
            ctrl.show_login()
            dlg = ctrl.login_dialog
            dlg.txt_id.setText(user_id)
            dlg.txt_pwd.setText(PASSWORD)
            dlg.txt_ip.setText("127.0.0.1")
            dlg.on_login()
            self.assertTrue(await wait_until(lambda: ctrl.workspace is not None, timeout=15), f"login {user_id}")
            return ctrl.workspace

        async def logout(ctrl):
            ws = ctrl.workspace  # the RoleWindow / HeadWorkspace, not the inner panel
            ws.logout_requested = True
            ws.close()
            self.assertTrue(await wait_until(lambda: ctrl.workspace is None and ctrl.login_dialog.isVisible()))
            ctrl.login_dialog.close()

        async def scenario():
            server = await start_server()
            ctrl = main_module.AppController(app, argparse.Namespace(server_ip="127.0.0.1", port=server.port,
                                                                     standalone=False))
            ctrl.quit = lambda: None
            try:
                # ---- Admin: data loads, add project through the UI, server confirms
                ws = (await login(ctrl, "adm")).panel
                self.assertTrue(await wait_until(lambda: ws.tbl_projects.rowCount() == 2))
                self.assertTrue(await wait_until(lambda: ws.tbl_employees.rowCount() == 4))  # Heads only
                ws.txt_prj_id.setText("P3")
                ws.txt_prj_name.setText("Project Three")
                ws.on_add_project()
                self.assertTrue(await wait_until(lambda: ws.tbl_projects.rowCount() == 3))
                self.assertEqual(ws.cmb_timeline_prj.count(), 3)  # no duplicates after refreshes
                # Export through the real panel (file dialog replaced by a capture)
                import app.ui.export_panel as export_panel
                saved = []
                export_panel.save_excel_report = lambda parent, data, name: saved.append((data, name))
                exp = ws.export_panel
                self.assertTrue(await wait_until(lambda: exp.cmb_project.count() == 4 and exp.cmb_head.count() == 5))
                exp.cmb_discipline.setCurrentIndex(exp.cmb_discipline.findData("URB"))
                self.assertEqual(exp.cmb_head.count(), 3)  # All Heads + the two URB Heads
                exp.chk_dates.setChecked(True)
                self.assertIn("start_date", exp.current_filters())
                exp.on_export()
                self.assertTrue(await wait_until(lambda: len(saved) == 1, timeout=30))
                self.assertTrue(saved[0][0].startswith(b"PK"))  # xlsx is a zip file
                self.assertIn("URB", saved[0][1])
                # Soft delete through the same path the Delete button uses (confirmation dialog skipped)
                server.db.add_task("P3", "T-TMP", "Temporary", "URB")
                ws.mutate("DELETE_TASK", {"task_id": "T-TMP"}, "deleted")
                self.assertTrue(await wait_until(lambda: not any(t["task_id"] == "T-TMP" for t in ws.tasks_data)
                                                 and ws.toast.label.text() == "deleted"))
                await logout(ctrl)

                # ---- Head: projects/tasks load, submit a log, toast reflects the server ACK
                ws = await login(ctrl, "h_urb")
                self.assertTrue(await wait_until(lambda: ws.cmb_projects.count() == 3))
                self.assertTrue(await wait_until(lambda: ws.lst_tasks.count() == 1))
                ws.lst_tasks.setCurrentRow(0)
                ws.txt_notes.setPlainText("Smoke test log")
                ws.spn_percentage.setValue(40)
                ws.on_submit_log()
                self.assertTrue(await wait_until(
                    lambda: any(l["notes"] == "Smoke test log" for l in server.db.get_progress_logs())))
                stored = next(l for l in server.db.get_progress_logs() if l["notes"] == "Smoke test log")
                self.assertEqual(stored["progress_percentage"], 40)
                self.assertTrue(await wait_until(lambda: "saved on the Central Server" in ws.toast.label.text()))
                self.assertEqual(ws.sync_service.pending_count(), 0)
                # Real-time push: a task added by an Admin appears without any manual refresh
                before = ws.lst_tasks.count()
                server.db.add_task(ws.cmb_projects.currentData(), name="Pushed task", discipline_id="URB")
                await server.notify_changed("tasks")
                self.assertTrue(await wait_until(lambda: ws.lst_tasks.count() == before + 1))
                await logout(ctrl)

                # ---- COO: live feed shows the log, alert history and dispatch work
                ws = (await login(ctrl, "coo1")).panel
                self.assertTrue(await wait_until(lambda: ws.tbl_logs.rowCount() >= 1))
                self.assertTrue(await wait_until(lambda: ws.cmb_target_emp.count() == 4))
                ws.cmb_target_emp.setCurrentIndex(ws.cmb_target_emp.findData("h_urb"))
                ws.txt_message.setText("Please review P1")
                ws.on_send_priority_alert()
                self.assertTrue(await wait_until(lambda: ws.tbl_responses.rowCount() == 1))
                await logout(ctrl)

                # ---- Head gets the pending alert as a single modal on login
                ws = await login(ctrl, "h_urb")
                self.assertTrue(await wait_until(lambda: len(ws._open_alerts) == 1))
                modal = next(iter(ws._open_alerts.values()))
                ws.request_refresh_from_server()  # a refresh must not stack a second modal
                await asyncio.sleep(0.5)
                self.assertEqual(len(ws._open_alerts), 1)
                modal.on_accept()
                self.assertTrue(await wait_until(
                    lambda: server.db.get_priority_notifications(employee_id="h_urb")[0]["status"] == "ACCEPTED"))
                await logout(ctrl)

                # ---- Super Admin: sees every account; embedded Admin/COO tabs load without cross-talk
                ws = (await login(ctrl, "sa")).panel
                self.assertTrue(await wait_until(lambda: ws.tbl_users.rowCount() == len(server.db.get_users())))
                self.assertTrue(await wait_until(lambda: ws.admin_sub.tbl_projects.rowCount() == 3))
                await asyncio.sleep(0.5)
                self.assertEqual(ws.tbl_users.rowCount(), len(server.db.get_users()))  # not overwritten by the COO tab's Heads-only list
                # System Settings tab is populated from the server
                self.assertTrue(await wait_until(lambda: len(ws.settings_inputs) == 4))
                self.assertEqual(ws.settings_inputs["backup_retention_count"].value(), 30)
                await logout(ctrl)
            finally:
                await server.stop()

        loop.run_until_complete(scenario())


if __name__ == "__main__":
    unittest.main()
