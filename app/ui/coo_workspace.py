import uuid
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QSplitter, QDateEdit
)
from app.core.settings import app_settings
from app.network.client import NetworkClient
from app.ui.components import (
    ToastNotifier, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_item, describe_error, RoleWindow, restore_splitter, BusyButton
)

class CooPanel(QWidget):
    """COO live feed, priority alerts and export. Shown in CooWorkspace and in the Super Admin console."""
    def __init__(self, user_dict: dict, net_client: NetworkClient, parent=None):
        super().__init__(parent)
        self.user = user_dict
        self.net_client = net_client

        self.users_data = []
        self.LOG_LIMIT = 500

        central_widget = self
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.btn_export = QPushButton("Excel Report...", self)
        self.btn_export.clicked.connect(self.on_export_excel)
        top_bar.addWidget(self.btn_export)
        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)

        # Vertical Splitter: Top (Live Feed), Bottom (Priority Alert & Responses)
        self.main_splitter = QSplitter(Qt.Vertical, central_widget)

        # Top Panel: Real-Time Submissions Feed (with Assigned To column - A5)
        top_content = QWidget()
        top_layout = QVBoxLayout(top_content)
        top_layout.setContentsMargins(6, 6, 6, 6)
        top_layout.addLayout(self._build_log_filters())

        self.tbl_logs = QTableWidget(0, 10)
        self.tbl_logs.setHorizontalHeaderLabels([
            "Submitted", "Head", "Discipline", "Project", "Task", "Assigned To", "Entry", "Task Dates", "Status", "Notes"
        ])
        setup_modern_table(self.tbl_logs, row_height=44)
        self.tbl_logs.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_logs.horizontalHeader().setSectionResizeMode(9, QHeaderView.Stretch)
        self.tbl_logs.setColumnWidth(0, 140)
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
        self.net_client.data_changed.connect(
            lambda scopes: bool(set(scopes) & {"projects", "disciplines"}) and self.reload_filter_lists())
        self.net_client.connection_status_changed.connect(lambda ok, _msg: ok and self.reload_all_data())

        self.reload_all_data()

    # ------------------------------------------------------------------ log filters
    PERIODS = ("All time", "Today", "Last 7 days", "This month", "Custom range")

    def _build_log_filters(self) -> QHBoxLayout:
        """Project / department / Head / period filters for the log feed; filtering happens on the server."""
        row = QHBoxLayout()
        row.setSpacing(8)

        def combo(label, min_w):
            row.addWidget(QLabel(label, objectName="FieldLabel"))
            cmb = QComboBox(self)
            cmb.setMinimumWidth(min_w)
            row.addWidget(cmb)
            return cmb

        self.cmb_log_project = combo("Project:", 170)
        self.cmb_log_discipline = combo("Department:", 150)
        self.cmb_log_head = combo("Head:", 150)
        self.cmb_log_period = combo("Period:", 120)
        self.cmb_log_period.addItems(self.PERIODS)
        self.dt_log_from = QDateEdit(QDate.currentDate().addDays(-6), self)
        self.dt_log_to = QDateEdit(QDate.currentDate(), self)
        for dt in (self.dt_log_from, self.dt_log_to):
            dt.setCalendarPopup(True)
            dt.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(self.dt_log_from)
        row.addWidget(QLabel("to", self))
        row.addWidget(self.dt_log_to)
        btn_reset = QPushButton("Reset", self)
        btn_reset.clicked.connect(self.reset_log_filters)
        row.addWidget(btn_reset)
        row.addStretch()
        self.lbl_log_count = QLabel("", self)
        self.lbl_log_count.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        row.addWidget(self.lbl_log_count)
        for cmb in (self.cmb_log_project, self.cmb_log_head, self.cmb_log_period):
            cmb.currentIndexChanged.connect(self._on_filter_changed)
        self.cmb_log_discipline.currentIndexChanged.connect(self._on_discipline_filter_changed)
        self.dt_log_from.dateChanged.connect(self._on_filter_changed)
        self.dt_log_to.dateChanged.connect(self._on_filter_changed)

        # Live logs arrive in bursts; reload the filtered feed once per burst
        self._reload_logs_timer = QTimer(self)
        self._reload_logs_timer.setSingleShot(True)
        self._reload_logs_timer.setInterval(300)
        self._reload_logs_timer.timeout.connect(self.reload_logs)
        self._update_date_edits()
        return row

    def _update_date_edits(self):
        custom = self.cmb_log_period.currentText() == "Custom range"
        self.dt_log_from.setEnabled(custom)
        self.dt_log_to.setEnabled(custom)

    def _on_discipline_filter_changed(self, *_):
        self._fill_head_filter()
        self._on_filter_changed()

    def _on_filter_changed(self, *_):
        self._update_date_edits()
        self.reload_logs()

    def reset_log_filters(self):
        for cmb in (self.cmb_log_project, self.cmb_log_discipline, self.cmb_log_head, self.cmb_log_period):
            cmb.blockSignals(True)
            cmb.setCurrentIndex(0)
            cmb.blockSignals(False)
        self._fill_head_filter()
        self._on_filter_changed()

    def period_range(self) -> tuple:
        """(start, end) as YYYY-MM-DD for the chosen period, or (None, None) for all time."""
        today = QDate.currentDate()
        period = self.cmb_log_period.currentText()
        if period == "Today":
            start, end = today, today
        elif period == "Last 7 days":
            start, end = today.addDays(-6), today
        elif period == "This month":
            start, end = QDate(today.year(), today.month(), 1), today
        elif period == "Custom range":
            start, end = self.dt_log_from.date(), self.dt_log_to.date()
        else:
            return None, None
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

    def log_filters(self) -> dict:
        start, end = self.period_range()
        filters = {"limit": self.LOG_LIMIT, "project_id": self.cmb_log_project.currentData(),
                   "discipline_id": self.cmb_log_discipline.currentData(),
                   "employee_id": self.cmb_log_head.currentData(), "start_date": start, "end_date": end}
        return {k: v for k, v in filters.items() if v is not None}

    @staticmethod
    def _refill(cmb: QComboBox, all_label: str, items: list):
        current = cmb.currentData()
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(all_label, None)
        for label, value in items:
            cmb.addItem(label, value)
        idx = cmb.findData(current)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)
        cmb.blockSignals(False)

    def _fill_head_filter(self):
        disc = self.cmb_log_discipline.currentData()
        self._refill(self.cmb_log_head, "All Heads",
                     [(f"{u.get('full_name') or u['user_id']} ({u['user_id']})", u["user_id"])
                      for u in self.users_data if not disc or u.get("discipline_id") == disc])

    def reload_filter_lists(self):
        if not self.net_client.is_connected:
            return
        self.net_client.call("GET_PROJECTS", {"include_hidden": True}, lambda r: self._refill(
            self.cmb_log_project, "All Projects",
            [(f"{p['name']} ({p['project_id']})", p["project_id"]) for p in r.get("projects", [])]),
            self.on_request_error)
        self.net_client.call("GET_DISCIPLINES", {"include_hidden": True}, lambda r: self._refill(
            self.cmb_log_discipline, "All Departments",
            [(f"{d['name']} ({d['discipline_id']})", d["discipline_id"]) for d in r.get("disciplines", [])]),
            self.on_request_error)

    def reload_logs(self):
        if not self.net_client.is_connected:
            return
        if self.cmb_log_period.currentText() == "Custom range" and self.dt_log_from.date() > self.dt_log_to.date():
            self.lbl_log_count.setText("The 'from' date is after the 'to' date.")
            return

        def shown(r):
            logs = r.get("logs", [])
            self.populate_logs_table(logs)
            more = f" (newest {len(logs)} shown; narrow the filters to see older ones)" if r.get("truncated") else ""
            self.lbl_log_count.setText(f"{len(logs)} logs{more}")
        self.net_client.call("GET_RECENT_LOGS", self.log_filters(), shown, self.on_request_error)

    def reload_all_data(self):
        if not self.net_client.is_connected:
            return
        self.net_client.call("GET_USERS", {"role": "HEAD"}, self._on_users, self.on_request_error)
        self.reload_filter_lists()
        self.reload_logs()
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
        self._fill_head_filter()

    def populate_logs_table(self, logs: list):
        self.tbl_logs.setRowCount(0)
        for r_idx, l in enumerate(logs):
            self.insert_log_row(r_idx, l)

    def insert_log_row(self, r_idx: int, l: dict):
        self.tbl_logs.insertRow(r_idx)
        self.tbl_logs.setItem(r_idx, 0, create_table_item(l.get("submitted_at") or "", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 1, create_table_item(l.get("employee_name") or l["employee_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 2, create_table_item(l.get("task_discipline_name") or l.get("task_discipline_id")
                                                          or l.get("discipline_id") or "Unassigned", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 3, create_table_item(l.get("project_name") or l["project_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 4, create_table_item(l.get("task_name") or l["task_id"], Qt.AlignLeft | Qt.AlignVCenter))
        self.tbl_logs.setItem(r_idx, 5, create_table_item(l.get("assigned_to") or "", Qt.AlignLeft | Qt.AlignVCenter))

        entry_type = l.get("entry_type") or "NEW"
        rev_num = l.get("revision_number") or 0
        ctx_str = f"Revision (R{rev_num})" if entry_type == "REVISION" else {"NEW": "New", "CONTINUATION": "Continuation"}.get(entry_type, entry_type)
        ctx_item = create_table_item(ctx_str, Qt.AlignCenter)
        if entry_type == "REVISION":
            ctx_item.setForeground(Qt.yellow)
        self.tbl_logs.setItem(r_idx, 6, ctx_item)

        self.tbl_logs.setItem(r_idx, 7, create_table_item(f"{l['start_date']} to {l['end_date']}", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 8, create_table_item(l.get("progress_stage") or "", Qt.AlignCenter))
        self.tbl_logs.setItem(r_idx, 9, create_table_item(l.get("notes") or "", Qt.AlignLeft | Qt.AlignVCenter))

    def on_live_log_event(self, data: dict):
        log = data.get("log", {})
        # Reload through the server so the new log appears only if it matches the current filters
        self._reload_logs_timer.start()
        self.toast.show_message(f"Live log submitted by {log.get('employee_name') or log.get('employee_id')}.")

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

        busy = BusyButton(self.sender())

        def sent(reply):
            busy()
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
        }, sent, lambda e: (busy(), QMessageBox.critical(self, "Alert Not Sent", describe_error(e))))

    def on_export_excel(self):
        from app.ui.export_panel import ExportDialog
        ExportDialog(self.net_client, self).exec()

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
