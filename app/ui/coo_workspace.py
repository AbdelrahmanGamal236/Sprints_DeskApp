import base64
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QSplitter
)
from app.network.client import NetworkClient
from app.ui.components import (
    ToastNotifier, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_item
)

class CooWorkspace(QMainWindow):
    """COO Live Monitoring & Priority Dispatch Workspace with Resizable Splitters (A5, A6, B2)."""
    def __init__(self, user_dict: dict, db_manager, net_client: NetworkClient):
        super().__init__()
        self.user = user_dict
        self.db = db_manager
        self.net_client = net_client
        self.logout_requested = False

        self.users_data = []

        self.setWindowTitle(f"COO Oversight Workspace - {self.user.get('full_name') or self.user['user_id']}")
        self.setMinimumSize(1050, 750)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Top Bar
        top_bar = QHBoxLayout()
        header = QLabel(f"COO Executive Oversight Dashboard - {self.user.get('full_name') or self.user['user_id']}", self)
        header.setObjectName("HeaderTitle")
        top_bar.addWidget(header)
        top_bar.addStretch()

        btn_export = QPushButton("Export Categorized Report", self)
        btn_export.clicked.connect(self.on_export_excel)
        top_bar.addWidget(btn_export)

        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)
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
        main_layout.addWidget(CopyrightFooter(self))

        # Network bindings
        self.net_client.log_event_received.connect(self.on_live_log_event)
        self.net_client.notification_response_received.connect(self.on_live_notif_response)
        self.net_client.global_refresh_received.connect(self.reload_all_data)
        self.net_client.response_received.connect(self.on_server_response)

        self.reload_all_data()

    def reload_all_data(self):
        self.net_client.send_action("GET_USERS", {"role": "HEAD"})
        self.net_client.send_action("GET_RECENT_LOGS", {})

    def on_server_response(self, resp_type: str, data: dict):
        if resp_type == "USERS_RESPONSE":
            self.users_data = data.get("users", [])
            self.cmb_target_emp.clear()
            for u in self.users_data:
                d_str = f" [{u.get('discipline_id')}]" if u.get("discipline_id") else ""
                self.cmb_target_emp.addItem(f"{u.get('full_name') or u['user_id']} ({u['user_id']}){d_str}", u["user_id"])
        elif resp_type == "RECENT_LOGS_RESPONSE":
            self.populate_logs_table(data.get("logs", []))
        elif resp_type == "EXPORT_EXCEL_RESPONSE":
            self.handle_export_response(data)

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

        self.tbl_logs.setItem(r_idx, 7, create_table_item(f"{l['start_date']} ➔ {l['end_date']}", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 8, create_table_item(l.get("progress_stage") or "", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 9, create_table_item(l.get("notes") or "", Qt.AlignLeft | Qt.AlignVCenter))

    def on_live_log_event(self, data: dict):
        log = data.get("log", {})
        self.insert_log_row(0, log)
        self.toast.show_message(f"Live log submitted by {log.get('employee_id')}.")

    def on_live_notif_response(self, data: dict):
        notif = data.get("notification", {})
        st = notif.get("status")
        emp = notif.get("target_employee_id")
        self.toast.show_message(f"Employee '{emp}' responded: {st}", is_warning=(st == "DENIED"))

        # Add to table
        row = self.tbl_responses.rowCount()
        self.tbl_responses.insertRow(row)
        self.tbl_responses.setItem(row, 0, create_table_item(notif.get("notification_id", ""), Qt.AlignCenter))
        self.tbl_responses.setItem(row, 1, create_table_item(emp or "", Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_responses.setItem(row, 2, create_table_item(notif.get("message", ""), Qt.AlignLeft | Qt.AlignVCenter))
        st_item = create_table_item(st or "", Qt.AlignCenter)
        st_item.setForeground(Qt.green if st == "ACCEPTED" else Qt.red)
        self.tbl_responses.setItem(row, 3, st_item)
        self.tbl_responses.setItem(row, 4, create_table_item(notif.get("responded_at", ""), Qt.AlignCenter))

    def on_send_priority_alert(self):
        target_emp = self.cmb_target_emp.currentData()
        msg = self.txt_message.text().strip()
        if not target_emp or not msg:
            QMessageBox.warning(self, "Error", "Target employee and message are required.")
            return

        self.net_client.send_action("COO_NOTIFY", {
            "coo_id": self.user["user_id"],
            "target_employee_id": target_emp,
            "message": msg
        })
        self.txt_message.clear()
        self.toast.show_message(f"Priority alert dispatched to '{target_emp}'.")

    def on_export_excel(self):
        self.net_client.send_action("EXPORT_EXCEL_REQUEST", {})
        self.toast.show_message("Generating comprehensive Excel report on Central Server...")

    def handle_export_response(self, data: dict):
        if not data.get("success"):
            QMessageBox.critical(self, "Export Error", data.get("error", "Failed to generate report."))
            return
        b64 = data.get("data_b64")
        if not b64:
            return
        raw = base64.b64decode(b64)
        file_path, _ = QFileDialog.getSaveFileName(self, "Save COO Report", "COO_Full_Progress_Report.xlsx", "Excel Files (*.xlsx)")
        if file_path:
            with open(file_path, "wb") as f:
                f.write(raw)
            QMessageBox.information(self, "Success", f"Report saved successfully to:\n{file_path}")

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()

    def showEvent(self, event):
        super().showEvent(event)
        h = max(self.height(), 750)
        top_h = int(h * 0.618)
        bottom_h = int(h * 0.382)
        settings = QSettings("SprintsDeskApp", "CooWorkspace")
        saved_sizes = settings.value("coo_main_splitter")
        if saved_sizes and hasattr(self, "main_splitter"):
            try:
                self.main_splitter.setSizes([int(x) for x in saved_sizes])
            except Exception:
                self.main_splitter.setSizes([top_h, bottom_h])
        elif hasattr(self, "main_splitter"):
            self.main_splitter.setSizes([top_h, bottom_h])

    def closeEvent(self, event):
        settings = QSettings("SprintsDeskApp", "CooWorkspace")
        if hasattr(self, "main_splitter"):
            settings.setValue("coo_main_splitter", self.main_splitter.sizes())
        super().closeEvent(event)

