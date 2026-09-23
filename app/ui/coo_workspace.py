from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QSplitter
)
from app.database.db_manager import DBManager
from app.network.client import NetworkClient
from app.services.excel_service import ExcelExportService
from app.ui.components import ToastNotifier, CopyrightFooter

class CooWorkspace(QMainWindow):
    """COO Live Monitoring & Priority Dispatch Workspace."""
    def __init__(self, user_dict: dict, db_manager: DBManager, net_client: NetworkClient):
        super().__init__()
        self.user = user_dict
        self.db = db_manager
        self.net_client = net_client
        self.excel_service = ExcelExportService(self.db)
        self.logout_requested = False

        self.setWindowTitle(f"COO Oversight Workspace - {self.user['user_id']}")
        self.setMinimumSize(1000, 720)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top Bar
        top_bar = QHBoxLayout()
        header = QLabel("COO Executive Oversight Dashboard", self)
        header.setObjectName("HeaderTitle")
        top_bar.addWidget(header)
        top_bar.addStretch()

        btn_export_all = QPushButton("Export All to Excel", self)
        btn_export_all.clicked.connect(self.on_export_excel)
        top_bar.addWidget(btn_export_all)

        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)

        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Splitter: Top (Live Logs Feed), Bottom (Priority Notification Dispatcher & Responses)
        splitter = QSplitter(Qt.Vertical, central_widget)

        # Top Section: Real-time Progress Log Monitor
        log_card = QFrame(splitter)
        log_card.setObjectName("CardFrame")
        log_layout = QVBoxLayout(log_card)
        log_layout.addWidget(QLabel("Real-Time LAN Progress Submissions", objectName="SubTitle"))

        self.tbl_logs = QTableWidget(0, 9)
        self.tbl_logs.setHorizontalHeaderLabels([
            "Log ID", "Employee", "Project", "Task", "Entry Context", "Dates", "Task Status", "Notes", "Submitted At"
        ])
        self.tbl_logs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        log_layout.addWidget(self.tbl_logs)
        splitter.addWidget(log_card)

        # Bottom Section: Priority Notification Panel
        notif_card = QFrame(splitter)
        notif_card.setObjectName("CardFrame")
        notif_layout = QHBoxLayout(notif_card)

        # Left: Dispatch Form
        dispatch_box = QWidget()
        d_layout = QVBoxLayout(dispatch_box)
        d_layout.addWidget(QLabel("Dispatch Priority Alert Modal", objectName="SubTitle"))

        d_layout.addWidget(QLabel("Select Target Employee (Head):", objectName="FieldLabel"))
        self.cmb_target_emp = QComboBox()
        d_layout.addWidget(self.cmb_target_emp)

        d_layout.addWidget(QLabel("Urgent Message / Instruction:", objectName="FieldLabel"))
        self.txt_message = QLineEdit()
        self.txt_message.setPlaceholderText("e.g. Stop current task and review PRJ-01 specs immediately.")
        d_layout.addWidget(self.txt_message)

        btn_send = QPushButton("Send Blocking Center Modal Alert")
        btn_send.setObjectName("DangerButton")
        btn_send.setMinimumHeight(38)
        btn_send.clicked.connect(self.on_send_priority_alert)
        d_layout.addWidget(btn_send)
        d_layout.addStretch()

        # Right: Response Status Table
        response_box = QWidget()
        r_layout = QVBoxLayout(response_box)
        r_layout.addWidget(QLabel("Priority Alerts Response Tracker", objectName="SubTitle"))

        self.tbl_responses = QTableWidget(0, 5)
        self.tbl_responses.setHorizontalHeaderLabels([
            "Notif ID", "Target Employee", "Message", "Status", "Responded At"
        ])
        self.tbl_responses.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        r_layout.addWidget(self.tbl_responses)

        notif_layout.addWidget(dispatch_box, 1)
        notif_layout.addWidget(response_box, 2)
        splitter.addWidget(notif_card)

        splitter.setSizes([380, 300])
        main_layout.addWidget(splitter)
        main_layout.addWidget(CopyrightFooter(self))

        # Bind Network Signals for live push updates
        self.net_client.log_event_received.connect(self.on_live_log_event)
        self.net_client.notification_response_received.connect(self.on_live_notif_response)
        self.net_client.global_refresh_received.connect(self.reload_all_data)

        self.reload_all_data()

    def reload_all_data(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Load employees into combo
            cursor.execute("SELECT user_id FROM users WHERE role = 'HEAD'")
            employees = cursor.fetchall()
            self.cmb_target_emp.clear()
            for emp in employees:
                self.cmb_target_emp.addItem(f"Employee {emp['user_id']}", emp["user_id"])

            # Load Logs
            cursor.execute("""
            SELECT l.*, p.name AS project_name, t.name AS task_name 
            FROM progress_logs l
            LEFT JOIN projects p ON l.project_id = p.project_id
            LEFT JOIN tasks t ON l.task_id = t.task_id
            ORDER BY l.submitted_at DESC
            """)
            logs = cursor.fetchall()
            self.tbl_logs.setRowCount(0)
            for r_idx, l in enumerate(logs):
                self.tbl_logs.insertRow(r_idx)
                self.tbl_logs.setItem(r_idx, 0, QTableWidgetItem(l["log_id"]))
                self.tbl_logs.setItem(r_idx, 1, QTableWidgetItem(l["employee_id"]))
                self.tbl_logs.setItem(r_idx, 2, QTableWidgetItem(l["project_name"] or l["project_id"]))
                self.tbl_logs.setItem(r_idx, 3, QTableWidgetItem(l["task_name"] or l["task_id"]))

                entry_type = l["entry_type"] if ("entry_type" in l.keys() and l["entry_type"]) else "NEW"
                rev_num = l["revision_number"] if ("revision_number" in l.keys() and l["revision_number"]) else 0

                if entry_type == "REVISION":
                    ctx_item = QTableWidgetItem(f"Revision (R{rev_num})")
                    ctx_item.setForeground(Qt.yellow)
                elif entry_type == "CONTINUATION":
                    ctx_item = QTableWidgetItem("Continuation")
                else:
                    ctx_item = QTableWidgetItem("New Task")

                self.tbl_logs.setItem(r_idx, 4, ctx_item)
                self.tbl_logs.setItem(r_idx, 5, QTableWidgetItem(f"{l['start_date']} -> {l['end_date']}"))
                self.tbl_logs.setItem(r_idx, 6, QTableWidgetItem(l['progress_stage']))
                self.tbl_logs.setItem(r_idx, 7, QTableWidgetItem(l["notes"] or ""))
                self.tbl_logs.setItem(r_idx, 8, QTableWidgetItem(l["submitted_at"]))

            # Load Notifications
            cursor.execute("SELECT * FROM priority_notifications ORDER BY created_at DESC")
            notifs = cursor.fetchall()
            self.tbl_responses.setRowCount(0)
            for r_idx, n in enumerate(notifs):
                self.tbl_responses.insertRow(r_idx)
                self.tbl_responses.setItem(r_idx, 0, QTableWidgetItem(n["notification_id"]))
                self.tbl_responses.setItem(r_idx, 1, QTableWidgetItem(n["target_employee_id"]))
                self.tbl_responses.setItem(r_idx, 2, QTableWidgetItem(n["message"]))
                
                status_item = QTableWidgetItem(n["status"])
                if n["status"] == "ACCEPTED":
                    status_item.setForeground(Qt.green)
                elif n["status"] == "DENIED":
                    status_item.setForeground(Qt.red)
                self.tbl_responses.setItem(r_idx, 3, status_item)
                self.tbl_responses.setItem(r_idx, 4, QTableWidgetItem(n["responded_at"] or "Pending..."))

    def on_send_priority_alert(self):
        target_emp = self.cmb_target_emp.currentData()
        msg = self.txt_message.text().strip()

        if not target_emp or not msg:
            QMessageBox.warning(self, "Error", "Target employee and message are required.")
            return

        payload = {
            "coo_id": self.user["user_id"],
            "target_employee_id": target_emp,
            "message": msg
        }
        self.net_client.send_action("COO_NOTIFY", payload)

        self.txt_message.clear()
        self.toast.show_message(f"Priority alert dispatched to Employee '{target_emp}'.")
        self.reload_all_data()

    def on_live_log_event(self, data: dict):
        """Called live when Head submits a log over LAN."""
        self.toast.show_message("Live push update: New progress log submitted!")
        self.reload_all_data()

    def on_live_notif_response(self, data: dict):
        """Called live when Head responds to priority modal."""
        emp = data.get("target_employee_id")
        st = data.get("status")
        self.toast.show_message(f"Live response from '{emp}': {st}", is_warning=(st == "DENIED"))
        self.reload_all_data()

    def on_export_excel(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save COO Audit Excel Report", "COO_Full_Progress_Report.xlsx", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return
        try:
            saved_path = self.excel_service.export_logs_to_excel(file_path)
            QMessageBox.information(self, "Export Success", f"Report saved to:\n{saved_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()
