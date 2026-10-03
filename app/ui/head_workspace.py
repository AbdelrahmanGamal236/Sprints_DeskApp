import uuid
from datetime import datetime
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDateEdit, QTextEdit, QPushButton, QFrame, 
    QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QRadioButton, QButtonGroup, QMessageBox, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget
)
from app.core.config import PROGRESS_STAGES, ENTRY_TYPE_NEW, ENTRY_TYPE_CONTINUATION, ENTRY_TYPE_REVISION
from app.database.db_manager import DBManager
from app.network.client import NetworkClient
from app.services.sync_service import SyncService
from app.ui.components import ToastNotifier, SyncStatusBadge, BlockingCenterModal, CopyrightFooter


class TaskProposalDialog(QDialog):
    """Modal dialog for Head to propose a new task for an assigned project."""
    def __init__(self, parent, projects: list, db_manager: DBManager):
        super().__init__(parent)
        self.db = db_manager
        self.projects = projects
        self.setWindowTitle("Propose New Task Request")
        self.setFixedSize(500, 320)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Request New Task for Project", self)
        title.setObjectName("SubTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("Select Project:", self, objectName="FieldLabel"))
        self.cmb_proj = QComboBox(self)
        for p in self.projects:
            self.cmb_proj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
        self.cmb_proj.currentIndexChanged.connect(self.update_task_id_preview)
        layout.addWidget(self.cmb_proj)

        layout.addWidget(QLabel("Proposed Task Name:", self, objectName="FieldLabel"))
        self.txt_task_name = QLineEdit(self)
        self.txt_task_name.setPlaceholderText("e.g. Router & Switch Configuration - Rack 2")
        layout.addWidget(self.txt_task_name)

        self.lbl_task_id_preview = QLabel("", self)
        self.lbl_task_id_preview.setStyleSheet("color: #7C3AED; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.lbl_task_id_preview)
        self.update_task_id_preview()

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

    def update_task_id_preview(self):
        p_id = self.cmb_proj.currentData()
        next_id = self.db.generate_next_task_id(p_id)
        self.lbl_task_id_preview.setText(f"System-assigned Task ID upon approval: {next_id}")

    def on_submit(self):
        name = self.txt_task_name.text().strip()
        p_id = self.cmb_proj.currentData()
        if not name or not p_id:
            QMessageBox.warning(self, "Validation Error", "Please provide a valid task name and select a project.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "project_id": self.cmb_proj.currentData(),
            "task_name": self.txt_task_name.text().strip()
        }

class HeadWorkspace(QMainWindow):
    """Employee / Head Workstation Form and Daily Progress Logger."""
    def __init__(self, user_dict: dict, db_manager: DBManager, net_client: NetworkClient, sync_service: SyncService):
        super().__init__()
        self.user_id = user_dict["user_id"]
        self.db = db_manager
        self.net_client = net_client
        self.sync_service = sync_service
        self.logout_requested = False

        self.projects_data = [] # List of project dicts
        self.tasks_data = []    # List of task dicts

        self.setWindowTitle(f"Head Workstation - Employee ID: {self.user_id}")
        self.setMinimumSize(950, 680)

        # Central Layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Top Bar: Header & Sync Status Badge
        top_bar = QHBoxLayout()
        emp_name = user_dict.get("full_name")
        if emp_name:
            header_str = f"Employee: {emp_name} ({self.user_id})"
        else:
            header_str = f"Employee: {self.user_id}"

        header_title = QLabel(header_str, self)
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

        # Toast Notifier
        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Form Card Frame
        form_card = QFrame(self)
        form_card.setObjectName("CardFrame")
        form_layout = QVBoxLayout(form_card)
        form_layout.setSpacing(12)

        form_heading = QLabel("Daily Progress Logging Form", form_card)
        form_heading.setObjectName("SubTitle")
        form_layout.addWidget(form_heading)

        # Splitter: Left (Project & Task selection), Right (Dates, Progress, Notes)
        splitter = QSplitter(Qt.Horizontal, form_card)
        
        # Left Container
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)

        lbl_proj = QLabel("1. Select Project:", left_widget)
        lbl_proj.setObjectName("FieldLabel")
        left_layout.addWidget(lbl_proj)

        self.lst_projects = QListWidget(left_widget)
        self.lst_projects.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst_projects.itemSelectionChanged.connect(self.on_project_selection_changed)
        left_layout.addWidget(self.lst_projects)

        task_header_layout = QHBoxLayout()
        lbl_task = QLabel("2. Select Task:", left_widget)
        lbl_task.setObjectName("FieldLabel")
        task_header_layout.addWidget(lbl_task)
        task_header_layout.addStretch()

        btn_propose = QPushButton("+ Request Task", left_widget)
        btn_propose.setCursor(Qt.PointingHandCursor)
        btn_propose.clicked.connect(self.on_open_task_proposal_dialog)
        task_header_layout.addWidget(btn_propose)

        left_layout.addLayout(task_header_layout)

        self.lst_tasks = QListWidget(left_widget)
        self.lst_tasks.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst_tasks.itemSelectionChanged.connect(self.update_revision_tag_display)
        left_layout.addWidget(self.lst_tasks)

        # Right Container
        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)

        # Dates Row
        dates_row = QHBoxLayout()
        
        start_box = QVBoxLayout()
        lbl_start = QLabel("3. Start Date:", right_widget)
        lbl_start.setObjectName("FieldLabel")
        self.dt_start = QDateEdit(QDate.currentDate(), right_widget)
        self.dt_start.setCalendarPopup(True)
        start_box.addWidget(lbl_start)
        start_box.addWidget(self.dt_start)
        dates_row.addLayout(start_box)

        end_box = QVBoxLayout()
        lbl_end = QLabel("4. End Date:", right_widget)
        lbl_end.setObjectName("FieldLabel")
        self.dt_end = QDateEdit(QDate.currentDate(), right_widget)
        self.dt_end.setCalendarPopup(True)
        end_box.addWidget(lbl_end)
        end_box.addWidget(self.dt_end)
        dates_row.addLayout(end_box)

        right_layout.addLayout(dates_row)

        # Task Logging Context / Entry Type Row
        lbl_entry = QLabel("5. Task Logging Context:", right_widget)
        lbl_entry.setObjectName("FieldLabel")
        right_layout.addWidget(lbl_entry)

        rb_layout = QHBoxLayout()
        self.rb_new = QRadioButton("New Task", right_widget)
        self.rb_continuation = QRadioButton("Continuation", right_widget)
        self.rb_revision = QRadioButton("Revision / Rework", right_widget)

        self.rb_group = QButtonGroup(right_widget)
        self.rb_group.addButton(self.rb_new, 1)
        self.rb_group.addButton(self.rb_continuation, 2)
        self.rb_group.addButton(self.rb_revision, 3)
        self.rb_new.setChecked(True)

        rb_layout.addWidget(self.rb_new)
        rb_layout.addWidget(self.rb_continuation)
        rb_layout.addWidget(self.rb_revision)

        self.lbl_rev_tag = QLabel("", right_widget)
        self.lbl_rev_tag.setStyleSheet("font-weight: bold; color: #F59E0B; font-size: 13px; margin-left: 8px;")
        rb_layout.addWidget(self.lbl_rev_tag)
        rb_layout.addStretch()

        right_layout.addLayout(rb_layout)
        self.rb_group.buttonToggled.connect(self.update_revision_tag_display)

        # Progress Selector Row
        lbl_progress = QLabel("6. Task Status:", right_widget)
        lbl_progress.setObjectName("FieldLabel")
        right_layout.addWidget(lbl_progress)

        self.cmb_progress = QComboBox(right_widget)
        for stage in PROGRESS_STAGES:
            self.cmb_progress.addItem(stage)
        self.cmb_progress.setCurrentIndex(0) # Default "In Progress"
        right_layout.addWidget(self.cmb_progress)

        # Notes Box
        lbl_notes = QLabel("7. Work Notes & Activity Summary:", right_widget)
        lbl_notes.setObjectName("FieldLabel")
        right_layout.addWidget(lbl_notes)

        self.txt_notes = QTextEdit(right_widget)
        self.txt_notes.setPlaceholderText("Enter detailed daily progress notes, key achievements, or blockers...")
        right_layout.addWidget(self.txt_notes)

        # Submit Button
        self.btn_submit = QPushButton("SUBMIT PROGRESS LOG", right_widget)
        self.btn_submit.setMinimumHeight(44)
        self.btn_submit.clicked.connect(self.on_submit_log)
        right_layout.addWidget(self.btn_submit)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([320, 580])

        form_layout.addWidget(splitter)

        # Tabs for Form and Audit Sequence Timeline
        tabs = QTabWidget(self)
        tabs.addTab(form_card, "Daily Progress Logging")
        tabs.addTab(self.create_timeline_tab(), "Task Request Sequence Timeline")
        main_layout.addWidget(tabs)

        main_layout.addWidget(CopyrightFooter(self))

        # Bind Network Signals
        self.net_client.connection_status_changed.connect(self.on_net_status_changed)
        self.net_client.initial_snapshot_received.connect(self.on_initial_snapshot)
        self.net_client.priority_alert_received.connect(self.on_priority_alert)
        self.net_client.task_proposal_event.connect(self.on_task_proposal_event)
        self.net_client.global_refresh_received.connect(self.reload_local_data)

        # Load initial local DB data
        self.reload_local_data()
        self.reload_timeline_data()

    def reload_local_data(self):
        """Loads assigned projects & tasks from SQLite database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT p.* FROM projects p
            JOIN employee_projects ep ON p.project_id = ep.project_id
            WHERE ep.employee_id = ? AND p.is_hidden = 0
            """, (self.user_id,))
            self.projects_data = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
            SELECT t.*, u.full_name AS proposer_name 
            FROM tasks t
            LEFT JOIN users u ON t.proposed_by_id = u.user_id
            WHERE t.is_hidden = 0
            """)
            self.tasks_data = [dict(row) for row in cursor.fetchall()]

        self.populate_project_list()
        self.reload_timeline_data()

    def populate_project_list(self):
        self.lst_projects.clear()
        for p in self.projects_data:
            item = QListWidgetItem(f"{p['name']} ({p['project_id']})")
            item.setData(Qt.UserRole, p["project_id"])
            self.lst_projects.addItem(item)

    def on_project_selection_changed(self):
        selected_project_ids = [
            item.data(Qt.UserRole) for item in self.lst_projects.selectedItems()
        ]
        self.lst_tasks.clear()
        for t in self.tasks_data:
            if t["project_id"] in selected_project_ids:
                prop_by = t.get("proposer_name") or t.get("proposed_by_id")
                prop_str = f" [By: {prop_by}]" if prop_by else ""
                item = QListWidgetItem(f"{t['name']} ({t['task_id']}){prop_str}")
                item.setData(Qt.UserRole, t["task_id"])
                item.setData(Qt.UserRole + 1, t["project_id"])
                self.lst_tasks.addItem(item)

    def update_revision_tag_display(self):
        if self.rb_revision.isChecked():
            selected_tasks = self.lst_tasks.selectedItems()
            selected_projects = self.lst_projects.selectedItems()
            if selected_tasks and selected_projects:
                task_id = selected_tasks[0].data(Qt.UserRole)
                project_id = selected_tasks[0].data(Qt.UserRole + 1)
                next_rev = self.db.get_next_revision_number(self.user_id, project_id, task_id)
                self.lbl_rev_tag.setText(f"[Revision Tag: R{next_rev}]")
            else:
                self.lbl_rev_tag.setText("[Revision Tag: R1]")
        else:
            self.lbl_rev_tag.setText("")

    def on_submit_log(self):
        selected_project_items = self.lst_projects.selectedItems()
        selected_task_items = self.lst_tasks.selectedItems()

        if not selected_project_items:
            self.toast.show_message("Please select at least one Project.", is_warning=True)
            return

        if not selected_task_items:
            self.toast.show_message("Please select at least one Task.", is_warning=True)
            return

        notes_text = self.txt_notes.toPlainText().strip()

        start_str = self.dt_start.date().toString("yyyy-MM-dd")
        end_str = self.dt_end.date().toString("yyyy-MM-dd")
        stage_text = self.cmb_progress.currentText()

        if self.rb_revision.isChecked():
            entry_type = ENTRY_TYPE_REVISION
        elif self.rb_continuation.isChecked():
            entry_type = ENTRY_TYPE_CONTINUATION
        else:
            entry_type = ENTRY_TYPE_NEW

        # Submit a log for each selected project+task pairing
        success_count = 0
        queued_count = 0

        for t_item in selected_task_items:
            task_id = t_item.data(Qt.UserRole)
            project_id = t_item.data(Qt.UserRole + 1)
            log_id = f"LOG-{uuid.uuid4().hex[:8].upper()}"

            if entry_type == ENTRY_TYPE_REVISION:
                rev_num = self.db.get_next_revision_number(self.user_id, project_id, task_id)
            else:
                rev_num = 0

            log_payload = {
                "log_id": log_id,
                "employee_id": self.user_id,
                "project_id": project_id,
                "task_id": task_id,
                "start_date": start_str,
                "end_date": end_str,
                "progress_percentage": 0,
                "progress_stage": stage_text,
                "entry_type": entry_type,
                "revision_number": rev_num,
                "notes": notes_text
            }

            sent_live = self.sync_service.submit_progress_log(log_payload)
            if sent_live:
                success_count += 1
            else:
                queued_count += 1

        self.txt_notes.clear()

        if queued_count > 0:
            self.toast.show_message(
                f"Offline: {queued_count} log(s) queued locally. Will auto-sync on reconnect.", 
                is_warning=True
            )
        else:
            self.toast.show_message(
                f"Submitted successfully! {success_count} log entry/entries recorded."
            )

        self.update_sync_badge()

    def on_priority_alert(self, data: dict):
        """Triggered when COO dispatches urgent non-dismissible modal alert."""
        notif_id = data.get("notification_id")
        coo_id = data.get("coo_id")
        msg = data.get("message")

        modal = BlockingCenterModal(notif_id, coo_id, msg, parent=self)
        modal.response_submitted.connect(lambda status: self.on_modal_response(notif_id, status))
        modal.exec()

    def on_modal_response(self, notif_id: str, status: str):
        payload = {
            "notification_id": notif_id,
            "employee_id": self.user_id,
            "response_status": status
        }
        sent = self.sync_service.respond_priority_notification(payload)
        if sent:
            self.toast.show_message(f"Priority response ('{status}') delivered to COO.")
        else:
            self.toast.show_message(f"Offline: Response ('{status}') queued locally.", is_warning=True)

    def on_initial_snapshot(self, snapshot: dict):
        # Update projects and tasks from Central Server live snapshot
        if "projects" in snapshot:
            self.projects_data = snapshot["projects"]
        if "tasks" in snapshot:
            self.tasks_data = snapshot["tasks"]

        self.populate_project_list()

        # Check for pending notifications
        if "pending_notifications" in snapshot:
            for notif in snapshot["pending_notifications"]:
                self.on_priority_alert(notif)

    def on_net_status_changed(self, is_connected: bool, status_msg: str):
        self.update_sync_badge(is_connected, status_msg)

    def update_sync_badge(self, is_connected: bool = None, status_msg: str = ""):
        if is_connected is None:
            is_connected = self.net_client.is_connected
        pending_cnt = self.sync_service.get_pending_queue_count()
        self.sync_badge.update_status(is_connected, status_msg, pending_cnt)

    def create_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        title = QLabel("Audit Sequence Timeline - Task Requests & Approvals", widget)
        title.setObjectName("SubTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        btn_refresh = QPushButton("Refresh Timeline", widget)
        btn_refresh.clicked.connect(self.reload_timeline_data)
        header_layout.addWidget(btn_refresh)

        btn_propose_t = QPushButton("+ Request New Task", widget)
        btn_propose_t.clicked.connect(self.on_open_task_proposal_dialog)
        header_layout.addWidget(btn_propose_t)

        layout.addLayout(header_layout)

        self.tbl_timeline = QTableWidget(0, 7)
        self.tbl_timeline.setHorizontalHeaderLabels([
            "Request ID", "Task ID", "Project", "Task Name", "Submitted At", "Status", "Decision & Feedback"
        ])
        self.tbl_timeline.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_timeline.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.tbl_timeline)
        return widget

    def reload_timeline_data(self):
        proposals = self.db.get_task_proposals(proposed_by_id=self.user_id)
        self.tbl_timeline.setRowCount(0)
        for r_idx, p in enumerate(proposals):
            self.tbl_timeline.insertRow(r_idx)
            self.tbl_timeline.setItem(r_idx, 0, QTableWidgetItem(p["proposal_id"]))
            self.tbl_timeline.setItem(r_idx, 1, QTableWidgetItem(p["task_id"] or "Pending..."))
            self.tbl_timeline.setItem(r_idx, 2, QTableWidgetItem(p["project_name"] or p["project_id"]))
            self.tbl_timeline.setItem(r_idx, 3, QTableWidgetItem(p["task_name"]))
            self.tbl_timeline.setItem(r_idx, 4, QTableWidgetItem(p["created_at"]))

            status_item = QTableWidgetItem(p["status"])
            if p["status"] == "APPROVED":
                status_item.setForeground(Qt.green)
                dec_text = f"Approved by Admin ({p['admin_name'] or p['admin_id'] or 'admin'}) on {p['decided_at'] or ''}"
            elif p["status"] == "REJECTED":
                status_item.setForeground(Qt.red)
                dec_text = f"Rejected on {p['decided_at'] or ''}: {p['rejection_reason'] or 'No reason provided'}"
            else:
                status_item.setForeground(Qt.yellow)
                dec_text = "Pending Admin review..."

            self.tbl_timeline.setItem(r_idx, 5, status_item)
            self.tbl_timeline.setItem(r_idx, 6, QTableWidgetItem(dec_text))

    def on_open_task_proposal_dialog(self):
        if not self.projects_data:
            self.toast.show_message("You have no assigned projects to request tasks for.", is_warning=True)
            return

        dlg = TaskProposalDialog(self, self.projects_data, self.db)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                self.net_client.send_action("PROPOSE_TASK", {
                    "project_id": data["project_id"],
                    "task_name": data["task_name"],
                    "proposed_by_id": self.user_id
                })
                self.toast.show_message(f"Task proposal for '{data['task_name']}' submitted! Waiting for Admin approval.")
                self.reload_timeline_data()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to submit task proposal: {e}")

    def on_task_proposal_event(self, data: dict):
        prop = data.get("proposal", {})
        msg_type = data.get("type")
        if msg_type == "TASK_PROPOSAL_DECIDED_EVENT":
            status = prop.get("status")
            name = prop.get("task_name")
            p_user = prop.get("proposed_by_id")
            if p_user == self.user_id:
                if status == "APPROVED":
                    self.toast.show_message(f"Admin approved your task proposal: '{name}'!")
                else:
                    self.toast.show_message(f"Admin rejected task proposal: '{name}'", is_warning=True)
        self.reload_local_data()
        self.reload_timeline_data()

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()
