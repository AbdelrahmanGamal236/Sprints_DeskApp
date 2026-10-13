from datetime import datetime
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDateEdit, QTextEdit, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QRadioButton, QButtonGroup, QMessageBox, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QCompleter
)
from app.core.settings import app_settings
from app.core.config import PROGRESS_STAGES, ENTRY_TYPE_NEW, ENTRY_TYPE_CONTINUATION, ENTRY_TYPE_REVISION
from app.network.client import NetworkClient
from app.services.sync_service import SyncService
from app.ui.components import (
    ToastNotifier, SyncStatusBadge, BlockingCenterModal, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_item, create_table_action_cell, describe_error, ConnectionBanner
)
from app.ui.timeline_widget import ProjectProgressiveTimelineWidget

class TaskProposalDialog(QDialog):
    """Modal dialog for Head to propose a new task automatically tagged with Head's discipline (A1)."""
    def __init__(self, parent, projects: list, head_discipline_id: str, net_client: NetworkClient):
        super().__init__(parent)
        self.projects = projects
        self.head_discipline_id = head_discipline_id
        self.net_client = net_client
        self.setWindowTitle("Request New Task for Project")
        self.setFixedSize(520, 380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Propose New Task", self)
        title.setObjectName("SubTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("Select Project:", self, objectName="FieldLabel"))
        self.cmb_proj = QComboBox(self)
        for p in self.projects:
            self.cmb_proj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
        layout.addWidget(self.cmb_proj)

        layout.addWidget(QLabel("Proposed Task Name:", self, objectName="FieldLabel"))
        self.txt_task_name = QLineEdit(self)
        self.txt_task_name.setPlaceholderText("e.g. Electrical Conduit Routing - Zone B")
        layout.addWidget(self.txt_task_name)

        dates_layout = QHBoxLayout()
        d1 = QVBoxLayout()
        d1.addWidget(QLabel("Planned Start Date:", self, objectName="FieldLabel"))
        self.dt_start = QDateEdit(QDate.currentDate(), self)
        self.dt_start.setCalendarPopup(True)
        d1.addWidget(self.dt_start)
        dates_layout.addLayout(d1)

        d2 = QVBoxLayout()
        d2.addWidget(QLabel("Planned End Date:", self, objectName="FieldLabel"))
        self.dt_end = QDateEdit(QDate.currentDate().addDays(7), self)
        self.dt_end.setCalendarPopup(True)
        d2.addWidget(self.dt_end)
        dates_layout.addLayout(d2)
        layout.addLayout(dates_layout)

        lbl_disc_info = QLabel(f"Discipline: {self.head_discipline_id or 'None (Contact Admin)'}", self)
        lbl_disc_info.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        layout.addWidget(lbl_disc_info)

        layout.addStretch()

        btns_layout = QHBoxLayout()
        btns_layout.addStretch()

        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btns_layout.addWidget(btn_cancel)

        btn_submit = QPushButton("Submit Proposal", self)
        btn_submit.setMinimumWidth(140)
        btn_submit.clicked.connect(self.on_submit)
        btns_layout.addWidget(btn_submit)

        layout.addLayout(btns_layout)

    def on_submit(self):
        name = self.txt_task_name.text().strip()
        p_id = self.cmb_proj.currentData()
        if not name or not p_id:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid task name and select a project.")
            return
        if self.dt_start.date() > self.dt_end.date():
            QMessageBox.warning(self, "Validation Error", "Planned start date cannot be after end date.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "project_id": self.cmb_proj.currentData(),
            "task_name": self.txt_task_name.text().strip(),
            "discipline_id": self.head_discipline_id,
            "planned_start_date": self.dt_start.date().toString("yyyy-MM-dd"),
            "planned_end_date": self.dt_end.date().toString("yyyy-MM-dd")
        }


class DateChangeRequestDialog(QDialog):
    """Dialog for Head to request a planned date change on a task (A2)."""
    def __init__(self, task_info: dict, parent=None):
        super().__init__(parent)
        self.task_info = task_info
        self.setWindowTitle(f"Request Date Change - {task_info.get('task_id')}")
        self.setFixedSize(500, 360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel(f"Request Schedule Change for: {task_info.get('name')}", self)
        title.setObjectName("SubTitle")
        layout.addWidget(title)

        curr_start = task_info.get("planned_start_date") or datetime.now().strftime("%Y-%m-%d")
        curr_end = task_info.get("planned_end_date") or datetime.now().strftime("%Y-%m-%d")

        lbl_curr = QLabel(f"Current Schedule: {curr_start} to {curr_end}", self)
        lbl_curr.setStyleSheet("color: #7C3AED; font-weight: bold;")
        layout.addWidget(lbl_curr)

        dates_row = QHBoxLayout()
        b1 = QVBoxLayout()
        b1.addWidget(QLabel("New Planned Start Date:", self, objectName="FieldLabel"))
        self.dt_new_start = QDateEdit(QDate.fromString(curr_start, "yyyy-MM-dd"), self)
        self.dt_new_start.setCalendarPopup(True)
        b1.addWidget(self.dt_new_start)
        dates_row.addLayout(b1)

        b2 = QVBoxLayout()
        b2.addWidget(QLabel("New Planned End Date:", self, objectName="FieldLabel"))
        self.dt_new_end = QDateEdit(QDate.fromString(curr_end, "yyyy-MM-dd"), self)
        self.dt_new_end.setCalendarPopup(True)
        b2.addWidget(self.dt_new_end)
        dates_row.addLayout(b2)
        layout.addLayout(dates_row)

        layout.addWidget(QLabel("Mandatory Reason for Date Change:", self, objectName="FieldLabel"))
        self.txt_reason = QTextEdit(self)
        self.txt_reason.setPlaceholderText("Explain why dates need adjustment (e.g. client scope modification, material delay)...")
        self.txt_reason.setMaximumHeight(85)
        layout.addWidget(self.txt_reason)

        layout.addStretch()

        btns_row = QHBoxLayout()
        btns_row.addStretch()

        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btns_row.addWidget(btn_cancel)

        btn_submit = QPushButton("Submit Date Change Request", self)
        btn_submit.clicked.connect(self.on_submit)
        btns_row.addWidget(btn_submit)

        layout.addLayout(btns_row)

    def on_submit(self):
        reason = self.txt_reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Validation Error", "A mandatory reason must be provided.")
            return
        if self.dt_new_start.date() > self.dt_new_end.date():
            QMessageBox.warning(self, "Validation Error", "New start date cannot be after end date.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "task_id": self.task_info["task_id"],
            "new_start_date": self.dt_new_start.date().toString("yyyy-MM-dd"),
            "new_end_date": self.dt_new_end.date().toString("yyyy-MM-dd"),
            "reason": self.txt_reason.toPlainText().strip()
        }


class FailedSubmissionsDialog(QDialog):
    """Lists items the Central Server rejected, so the Head can fix, retry or discard them."""
    ACTION_LABELS = {"SUBMIT_LOG": "Progress Log", "PROPOSE_TASK": "Task Request",
                     "REQUEST_TASK_DATE_CHANGE": "Date Change Request", "RESPOND_NOTIFICATION": "Alert Response"}

    def __init__(self, sync_service: SyncService, parent=None):
        super().__init__(parent)
        self.sync = sync_service
        self.setWindowTitle("Submissions Rejected by the Central Server")
        self.setMinimumSize(760, 360)
        layout = QVBoxLayout(self)
        info = QLabel("These items were not saved. Retry after the cause is fixed (for example after the Admin "
                      "updates the task), or discard them.", self)
        info.setWordWrap(True)
        layout.addWidget(info)
        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels(["Type", "Details", "Reason", "Actions"])
        setup_modern_table(self.tbl, row_height=44)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 140)
        self.tbl.setColumnWidth(1, 220)
        self.tbl.setColumnWidth(3, 180)
        layout.addWidget(self.tbl)
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        self.reload()

    def reload(self):
        items = self.sync.failed_items()
        self.tbl.setRowCount(0)
        for r, it in enumerate(items):
            pl = it["payload"]
            details = pl.get("task_id") or pl.get("task_name") or pl.get("notification_id") or it["item_id"]
            if pl.get("start_date"):
                details = f"{details} ({pl.get('start_date')})"
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, create_table_item(self.ACTION_LABELS.get(it["event_type"], it["event_type"])))
            self.tbl.setItem(r, 1, create_table_item(str(details), Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl.setItem(r, 2, create_table_item(it.get("last_error") or "", Qt.AlignLeft | Qt.AlignVCenter))
            b_retry = QPushButton("Retry")
            b_retry.clicked.connect(lambda _, q=it["queue_id"]: self._retry(q))
            b_discard = QPushButton("Discard")
            b_discard.setObjectName("DangerButton")
            b_discard.clicked.connect(lambda _, q=it["queue_id"]: self._discard(q))
            self.tbl.setCellWidget(r, 3, create_table_action_cell([b_retry, b_discard]))

    def _retry(self, queue_id: int):
        self.sync.retry_failed(queue_id)
        self.reload()

    def _discard(self, queue_id: int):
        if QMessageBox.question(self, "Discard Item", "Permanently discard this unsent item?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.sync.discard_failed(queue_id)
            self.reload()


class HeadWorkspace(QMainWindow):
    """Employee / Head Workstation with Discipline Task Filtering & Resizable Panels (A1, A2, A3, A5, A6)."""
    def __init__(self, user_dict: dict, net_client: NetworkClient, sync_service: SyncService):
        super().__init__()
        self.user = user_dict
        self.user_id = user_dict["user_id"]
        self.discipline_id = user_dict.get("discipline_id")
        self.net_client = net_client
        self.sync_service = sync_service
        self.logout_requested = False

        self.projects_data = []
        self.tasks_data = []
        self._open_alerts = {}          # notification_id -> modal currently shown (prevents duplicates)
        self._awaiting_ack = {}         # item_id -> description, for "saved"/"queued" toasts

        self.setWindowTitle(f"Head Workstation - {self.user.get('full_name', self.user_id)} ({self.user_id})")
        self.setMinimumSize(1000, 720)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Top Bar
        top_bar = QHBoxLayout()
        emp_name = self.user.get("full_name") or self.user_id
        disc_name = self.user.get("discipline_name") or self.discipline_id
        disc_str = f" - {disc_name}" if self.discipline_id else " - No Discipline Assigned"
        header_title = QLabel(f"Head: {emp_name} ({self.user_id}){disc_str}", self)
        header_title.setObjectName("HeaderTitle")
        top_bar.addWidget(header_title)
        top_bar.addStretch()

        self.sync_badge = SyncStatusBadge(self)
        top_bar.addWidget(self.sync_badge)

        self.btn_failed = QPushButton("Rejected Items (0)", self)
        self.btn_failed.setObjectName("DangerButton")
        self.btn_failed.clicked.connect(self.on_open_failed_items)
        self.btn_failed.setVisible(False)
        top_bar.addWidget(self.btn_failed)

        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)
        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(ConnectionBanner(
            self.net_client, "Your logs and requests are saved on this PC and sent automatically when it returns.", self))

        # Project selector on top; everything below shows the selected project
        prj_row = QHBoxLayout()
        prj_row.addWidget(QLabel("Project:", objectName="FieldLabel"))
        self.cmb_projects = QComboBox(self)
        self.cmb_projects.setMinimumWidth(320)
        self.cmb_projects.currentIndexChanged.connect(self.on_project_selected)
        prj_row.addWidget(self.cmb_projects)
        prj_row.addStretch()
        main_layout.addLayout(prj_row)

        # Tabs: Daily Progress Logging, Audit Timeline & Progressive Timeline
        self.main_tabs = QTabWidget(self)
        self.main_tabs.addTab(self.create_logging_tab(), "Daily Progress Logging")
        self.main_tabs.addTab(self.create_project_timeline_tab(), "Project Progressive Timeline")
        self.main_tabs.addTab(self.create_timeline_tab(), "Task Requests && Date Changes")
        main_layout.addWidget(self.main_tabs)

        main_layout.addWidget(CopyrightFooter(self))

        # Network bindings
        self.net_client.connection_status_changed.connect(self.on_net_status_changed)
        self.net_client.priority_alert_received.connect(self.on_priority_alert)
        self.net_client.task_proposal_event.connect(self.on_task_proposal_event)
        self.net_client.task_date_change_event.connect(self.on_task_date_change_event)
        self.net_client.data_changed.connect(self.on_data_changed)
        self.sync_service.item_synced.connect(self.on_item_synced)
        self.sync_service.item_failed.connect(self.on_item_failed)
        self.sync_service.queue_changed.connect(lambda p, f: self.update_sync_badge())

        # Load initial data from server snapshot
        self.request_refresh_from_server()
        self.restore_splitter_states()
        self.update_sync_badge()

    def create_logging_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Main resizable splitter (A6)
        self.log_splitter = QSplitter(Qt.Horizontal, widget)

        # ----------------- LEFT PANEL: PROJECTS & DISCIPLINE TASKS -----------------
        left_content = QWidget()
        left_vbox = QVBoxLayout(left_content)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(10)

        # Discipline banner if no discipline
        self.lbl_disc_warning = QLabel("Contact Admin to assign your discipline.", objectName="FieldLabel")
        self.lbl_disc_warning.setStyleSheet("color: #EF4444; font-weight: bold; padding: 4px;")
        self.lbl_disc_warning.setVisible(not bool(self.discipline_id))
        left_vbox.addWidget(self.lbl_disc_warning)

        # Discipline Tab Bar showing ONLY Head's discipline tab (A1, A3)
        self.disc_tabs = QTabWidget()
        self.lst_tasks = QListWidget()
        self.lst_tasks.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst_tasks.itemSelectionChanged.connect(self.update_revision_tag_display)
        self.lst_tasks.itemSelectionChanged.connect(self.on_task_selected)

        self.discipline_label = self.user.get("discipline_name") or self.discipline_id or "Unassigned"
        tab_title = f"{self.discipline_label} (0)"
        self.disc_tabs.addTab(self.lst_tasks, tab_title)
        left_vbox.addWidget(self.disc_tabs)

        # Action Buttons under task list
        t_actions = QHBoxLayout()
        btn_propose = QPushButton("+ Request Task")
        btn_propose.setCursor(Qt.PointingHandCursor)
        btn_propose.clicked.connect(self.on_open_task_proposal_dialog)
        t_actions.addWidget(btn_propose)

        btn_date_chg = QPushButton("Request Date Change")
        btn_date_chg.setCursor(Qt.PointingHandCursor)
        btn_date_chg.clicked.connect(self.on_open_date_change_dialog)
        t_actions.addWidget(btn_date_chg)
        left_vbox.addLayout(t_actions)

        self.panel_left = CollapsiblePanel("Project & Tasks Explorer", left_content, horizontal=True)
        self.log_splitter.addWidget(self.panel_left)

        # ----------------- RIGHT PANEL: PROGRESS FORM -----------------
        right_content = QWidget()
        right_vbox = QVBoxLayout(right_content)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(10)

        # Dates Row: the selected task's planned dates, read-only. A log never changes them; the server
        # stamps them on the log itself. They change only through an approved Request Date Change.
        dates_row = QHBoxLayout()
        self.txt_task_start = self._locked_date_field()
        self.txt_task_end = self._locked_date_field()
        for label, field in (("Task Start Date:", self.txt_task_start), ("Task End Date:", self.txt_task_end)):
            box = QVBoxLayout()
            box.addWidget(QLabel(label, objectName="FieldLabel"))
            box.addWidget(field)
            dates_row.addLayout(box)
        right_vbox.addLayout(dates_row)
        self.lbl_planned = QLabel("Dates come from the task. To change them, use Request Date Change.")
        self.lbl_planned.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        right_vbox.addWidget(self.lbl_planned)

        # Task Logging Context / Rework Tag (R1, R2...)
        right_vbox.addWidget(QLabel("Entry Type:", objectName="FieldLabel"))
        rb_layout = QHBoxLayout()
        self.rb_new = QRadioButton("New Task")
        self.rb_continuation = QRadioButton("Continuation")
        self.rb_revision = QRadioButton("Revision / Rework")
        self.rb_group = QButtonGroup(self)
        self.rb_group.addButton(self.rb_new, 1)
        self.rb_group.addButton(self.rb_continuation, 2)
        self.rb_group.addButton(self.rb_revision, 3)
        self.rb_new.setChecked(True)

        rb_layout.addWidget(self.rb_new)
        rb_layout.addWidget(self.rb_continuation)
        rb_layout.addWidget(self.rb_revision)

        self.lbl_rev_tag = QLabel("")
        self.lbl_rev_tag.setStyleSheet("font-weight: bold; color: #F59E0B; font-size: 13px; margin-left: 8px;")
        rb_layout.addWidget(self.lbl_rev_tag)
        rb_layout.addStretch()
        right_vbox.addLayout(rb_layout)
        self.lbl_entry_hint = QLabel("")
        self.lbl_entry_hint.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        right_vbox.addWidget(self.lbl_entry_hint)
        self.apply_entry_type_rules(None)
        self.rb_group.buttonToggled.connect(self.update_revision_tag_display)

        # Status & Assigned To Row (A5)
        row_status_assign = QHBoxLayout()
        box_st = QVBoxLayout()
        box_st.addWidget(QLabel("Progress Stage:", objectName="FieldLabel"))
        self.cmb_progress = QComboBox()
        for s in PROGRESS_STAGES:
            self.cmb_progress.addItem(s)
        box_st.addWidget(self.cmb_progress)
        row_status_assign.addLayout(box_st)


        box_as = QVBoxLayout()
        box_as.addWidget(QLabel("Assigned To (Team Member Name):", objectName="FieldLabel"))
        self.txt_assigned_to = QLineEdit()
        self.txt_assigned_to.setPlaceholderText("e.g. Eng. Tarek (optional, max 100 chars)")
        self.txt_assigned_to.setMaxLength(100)
        self.setup_assigned_to_autocomplete()
        box_as.addWidget(self.txt_assigned_to)
        row_status_assign.addLayout(box_as)
        right_vbox.addLayout(row_status_assign)

        # Notes Box
        right_vbox.addWidget(QLabel("Work Notes & Activity Summary:", objectName="FieldLabel"))
        self.txt_notes = QTextEdit()
        self.txt_notes.setPlaceholderText("Enter detailed daily progress notes, deliverables, or blockers...")
        right_vbox.addWidget(self.txt_notes)

        # Submit Button
        self.btn_submit = QPushButton("SUBMIT PROGRESS LOG")
        self.btn_submit.setMinimumHeight(44)
        self.btn_submit.clicked.connect(self.on_submit_log)
        right_vbox.addWidget(self.btn_submit)

        self.panel_right = CollapsiblePanel("Daily Progress Entry", right_content, horizontal=True)
        self.log_splitter.addWidget(self.panel_right)
        self.log_splitter.setSizes([380, 580])

        layout.addWidget(self.log_splitter)
        return widget

    def setup_assigned_to_autocomplete(self):
        """Remembers last entered 'Assigned To' values per Head for faster entry (A5)."""
        settings = app_settings("ClientConfig")
        recent_names = settings.value(f"assigned_to_history_{self.user_id}", [])
        if isinstance(recent_names, list) and recent_names:
            completer = QCompleter(recent_names, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.txt_assigned_to.setCompleter(completer)

    def save_assigned_to_history(self, name: str):
        if not name:
            return
        settings = app_settings("ClientConfig")
        key = f"assigned_to_history_{self.user_id}"
        recent = settings.value(key, [])
        if not isinstance(recent, list):
            recent = []
        if name in recent:
            recent.remove(name)
        recent.insert(0, name)
        recent = recent[:15] # Keep last 15
        settings.setValue(key, recent)
        completer = QCompleter(recent, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.txt_assigned_to.setCompleter(completer)

    def request_refresh_from_server(self):
        if not self.net_client.is_connected:
            return
        self.net_client.call("GET_SNAPSHOT", {}, self.on_initial_snapshot, self.on_request_error)
        self.net_client.call("GET_TASK_PROPOSALS", {},
                             lambda r: self.populate_proposals_timeline(r.get("proposals", [])), self.on_request_error)
        self.net_client.call("GET_DATE_CHANGE_REQUESTS", {},
                             lambda r: self.populate_date_change_timeline(r.get("requests", [])), self.on_request_error)

    def on_request_error(self, exc):
        self.toast.show_message(describe_error(exc), is_error=True)

    def on_data_changed(self, scopes: list):
        """Reload only what the server says changed."""
        if not self.net_client.is_connected:
            return
        scopes = set(scopes)
        if scopes & {"projects", "tasks", "disciplines", "users"}:
            self.net_client.call("GET_SNAPSHOT", {}, self.on_initial_snapshot, self.on_request_error)
        if "proposals" in scopes:
            self.net_client.call("GET_TASK_PROPOSALS", {},
                                 lambda r: self.populate_proposals_timeline(r.get("proposals", [])), self.on_request_error)
        if "date_changes" in scopes:
            self.net_client.call("GET_DATE_CHANGE_REQUESTS", {},
                                 lambda r: self.populate_date_change_timeline(r.get("requests", [])), self.on_request_error)

    def on_initial_snapshot(self, snapshot: dict):
        self.projects_data = snapshot.get("projects", [])
        self.tasks_data = snapshot.get("tasks", [])
        selected = self.cmb_projects.currentData()
        selected_task = self.lst_tasks.currentItem().data(Qt.UserRole) if self.lst_tasks.currentItem() else None
        self.populate_project_list(selected)
        if selected_task:
            for i in range(self.lst_tasks.count()):
                if self.lst_tasks.item(i).data(Qt.UserRole) == selected_task:
                    self.lst_tasks.setCurrentRow(i)
                    break

        # Handle pending priority alerts if present
        for notif in snapshot.get("pending_notifications", []):
            self.on_priority_alert({"notification": notif})

    def populate_project_list(self, keep_project_id: str = None):
        self.cmb_projects.blockSignals(True)
        self.cmb_projects.clear()
        for p in self.projects_data:
            self.cmb_projects.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
        idx = self.cmb_projects.findData(keep_project_id)
        if self.cmb_projects.count() > 0:
            self.cmb_projects.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_projects.blockSignals(False)
        self.on_project_selected()

    def create_project_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        self.proj_timeline_widget = ProjectProgressiveTimelineWidget()
        layout.addWidget(self.proj_timeline_widget)
        return widget

    def on_project_selected(self, *_):
        p_id = self.cmb_projects.currentData()
        if not p_id:
            self.lst_tasks.clear()
            self.disc_tabs.setTabText(0, f"{self.discipline_label} (0)")
            if hasattr(self, "proj_timeline_widget"):
                self.proj_timeline_widget.load_timeline_data({})
            return

        self.lst_tasks.clear()
        count = 0
        for t in self.tasks_data:
            if t.get("project_id") == p_id:
                # Dates display (A2)
                p_start = t.get("planned_start_date") or "TBD"
                p_end = t.get("planned_end_date") or "TBD"
                dates_tag = f" [{p_start} to {p_end}]"
                assign_tag = " [Assigned to You]" if t.get("assigned_head_id") == self.user_id else ("" if not t.get("assigned_head_id") else f" [{t.get('assigned_head_name')}]")
                item = QListWidgetItem(f"{t['name']} ({t['task_id']}){dates_tag}{assign_tag}")
                item.setData(Qt.UserRole, t["task_id"])
                item.setData(Qt.UserRole + 1, t["project_id"])
                item.setData(Qt.UserRole + 2, t)
                self.lst_tasks.addItem(item)
                count += 1

        tab_title = f"{self.discipline_label} ({count})"
        self.disc_tabs.setTabText(0, tab_title)

        # Request progressive project timeline data from server
        if self.net_client.is_connected:
            self.net_client.call("GET_PROJECT_TIMELINE", {"project_id": p_id},
                                 lambda r: self.proj_timeline_widget.load_timeline_data(r.get("data", {})),
                                 self.on_request_error)

    def _locked_date_field(self) -> QLineEdit:
        field = QLineEdit()
        field.setReadOnly(True)
        field.setFocusPolicy(Qt.NoFocus)
        field.setPlaceholderText("Select a task")
        field.setStyleSheet("color: #A1A1AA; background-color: #18181B;")
        return field

    def on_task_selected(self):
        """Show the selected task's planned dates (from the approved request or a later date change)."""
        items = self.lst_tasks.selectedItems()
        if not items:
            self.txt_task_start.clear()
            self.txt_task_end.clear()
            self.apply_entry_type_rules(None)
            return
        t = items[0].data(Qt.UserRole + 2) or {}
        self.txt_task_start.setText(t.get("planned_start_date") or "Not set")
        self.txt_task_end.setText(t.get("planned_end_date") or "Not set")
        self.apply_entry_type_rules(t)

    def apply_entry_type_rules(self, task: dict | None):
        """New Task only for a task's first entry; afterwards only Continuation or Revision (server enforces it)."""
        if task is None:
            for rb in (self.rb_new, self.rb_continuation, self.rb_revision):
                rb.setEnabled(False)
            self.lbl_entry_hint.setText("Select a task first.")
            return
        has_entries = (task.get("log_count") or 0) > 0
        self.rb_new.setEnabled(not has_entries)
        self.rb_continuation.setEnabled(has_entries)
        self.rb_revision.setEnabled(has_entries)
        if has_entries and self.rb_new.isChecked():
            self.rb_continuation.setChecked(True)
        elif not has_entries:
            self.rb_new.setChecked(True)
        self.lbl_entry_hint.setText(
            "New Task was already submitted for this task. Choose Continuation or Revision." if has_entries
            else "First entry for this task: New Task. Later entries are Continuation or Revision.")

    def _mark_task_has_entry(self, task_id: str):
        """Lock New Task right after submitting, even before the server answers (or while offline)."""
        for t in self.tasks_data:
            if t.get("task_id") == task_id:
                t["log_count"] = (t.get("log_count") or 0) + 1
        for i in range(self.lst_tasks.count()):
            item = self.lst_tasks.item(i)
            if item.data(Qt.UserRole) == task_id:
                data = item.data(Qt.UserRole + 2) or {}
                data["log_count"] = (data.get("log_count") or 0) + 1
                item.setData(Qt.UserRole + 2, data)
                if item.isSelected():
                    self.apply_entry_type_rules(data)

    def update_revision_tag_display(self):
        if self.rb_revision.isChecked():
            items = self.lst_tasks.selectedItems()
            if items:
                task_id = items[0].data(Qt.UserRole)
                project_id = items[0].data(Qt.UserRole + 1)
                if not self.net_client.is_connected:
                    self.lbl_rev_tag.setText("[Revision Tag: assigned when synced]")
                    return
                self.net_client.call("CALCULATE_NEXT_REVISION", {"project_id": project_id, "task_id": task_id},
                                     lambda r: self.lbl_rev_tag.setText(f"[Revision Tag: R{r.get('revision_number', 1)}]"),
                                     lambda e: self.lbl_rev_tag.setText("[Revision Tag: assigned when synced]"))
            else:
                self.lbl_rev_tag.setText("[Revision Tag: R1]")
        else:
            self.lbl_rev_tag.setText("")

    def on_submit_log(self):
        selected_tasks = self.lst_tasks.selectedItems()
        if not selected_tasks:
            self.toast.show_message("Please select a Task from your discipline list.", is_warning=True)
            return

        t_data = selected_tasks[0].data(Qt.UserRole + 2)
        task_id = t_data["task_id"]
        project_id = t_data["project_id"]
        notes = self.txt_notes.toPlainText().strip()
        assigned_to = self.txt_assigned_to.text().strip()

        stage = self.cmb_progress.currentText()

        if self.rb_revision.isChecked():
            entry_type = ENTRY_TYPE_REVISION
            # Parse revision number from label tag
            rev_str = self.lbl_rev_tag.text().replace("[Revision Tag: R", "").replace("]", "")
            rev_num = int(rev_str) if rev_str.isdigit() else 1
        elif self.rb_continuation.isChecked():
            entry_type = ENTRY_TYPE_CONTINUATION
            rev_num = 0
        else:
            entry_type = ENTRY_TYPE_NEW
            rev_num = 0

        log_payload = {
            "project_id": project_id,
            "task_id": task_id,
            "progress_stage": stage,
            "entry_type": entry_type,
            "revision_number": rev_num,
            "notes": notes,
            "assigned_to": assigned_to,
            "discipline_id": self.discipline_id
        }

        item_id = self.sync_service.submit_progress_log(log_payload)
        self._mark_task_has_entry(task_id)
        # Guard against accidental double submission
        self.btn_submit.setEnabled(False)
        QTimer.singleShot(1500, lambda: self.btn_submit.setEnabled(True))
        self.save_assigned_to_history(assigned_to)
        self.txt_notes.clear()
        self._track_submission(item_id, "Progress log")
        self.update_sync_badge()

    def _track_submission(self, item_id: str, label: str):
        """Shows 'saved' when the server confirms, or 'queued' if it is offline / slow."""
        if not self.net_client.is_connected:
            self.toast.show_message(f"Offline: {label} saved on this PC and will be sent automatically when the "
                                    f"connection returns.", is_warning=True, duration_ms=6000)
            return
        self._awaiting_ack[item_id] = label

        def still_waiting():
            if item_id in self._awaiting_ack:
                self.toast.show_message(f"{label} queued; it will be sent when the server answers.", is_warning=True)
        QTimer.singleShot(4000, still_waiting)

    def on_item_synced(self, action: str, item_id: str, reply: dict):
        label = self._awaiting_ack.pop(item_id, None)
        if action == "SUBMIT_LOG":
            log = reply.get("log", {})
            tag = f" (R{log.get('revision_number')})" if log.get("entry_type") == "REVISION" else ""
            self.toast.show_message(f"Progress log saved on the Central Server{tag}.")
        elif label:
            self.toast.show_message(f"{label} saved on the Central Server.")
        if action in ("PROPOSE_TASK", "REQUEST_TASK_DATE_CHANGE"):
            self.request_refresh_from_server()
        self.update_sync_badge()

    def on_item_failed(self, action: str, item_id: str, error: str):
        self._awaiting_ack.pop(item_id, None)
        label = FailedSubmissionsDialog.ACTION_LABELS.get(action, "Item")
        self.toast.show_message(f"{label} was rejected by the Central Server: {error}", is_error=True, duration_ms=9000)
        self.update_sync_badge()
        self.request_refresh_from_server()  # resync task state (e.g. which entry types are allowed)

    def on_open_failed_items(self):
        FailedSubmissionsDialog(self.sync_service, self).exec()
        self.update_sync_badge()

    def on_open_task_proposal_dialog(self):
        if not self.projects_data:
            self.toast.show_message("You have no assigned projects to request tasks for.", is_warning=True)
            return

        dlg = TaskProposalDialog(self, self.projects_data, self.discipline_id, self.net_client)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            proposal_payload = {
                "project_id": data["project_id"],
                "task_name": data["task_name"],
                "planned_start_date": data["planned_start_date"],
                "planned_end_date": data["planned_end_date"]
            }
            item_id = self.sync_service.propose_task(proposal_payload)
            self._track_submission(item_id, f"Task request '{data['task_name']}'")

    def on_open_date_change_dialog(self):
        selected = self.lst_tasks.selectedItems()
        if not selected:
            self.toast.show_message("Please select a Task to request a date change.", is_warning=True)
            return
        t_data = selected[0].data(Qt.UserRole + 2)
        dlg = DateChangeRequestDialog(t_data, self)
        if dlg.exec() == QDialog.Accepted:
            req_data = dlg.get_data()
            item_id = self.sync_service.request_date_change(req_data)
            self._track_submission(item_id, "Date change request")

    def on_task_proposal_event(self, data: dict):
        prop = data.get("proposal", {})
        if prop.get("proposed_by_id") == self.user_id:
            st = prop.get("status")
            name = prop.get("task_name")
            if st == "APPROVED":
                self.toast.show_message(f"Admin APPROVED your task proposal: '{name}'!")
            elif st == "REJECTED":
                reason = prop.get("rejection_reason", "No reason provided")
                self.toast.show_message(f"Admin REJECTED task proposal '{name}': {reason}", is_warning=True)

    def on_task_date_change_event(self, data: dict):
        req = data.get("request", {})
        if req.get("requested_by_id") == self.user_id:
            st = req.get("status")
            t_id = req.get("task_id")
            if st == "APPROVED":
                self.toast.show_message(f"Admin APPROVED schedule change for task '{t_id}'!")
            elif st == "REJECTED":
                reason = req.get("rejection_reason", "No reason provided")
                self.toast.show_message(f"Admin REJECTED schedule change for task '{t_id}': {reason}", is_warning=True)

    def on_priority_alert(self, data: dict):
        notif = data.get("notification", {})
        n_id = notif.get("notification_id")
        coo_id = notif.get("coo_id")
        msg = notif.get("message")
        if not n_id or n_id in self._open_alerts or self._alert_already_answered(n_id):
            return

        modal = BlockingCenterModal(n_id, coo_id, msg, parent=self)
        modal.response_submitted.connect(lambda status: self.on_modal_response(n_id, status))
        modal.finished.connect(lambda _: self._open_alerts.pop(n_id, None))
        self._open_alerts[n_id] = modal
        modal.open()  # window-modal without a nested event loop; still only closable via Accept/Deny

    def _alert_already_answered(self, notif_id: str) -> bool:
        # An answer may still be waiting in the outbox (offline) - do not ask again
        return any(it["item_id"] == notif_id
                   for it in self.sync_service.queue_db.get_items(self.user_id)
                   if it["event_type"] == "RESPOND_NOTIFICATION")

    def on_modal_response(self, notif_id: str, status: str):
        payload = {"notification_id": notif_id, "response_status": status}
        item_id = self.sync_service.respond_priority_notification(payload)
        self._track_submission(item_id, f"Response '{status}' to the COO")

    def on_net_status_changed(self, is_connected: bool, status_msg: str):
        self.update_sync_badge(is_connected, status_msg)
        if is_connected:
            self.request_refresh_from_server()

    def update_sync_badge(self, is_connected: bool = None, status_msg: str = ""):
        if is_connected is None:
            is_connected = self.net_client.is_connected
        failed = self.sync_service.failed_count()
        self.sync_badge.update_status(is_connected, status_msg, self.sync_service.pending_count(), failed)
        self.btn_failed.setText(f"Rejected Items ({failed})")
        self.btn_failed.setVisible(failed > 0)

    # ----------------- TIMELINE TAB (PROPOSALS & DATE CHANGES) -----------------
    def create_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Vertical, widget)

        # Top: Task Proposals
        card_p = QFrame(splitter)
        card_p.setObjectName("CardFrame")
        cp_layout = QVBoxLayout(card_p)
        cp_layout.setContentsMargins(10, 10, 10, 10)
        cp_layout.addWidget(QLabel("Task Proposals Timeline", objectName="SubTitle"))
        self.tbl_proposals = QTableWidget(0, 6)
        self.tbl_proposals.setHorizontalHeaderLabels([
            "Proposal ID", "Task ID", "Project", "Task Name", "Status", "Admin Decision"
        ])
        setup_modern_table(self.tbl_proposals, row_height=44)
        self.tbl_proposals.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_proposals.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl_proposals.setColumnWidth(0, 95)
        self.tbl_proposals.setColumnWidth(1, 95)
        self.tbl_proposals.setColumnWidth(2, 130)
        self.tbl_proposals.setColumnWidth(4, 95)
        self.tbl_proposals.setColumnWidth(5, 200)
        cp_layout.addWidget(self.tbl_proposals)
        splitter.addWidget(card_p)

        # Bottom: Date Change Requests
        card_d = QFrame(splitter)
        card_d.setObjectName("CardFrame")
        cd_layout = QVBoxLayout(card_d)
        cd_layout.setContentsMargins(10, 10, 10, 10)
        cd_layout.addWidget(QLabel("Task Date Change Requests Timeline", objectName="SubTitle"))
        self.tbl_date_changes = QTableWidget(0, 6)
        self.tbl_date_changes.setHorizontalHeaderLabels([
            "Request ID", "Task ID", "New Schedule", "Reason", "Status", "Admin Decision"
        ])
        setup_modern_table(self.tbl_date_changes, row_height=44)
        self.tbl_date_changes.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_date_changes.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl_date_changes.setColumnWidth(0, 95)
        self.tbl_date_changes.setColumnWidth(1, 95)
        self.tbl_date_changes.setColumnWidth(2, 180)
        self.tbl_date_changes.setColumnWidth(4, 95)
        self.tbl_date_changes.setColumnWidth(5, 200)
        cd_layout.addWidget(self.tbl_date_changes)
        splitter.addWidget(card_d)

        splitter.setSizes([300, 300])
        layout.addWidget(splitter)
        return widget

    def populate_proposals_timeline(self, proposals: list):
        self.tbl_proposals.setRowCount(0)
        for r_idx, p in enumerate(proposals):
            self.tbl_proposals.insertRow(r_idx)
            self.tbl_proposals.setItem(r_idx, 0, create_table_item(p["proposal_id"], Qt.AlignCenter))
            self.tbl_proposals.setItem(r_idx, 1, create_table_item(p["task_id"] or "Pending", Qt.AlignCenter))
            self.tbl_proposals.setItem(r_idx, 2, create_table_item(p.get("project_name") or p["project_id"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_proposals.setItem(r_idx, 3, create_table_item(p["task_name"], Qt.AlignLeft | Qt.AlignVCenter))

            st_item = create_table_item(p["status"], Qt.AlignCenter)
            if p["status"] == "APPROVED":
                st_item.setForeground(Qt.green)
                dec_info = f"Approved by {p.get('admin_name') or 'Admin'} on {p.get('decided_at', '')}"
            elif p["status"] == "REJECTED":
                st_item.setForeground(Qt.red)
                dec_info = f"Rejected: {p.get('rejection_reason', 'No reason')}"
            else:
                st_item.setForeground(Qt.yellow)
                dec_info = "Pending Admin Review..."
            self.tbl_proposals.setItem(r_idx, 4, st_item)
            self.tbl_proposals.setItem(r_idx, 5, create_table_item(dec_info, Qt.AlignLeft | Qt.AlignVCenter))

    def populate_date_change_timeline(self, requests: list):
        self.tbl_date_changes.setRowCount(0)
        for r_idx, req in enumerate(requests):
            self.tbl_date_changes.insertRow(r_idx)
            self.tbl_date_changes.setItem(r_idx, 0, create_table_item(req["request_id"], Qt.AlignCenter))
            self.tbl_date_changes.setItem(r_idx, 1, create_table_item(req["task_id"], Qt.AlignCenter))
            self.tbl_date_changes.setItem(r_idx, 2, create_table_item(f"{req['new_start_date']} to {req['new_end_date']}", Qt.AlignCenter))
            self.tbl_date_changes.setItem(r_idx, 3, create_table_item(req["reason"], Qt.AlignLeft | Qt.AlignVCenter))

            st_item = create_table_item(req["status"], Qt.AlignCenter)
            if req["status"] == "APPROVED":
                st_item.setForeground(Qt.green)
                dec_info = f"Approved on {req.get('decided_at', '')}"
            elif req["status"] == "REJECTED":
                st_item.setForeground(Qt.red)
                dec_info = f"Rejected: {req.get('rejection_reason', 'No reason')}"
            else:
                st_item.setForeground(Qt.yellow)
                dec_info = "Pending Admin Review..."
            self.tbl_date_changes.setItem(r_idx, 4, st_item)
            self.tbl_date_changes.setItem(r_idx, 5, create_table_item(dec_info, Qt.AlignLeft | Qt.AlignVCenter))

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()

    def restore_splitter_states(self):
        w = max(self.width(), 1050)
        sidebar_w = int(w * 0.382)
        content_w = int(w * 0.618)
        settings = app_settings("HeadWorkspace")
        log_sizes = settings.value(f"{self.user_id}/log_splitter_sizes")
        if log_sizes and hasattr(self, "log_splitter"):
            try:
                self.log_splitter.setSizes([int(x) for x in log_sizes])
            except Exception:
                self.log_splitter.setSizes([sidebar_w, content_w])
        elif hasattr(self, "log_splitter"):
            self.log_splitter.setSizes([sidebar_w, content_w])

    def closeEvent(self, event):
        settings = app_settings("HeadWorkspace")
        if hasattr(self, "log_splitter"):
            settings.setValue(f"{self.user_id}/log_splitter_sizes", self.log_splitter.sizes())
        super().closeEvent(event)

