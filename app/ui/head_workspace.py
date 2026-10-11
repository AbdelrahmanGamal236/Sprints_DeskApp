import uuid
import json
from datetime import datetime
from PySide6.QtCore import Qt, QDate, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDateEdit, QTextEdit, QPushButton, QFrame, 
    QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QRadioButton, QButtonGroup, QMessageBox, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QCompleter
)
from app.core.config import PROGRESS_STAGES, ENTRY_TYPE_NEW, ENTRY_TYPE_CONTINUATION, ENTRY_TYPE_REVISION
from app.network.client import NetworkClient
from app.services.sync_service import SyncService
from app.ui.components import (
    ToastNotifier, SyncStatusBadge, BlockingCenterModal, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_item
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

        lbl_curr = QLabel(f"Current Schedule: {curr_start}  ➔  {curr_end}", self)
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


class HeadWorkspace(QMainWindow):
    """Employee / Head Workstation with Discipline Task Filtering & Resizable Panels (A1, A2, A3, A5, A6)."""
    def __init__(self, user_dict: dict, db_manager, net_client: NetworkClient, sync_service: SyncService):
        super().__init__()
        self.user = user_dict
        self.user_id = user_dict["user_id"]
        self.discipline_id = user_dict.get("discipline_id")
        self.db = db_manager
        self.net_client = net_client
        self.sync_service = sync_service
        self.logout_requested = False

        self.projects_data = []
        self.tasks_data = []

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
        disc_str = f" [Discipline: {self.discipline_id}]" if self.discipline_id else " [No Discipline Assigned]"
        header_title = QLabel(f"Employee: {emp_name} ({self.user_id}){disc_str}", self)
        header_title.setObjectName("HeaderTitle")
        top_bar.addWidget(header_title)
        top_bar.addStretch()

        self.sync_badge = SyncStatusBadge(self)
        top_bar.addWidget(self.sync_badge)

        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)
        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Tabs: Daily Progress Logging, Audit Timeline & Progressive Timeline
        self.main_tabs = QTabWidget(self)
        self.main_tabs.addTab(self.create_logging_tab(), "Daily Progress Logging")
        self.main_tabs.addTab(self.create_project_timeline_tab(), "Project Progressive Timeline")
        self.main_tabs.addTab(self.create_timeline_tab(), "Task Requests & Date Changes Timeline")
        main_layout.addWidget(self.main_tabs)

        main_layout.addWidget(CopyrightFooter(self))

        # Network bindings
        self.net_client.connection_status_changed.connect(self.on_net_status_changed)
        self.net_client.initial_snapshot_received.connect(self.on_initial_snapshot)
        self.net_client.priority_alert_received.connect(self.on_priority_alert)
        self.net_client.task_proposal_event.connect(self.on_task_proposal_event)
        self.net_client.task_date_change_event.connect(self.on_task_date_change_event)
        self.net_client.global_refresh_received.connect(self.request_refresh_from_server)
        self.net_client.response_received.connect(self.on_server_response)

        # Load initial data from server snapshot
        self.request_refresh_from_server()
        self.restore_splitter_states()

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

        # Project selector
        left_vbox.addWidget(QLabel("1. Select Project:", objectName="FieldLabel"))
        self.lst_projects = QListWidget()
        self.lst_projects.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst_projects.itemSelectionChanged.connect(self.on_project_selected)
        self.lst_projects.setMaximumHeight(130)
        left_vbox.addWidget(self.lst_projects)

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

        tab_title = f"{self.discipline_id} (0)" if self.discipline_id else "Unassigned (0)"
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

        # Dates Row
        dates_row = QHBoxLayout()
        s_box = QVBoxLayout()
        s_box.addWidget(QLabel("3. Start Date:", objectName="FieldLabel"))
        self.dt_start = QDateEdit(QDate.currentDate())
        self.dt_start.setCalendarPopup(True)
        s_box.addWidget(self.dt_start)
        dates_row.addLayout(s_box)

        e_box = QVBoxLayout()
        e_box.addWidget(QLabel("4. End Date:", objectName="FieldLabel"))
        self.dt_end = QDateEdit(QDate.currentDate())
        self.dt_end.setCalendarPopup(True)
        e_box.addWidget(self.dt_end)
        dates_row.addLayout(e_box)
        right_vbox.addLayout(dates_row)

        # Task Logging Context / Rework Tag (R1, R2...)
        right_vbox.addWidget(QLabel("5. Task Logging Context:", objectName="FieldLabel"))
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
        self.rb_group.buttonToggled.connect(self.update_revision_tag_display)

        # Status & Assigned To Row (A5)
        row_status_assign = QHBoxLayout()
        box_st = QVBoxLayout()
        box_st.addWidget(QLabel("6. Task Status:", objectName="FieldLabel"))
        self.cmb_progress = QComboBox()
        for s in PROGRESS_STAGES:
            self.cmb_progress.addItem(s)
        box_st.addWidget(self.cmb_progress)
        row_status_assign.addLayout(box_st)

        box_as = QVBoxLayout()
        box_as.addWidget(QLabel("7. Assigned To (Team Member Name):", objectName="FieldLabel"))
        self.txt_assigned_to = QLineEdit()
        self.txt_assigned_to.setPlaceholderText("e.g. Eng. Tarek (optional, max 100 chars)")
        self.txt_assigned_to.setMaxLength(100)
        self.setup_assigned_to_autocomplete()
        box_as.addWidget(self.txt_assigned_to)
        row_status_assign.addLayout(box_as)
        right_vbox.addLayout(row_status_assign)

        # Notes Box
        right_vbox.addWidget(QLabel("8. Work Notes & Activity Summary:", objectName="FieldLabel"))
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
        settings = QSettings("SprintsDeskApp", "ClientConfig")
        recent_names = settings.value(f"assigned_to_history_{self.user_id}", [])
        if isinstance(recent_names, list) and recent_names:
            completer = QCompleter(recent_names, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.txt_assigned_to.setCompleter(completer)

    def save_assigned_to_history(self, name: str):
        if not name:
            return
        settings = QSettings("SprintsDeskApp", "ClientConfig")
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

    def restore_splitter_states(self):
        """Restores resizable splitter positions and collapsed states (A6)."""
        settings = QSettings("SprintsDeskApp", "ClientConfig")
        sizes = settings.value(f"HeadWorkspace_Splitter_{self.user_id}")
        if sizes:
            try:
                self.log_splitter.setSizes([int(s) for s in sizes])
            except Exception:
                pass

    def closeEvent(self, event):
        # Save splitter states on close (A6)
        settings = QSettings("SprintsDeskApp", "ClientConfig")
        settings.setValue(f"HeadWorkspace_Splitter_{self.user_id}", self.log_splitter.sizes())
        event.accept()

    def request_refresh_from_server(self):
        self.net_client.send_action("IDENTIFY", {"user_id": self.user_id, "role": self.user["role"]})
        self.net_client.send_action("GET_TASK_PROPOSALS", {"proposed_by_id": self.user_id})
        self.net_client.send_action("GET_DATE_CHANGE_REQUESTS", {"requested_by_id": self.user_id})

    def on_initial_snapshot(self, snapshot: dict):
        self.projects_data = snapshot.get("projects", [])
        self.tasks_data = snapshot.get("tasks", [])
        self.populate_project_list()

        # Handle pending priority alerts if present
        for notif in snapshot.get("pending_notifications", []):
            self.on_priority_alert({"notification": notif})

    def populate_project_list(self):
        self.lst_projects.clear()
        for p in self.projects_data:
            item = QListWidgetItem(f"{p['name']} ({p['project_id']})")
            item.setData(Qt.UserRole, p["project_id"])
            self.lst_projects.addItem(item)
        if self.lst_projects.count() > 0:
            self.lst_projects.setCurrentRow(0)

    def create_project_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        self.proj_timeline_widget = ProjectProgressiveTimelineWidget()
        layout.addWidget(self.proj_timeline_widget)
        return widget

    def on_project_selected(self):
        selected_items = self.lst_projects.selectedItems()
        if not selected_items:
            self.lst_tasks.clear()
            if hasattr(self, "proj_timeline_widget"):
                self.proj_timeline_widget.load_timeline_data({})
            return
        p_id = selected_items[0].data(Qt.UserRole)

        self.lst_tasks.clear()
        count = 0
        for t in self.tasks_data:
            if t.get("project_id") == p_id:
                # Dates display (A2)
                p_start = t.get("planned_start_date") or "TBD"
                p_end = t.get("planned_end_date") or "TBD"
                dates_tag = f" [{p_start} to {p_end}]"
                assign_tag = " 👤 [Assigned to You]" if t.get("assigned_head_id") == self.user_id else ("" if not t.get("assigned_head_id") else f" [👤 {t.get('assigned_head_name')}]")
                item = QListWidgetItem(f"{t['name']} ({t['task_id']}){dates_tag}{assign_tag}")
                item.setData(Qt.UserRole, t["task_id"])
                item.setData(Qt.UserRole + 1, t["project_id"])
                item.setData(Qt.UserRole + 2, t)
                self.lst_tasks.addItem(item)
                count += 1

        tab_title = f"{self.discipline_id or 'Unassigned'} ({count})"
        self.disc_tabs.setTabText(0, tab_title)

        # Request progressive project timeline data from server
        self.net_client.send_action("GET_PROJECT_TIMELINE", {"project_id": p_id})

    def update_revision_tag_display(self):
        if self.rb_revision.isChecked():
            items = self.lst_tasks.selectedItems()
            if items:
                task_id = items[0].data(Qt.UserRole)
                project_id = items[0].data(Qt.UserRole + 1)
                self.net_client.send_action("CALCULATE_NEXT_REVISION", {
                    "employee_id": self.user_id,
                    "project_id": project_id,
                    "task_id": task_id
                })
            else:
                self.lbl_rev_tag.setText("[Revision Tag: R1]")
        else:
            self.lbl_rev_tag.setText("")

    def on_server_response(self, resp_type: str, data: dict):
        if resp_type == "NEXT_REVISION_RESPONSE":
            rev = data.get("revision_number", 1)
            self.lbl_rev_tag.setText(f"[Revision Tag: R{rev}]")
        elif resp_type == "TASK_PROPOSALS_RESPONSE":
            self.populate_proposals_timeline(data.get("proposals", []))
        elif resp_type == "DATE_CHANGE_REQUESTS_RESPONSE":
            self.populate_date_change_timeline(data.get("requests", []))
        elif resp_type == "PROJECT_TIMELINE_RESPONSE":
            if hasattr(self, "proj_timeline_widget"):
                self.proj_timeline_widget.load_timeline_data(data.get("data", {}))

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

        start_str = self.dt_start.date().toString("yyyy-MM-dd")
        end_str = self.dt_end.date().toString("yyyy-MM-dd")
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
            "log_id": f"LOG-{uuid.uuid4().hex[:8].upper()}",
            "employee_id": self.user_id,
            "project_id": project_id,
            "task_id": task_id,
            "start_date": start_str,
            "end_date": end_str,
            "progress_percentage": 0,
            "progress_stage": stage,
            "entry_type": entry_type,
            "revision_number": rev_num,
            "notes": notes,
            "assigned_to": assigned_to,
            "discipline_id": self.discipline_id
        }

        sent = self.sync_service.submit_progress_log(log_payload)
        self.save_assigned_to_history(assigned_to)
        self.txt_notes.clear()

        if sent:
            self.toast.show_message("Progress log submitted successfully to Central Server!")
        else:
            self.toast.show_message("Offline: Log queued locally. Will sync upon connection.", is_warning=True)
        self.update_sync_badge()

    def on_open_task_proposal_dialog(self):
        if not self.projects_data:
            self.toast.show_message("You have no assigned projects to request tasks for.", is_warning=True)
            return

        dlg = TaskProposalDialog(self, self.projects_data, self.discipline_id, self.net_client)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            proposal_payload = {
                "proposal_id": f"PROP-{uuid.uuid4().hex[:8].upper()}",
                "project_id": data["project_id"],
                "task_name": data["task_name"],
                "proposed_by_id": self.user_id,
                "discipline_id": self.discipline_id,
                "planned_start_date": data["planned_start_date"],
                "planned_end_date": data["planned_end_date"]
            }
            self.sync_service.propose_task(proposal_payload)
            self.toast.show_message(f"Task proposal for '{data['task_name']}' submitted!")
            self.request_refresh_from_server()

    def on_open_date_change_dialog(self):
        selected = self.lst_tasks.selectedItems()
        if not selected:
            self.toast.show_message("Please select a Task to request a date change.", is_warning=True)
            return
        t_data = selected[0].data(Qt.UserRole + 2)
        dlg = DateChangeRequestDialog(t_data, self)
        if dlg.exec() == QDialog.Accepted:
            req_data = dlg.get_data()
            req_data["request_id"] = f"DCR-{uuid.uuid4().hex[:8].upper()}"
            req_data["requested_by_id"] = self.user_id
            self.sync_service.request_date_change(req_data)
            self.toast.show_message("Date change request submitted for Admin review!")
            self.request_refresh_from_server()

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
        self.request_refresh_from_server()

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
        self.request_refresh_from_server()

    def on_priority_alert(self, data: dict):
        notif = data.get("notification", {})
        n_id = notif.get("notification_id")
        coo_id = notif.get("coo_id")
        msg = notif.get("message")
        if not n_id:
            return

        modal = BlockingCenterModal(n_id, coo_id, msg, parent=self)
        modal.response_submitted.connect(lambda status: self.on_modal_response(n_id, status))
        modal.exec()

    def on_modal_response(self, notif_id: str, status: str):
        payload = {"notification_id": notif_id, "employee_id": self.user_id, "response_status": status}
        self.sync_service.respond_priority_notification(payload)
        self.toast.show_message(f"Priority response ('{status}') dispatched to COO.")

    def on_net_status_changed(self, is_connected: bool, status_msg: str):
        self.update_sync_badge(is_connected, status_msg)

    def update_sync_badge(self, is_connected: bool = None, status_msg: str = ""):
        if is_connected is None:
            is_connected = self.net_client.is_connected
        pending_cnt = self.sync_service.get_pending_queue_count()
        self.sync_badge.update_status(is_connected, status_msg, pending_cnt)

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
            self.tbl_date_changes.setItem(r_idx, 2, create_table_item(f"{req['new_start_date']} ➔ {req['new_end_date']}", Qt.AlignCenter))
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
        settings = QSettings("SprintsDeskApp", "HeadWorkspace")
        log_sizes = settings.value("log_splitter_sizes")
        if log_sizes and hasattr(self, "log_splitter"):
            try:
                self.log_splitter.setSizes([int(x) for x in log_sizes])
            except Exception:
                self.log_splitter.setSizes([sidebar_w, content_w])
        elif hasattr(self, "log_splitter"):
            self.log_splitter.setSizes([sidebar_w, content_w])

    def closeEvent(self, event):
        settings = QSettings("SprintsDeskApp", "HeadWorkspace")
        if hasattr(self, "log_splitter"):
            settings.setValue("log_splitter_sizes", self.log_splitter.sizes())
        super().closeEvent(event)

