import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QSplitter
)
from app.core.settings import app_settings
from app.network.client import NetworkClient, run_async
from app.ui.components import (
    ToastNotifier, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_item, describe_error, RoleWindow, restore_splitter
)

class CooPanel(QWidget):
    """COO live feed, priority alerts and export. Shown in CooWorkspace and in the Super Admin console."""
    def __init__(self, user_dict: dict, net_client: NetworkClient, parent=None):
        super().__init__(parent)
        self.user = user_dict
        self.net_client = net_client

        self.users_data = []

        central_widget = self
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.btn_export = QPushButton("Export Categorized Report", self)
        self.btn_export.clicked.connect(self.on_export_excel)
        top_bar.addWidget(self.btn_export)
        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Vertical Splitter: Top (Live Feed), Bottom (Priority Alert & Responses)
        self.main_splitter = QSplitter(Qt.Vertical, central_widget)

        # Top Panel: Real-Time Submissions Feed (with Assigned To column - A5)
        top_content = QWidget()
        top_layout = QVBoxLayout(top_content)
        top_layout.setContentsMargins(6, 6, 6, 6)

        self.tbl_logs = QTableWidget(0, 10)
        self.tbl_logs.setHorizontalHeaderLabels([
            "Log ID", "Employee", "Discipline", "Project", "Task", "Assigned To", "Context", "Schedule", "Status", "Notes"
        ])
        setup_modern_table(self.tbl_logs, row_height=44)
        self.tbl_logs.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_logs.horizontalHeader().setSectionResizeMode(9, QHeaderView.Stretch)
        self.tbl_logs.setColumnWidth(0, 75)
        self.tbl_logs.setColumnWidth(1, 120)
        self.tbl_logs.setColumnWidth(2, 100)
        self.tbl_logs.setColumnWidth(3, 130)
        self.tbl_logs.setColumnWidth(4, 130)
        self.tbl_logs.setColumnWidth(5, 120)
        self.tbl_logs.setColumnWidth(6, 110)
        self.tbl_logs.setColumnWidth(7, 175)
        self.tbl_logs.setColumnWidth(8, 100)
        top_layout.addWidget(self.tbl_logs)

        panel_top = CollapsiblePanel("Real-Time LAN Progress Submissions", top_content, horizontal=False)
        self.main_splitter.addWidget(panel_top)

        # Bottom Panel: Priority Notification Dispatcher & Responses
        bottom_splitter = QSplitter(Qt.Horizontal)

        # Dispatch form
        d_content = QWidget()
        d_layout = QVBoxLayout(d_content)
        d_layout.addWidget(QLabel("Target Employee (Head):", objectName="FieldLabel"))
        self.cmb_target_emp = QComboBox()
        d_layout.addWidget(self.cmb_target_emp)

        d_layout.addWidget(QLabel("Urgent Instruction / Message:", objectName="FieldLabel"))
        self.txt_message = QLineEdit()
        self.txt_message.setPlaceholderText("e.g. Stop task immediately and review PRJ-01 specs.")
        d_layout.addWidget(self.txt_message)

        btn_send = QPushButton("Send Blocking Priority Modal Alert")
        btn_send.setObjectName("DangerButton")
        btn_send.setMinimumHeight(38)
        btn_send.clicked.connect(self.on_send_priority_alert)
        d_layout.addWidget(btn_send)
        d_layout.addStretch()

        panel_d = CollapsiblePanel("Dispatch Priority Alert Modal", d_content, horizontal=True)
        bottom_splitter.addWidget(panel_d)

        # Response tracking
        r_content = QWidget()
        r_layout = QVBoxLayout(r_content)
        r_layout.setContentsMargins(6, 6, 6, 6)
        self.tbl_responses = QTableWidget(0, 5)
        self.tbl_responses.setHorizontalHeaderLabels([
            "Notif ID", "Target Employee", "Message", "Status", "Responded At"
        ])
        setup_modern_table(self.tbl_responses, row_height=44)
        self.tbl_responses.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_responses.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_responses.setColumnWidth(0, 85)
        self.tbl_responses.setColumnWidth(1, 130)
        self.tbl_responses.setColumnWidth(3, 95)
        self.tbl_responses.setColumnWidth(4, 140)
        r_layout.addWidget(self.tbl_responses)

        panel_r = CollapsiblePanel("Priority Alert Response Tracker", r_content, horizontal=True)
        bottom_splitter.addWidget(panel_r)
        bottom_splitter.setSizes([380, 620])

        self.main_splitter.addWidget(bottom_splitter)
        self.main_splitter.setSizes([420, 280])

        main_layout.addWidget(self.main_splitter)

        # Network bindings
        self.net_client.log_event_received.connect(self.on_live_log_event)
        self.net_client.notification_response_received.connect(self.on_live_notif_response)
        self.net_client.data_changed.connect(lambda scopes: "users" in scopes and self.reload_all_data())
        self.net_client.connection_status_changed.connect(lambda ok, _msg: ok and self.reload_all_data())

        self.reload_all_data()

    def reload_all_data(self):
        if not self.net_client.is_connected:
            return
        self.net_client.call("GET_USERS", {"role": "HEAD"}, self._on_users, self.on_request_error)
        self.net_client.call("GET_RECENT_LOGS", {"limit": 200},
                             lambda r: self.populate_logs_table(r.get("logs", [])), self.on_request_error)
        self.net_client.call("GET_NOTIFICATIONS", {"limit": 200},
                             lambda r: self.populate_responses_table(r.get("notifications", [])), self.on_request_error)

    def on_request_error(self, exc):
        self.toast.show_message(describe_error(exc), is_error=True)

    def _on_users(self, r):
        self.users_data = r.get("users", [])
        current = self.cmb_target_emp.currentData()
        self.cmb_target_emp.clear()
        for u in self.users_data:
            d_str = f" [{u.get('discipline_id')}]" if u.get("discipline_id") else ""
            self.cmb_target_emp.addItem(f"{u.get('full_name') or u['user_id']} ({u['user_id']}){d_str}", u["user_id"])
        idx = self.cmb_target_emp.findData(current)
        if idx >= 0:
            self.cmb_target_emp.setCurrentIndex(idx)

    def populate_logs_table(self, logs: list):
        self.tbl_logs.setRowCount(0)
        for r_idx, l in enumerate(logs):
            self.insert_log_row(r_idx, l)

    def insert_log_row(self, r_idx: int, l: dict):
        self.tbl_logs.insertRow(r_idx)
        self.tbl_logs.setItem(r_idx, 0, create_table_item(l["log_id"], Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 1, create_table_item(l.get("employee_name") or l["employee_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 2, create_table_item(l.get("discipline_id") or l.get("task_discipline_id") or "Unassigned", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 3, create_table_item(l.get("project_name") or l["project_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 4, create_table_item(l.get("task_name") or l["task_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 5, create_table_item(l.get("assigned_to") or "", Qt.AlignLeft | Qt.AlignVCenter))

        entry_type = l.get("entry_type") or "NEW"
        rev_num = l.get("revision_number") or 0
        ctx_str = f"Revision (R{rev_num})" if entry_type == "REVISION" else entry_type
        ctx_item = create_table_item(ctx_str, Qt.AlignCenter)
        if entry_type == "REVISION":
            ctx_item.setForeground(Qt.yellow)
        self.tbl_logs.setItem(r_idx, 6, ctx_item)

        self.tbl_logs.setItem(r_idx, 7, create_table_item(f"{l['start_date']} to {l['end_date']}", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 8, create_table_item(l.get("progress_stage") or "", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 9, create_table_item(l.get("notes") or "", Qt.AlignLeft | Qt.AlignVCenter))

    def on_live_log_event(self, data: dict):
        log = data.get("log", {})
        self.insert_log_row(0, log)
        self.toast.show_message(f"Live log submitted by {log.get('employee_id')}.")

    def populate_responses_table(self, notifications: list):
        self.tbl_responses.setRowCount(0)
        for n in notifications:
            self._upsert_response_row(n)

    def _upsert_response_row(self, notif: dict):
        """Insert or update the tracker row for one alert (keyed by notification ID)."""
        n_id = notif.get("notification_id", "")
        row = next((r for r in range(self.tbl_responses.rowCount())
                    if self.tbl_responses.item(r, 0) and self.tbl_responses.item(r, 0).text() == n_id), None)
        if row is None:
            row = self.tbl_responses.rowCount()
            self.tbl_responses.insertRow(row)
            self.tbl_responses.setItem(row, 0, create_table_item(n_id, Qt.AlignCenter))
        emp = notif.get("target_employee_id") or ""
        name = notif.get("target_name")
        if notif.get("message") is not None:
            self.tbl_responses.setItem(row, 2, create_table_item(notif.get("message", ""), Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_responses.setItem(row, 1, create_table_item(f"{name} ({emp})" if name else emp, Qt.AlignLeft | Qt.AlignVCenter))
        st = notif.get("status") or "PENDING"
        st_item = create_table_item(st, Qt.AlignCenter)
        st_item.setForeground(Qt.green if st == "ACCEPTED" else (Qt.red if st == "DENIED" else Qt.yellow))
        self.tbl_responses.setItem(row, 3, st_item)
        self.tbl_responses.setItem(row, 4, create_table_item(notif.get("responded_at") or "", Qt.AlignCenter))

    def on_live_notif_response(self, data: dict):
        notif = data.get("notification", {})
        st = notif.get("status")
        emp = notif.get("target_employee_id")
        self.toast.show_message(f"Head '{emp}' responded: {st}", is_warning=(st == "DENIED"))
        self._upsert_response_row(notif)

    def on_send_priority_alert(self):
        target_emp = self.cmb_target_emp.currentData()
        msg = self.txt_message.text().strip()
        if not target_emp or not msg:
            QMessageBox.warning(self, "Error", "Target employee and message are required.")
            return

        def sent(reply):
            self.txt_message.clear()
            self._upsert_response_row(reply.get("notification", {}))
            if reply.get("delivered"):
                self.toast.show_message(f"Priority alert delivered to '{target_emp}'.")
            else:
                self.toast.show_message(f"'{target_emp}' is not online right now; the alert will appear when they log in.",
                                        is_warning=True, duration_ms=6000)

        self.net_client.call("COO_NOTIFY", {
            "notification_id": f"NOTIF-{uuid.uuid4().hex.upper()}",
            "target_employee_id": target_emp,
            "message": msg
        }, sent, lambda e: QMessageBox.critical(self, "Alert Not Sent", describe_error(e)))

    def on_export_excel(self):
        self.btn_export.setEnabled(False)
        self.toast.show_message("Generating the Excel report on the Central Server...", duration_ms=10000)
        run_async(self.net_client.export_excel({}), self._on_export_ready, self._on_export_failed)

    def _on_export_failed(self, exc):
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "Export Error", describe_error(exc))

    def _on_export_ready(self, result):
        from app.ui.admin_workspace import save_excel_report
        self.btn_export.setEnabled(True)
        raw_bytes, default_name = result
        save_excel_report(self, raw_bytes, default_name)

    def restore_layout(self):
        h = max(self.height(), 750)
        restore_splitter(self.main_splitter, app_settings("CooWorkspace"),
                         f"{self.user['user_id']}/coo_main_splitter", [int(h * 0.618), int(h * 0.382)])

    def save_layout(self):
        app_settings("CooWorkspace").setValue(f"{self.user['user_id']}/coo_main_splitter", self.main_splitter.sizes())


class CooWorkspace(RoleWindow):
    def __init__(self, user_dict: dict, net_client: NetworkClient):
        name = user_dict.get("full_name") or user_dict["user_id"]
        super().__init__(f"COO Oversight Workspace - {name}", f"COO Executive Oversight Dashboard - {name}",
                         CooPanel(user_dict, net_client))
