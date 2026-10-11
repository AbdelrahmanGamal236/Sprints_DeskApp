from datetime import datetime
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTabWidget, 
    QMessageBox, QFileDialog, QTableWidget, QTableWidgetItem, 
    QHeaderView, QInputDialog, QSplitter, QDateEdit
)
from app.core.settings import app_settings
from app.core.config import ROLE_HEAD, ROLE_COO, ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.network.client import NetworkClient, run_async
from app.ui.components import (
    ToastNotifier, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_action_cell, create_table_item, KpiMetricCard, describe_error,
    ChangeDebouncer, RoleWindow, restore_splitter
)
from app.ui.timeline_widget import ProjectProgressiveTimelineWidget

class AdminPanel(QWidget):
    """All Admin tools. Shown in AdminWorkspace and embedded in the Super Admin console."""
    ALL_SCOPES = {"disciplines", "projects", "tasks", "users", "proposals", "date_changes", "analytics"}

    def __init__(self, user_dict: dict, net_client: NetworkClient, parent=None):
        super().__init__(parent)
        self.user = user_dict
        self.net_client = net_client

        self.disciplines_data = []
        self.projects_data = []
        self.tasks_data = []
        self.users_data = []
        self.pending_proposals_data = []
        self.pending_date_changes_data = []

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Tabs
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.create_employee_tab(), "Manage Heads & Users")
        self.tabs.addTab(self.create_project_tab(), "Manage Projects")
        self.tabs.addTab(self.create_task_tab(), "Manage Tasks & Disciplines")
        self.tabs.addTab(self.create_timeline_tab(), "Project Timeline & Progress")
        self.tabs.addTab(self.create_analysis_tab(), "Analysis & Revision Insights")
        self.tabs.addTab(self.create_export_tab(), "Excel Reports")
        main_layout.addWidget(self.tabs)

        # Network bindings: reload only what changed on the server
        self._changes = ChangeDebouncer(self.reload_scopes, parent=self)
        self.net_client.task_proposal_event.connect(self.on_task_proposal_event)
        self.net_client.task_date_change_event.connect(self.on_task_date_change_event)
        self.net_client.data_changed.connect(self._changes.add)
        self.net_client.log_event_received.connect(lambda _d: self._changes.add({"analytics"}))
        self.net_client.connection_status_changed.connect(lambda ok, _msg: ok and self.reload_all_data())

        self.reload_all_data()

    # ------------------- DATA RELOAD VIA SERVER (B2) -------------------
    def reload_all_data(self):
        self.reload_scopes(self.ALL_SCOPES)

    def reload_scopes(self, scopes):
        if not self.net_client.is_connected:
            return
        scopes = set(scopes)
        call = self.net_client.call
        if "disciplines" in scopes:
            call("GET_DISCIPLINES", {"include_hidden": True}, self._on_disciplines, self.on_request_error)
        if "projects" in scopes:
            call("GET_PROJECTS", {"include_hidden": True}, self._on_projects, self.on_request_error)
        if "tasks" in scopes:
            call("GET_TASKS", {"include_hidden": True}, self._on_tasks, self.on_request_error)
            self.on_timeline_project_selected()
        if "users" in scopes:
            call("GET_USERS", {}, self._on_users, self.on_request_error)
        if "proposals" in scopes:
            call("GET_TASK_PROPOSALS", {}, lambda r: self.update_proposals_views(r.get("proposals", [])), self.on_request_error)
        if "date_changes" in scopes:
            call("GET_DATE_CHANGE_REQUESTS", {}, lambda r: self.update_date_change_views(r.get("requests", [])), self.on_request_error)
        if scopes & {"analytics", "tasks", "projects", "users"}:
            call("GET_ANALYTICS", {}, lambda r: self.update_analytics_views(r.get("data", {})), self.on_request_error)

    def _on_disciplines(self, r):
        self.disciplines_data = r.get("disciplines", [])
        self.update_disciplines_views()

    def _on_projects(self, r):
        self.projects_data = r.get("projects", [])
        self.update_projects_views()

    def _on_tasks(self, r):
        self.tasks_data = r.get("tasks", [])
        self.update_tasks_views()

    def _on_users(self, r):
        self.users_data = r.get("users", [])
        self.update_users_views()
        self.update_export_heads_filter()

    def on_request_error(self, exc):
        self.toast.show_message(describe_error(exc), is_error=True)

    def mutate(self, action: str, payload: dict, success_msg: str, on_ok=None, error_title: str = "Action Failed"):
        """Send a change to the server; report the real outcome (never a success toast before the server confirms)."""
        def ok(reply):
            if success_msg:
                self.toast.show_message(success_msg)
            if on_ok:
                on_ok(reply)

        def err(exc):
            QMessageBox.critical(self, error_title, describe_error(exc))
        self.net_client.call(action, payload, ok, err)

    # ------------------- TAB 1: USERS & HEADS TAB (A3, B5) -------------------
    def create_employee_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        self.emp_splitter = QSplitter(Qt.Horizontal, widget)

        # Form container
        form_widget = QWidget()
        f_layout = QVBoxLayout(form_widget)
        f_layout.addWidget(QLabel("Add New Head (Team Employee)", objectName="SubTitle"))

        f_layout.addWidget(QLabel("User / Employee ID:", objectName="FieldLabel"))
        self.txt_emp_id = QLineEdit()
        self.txt_emp_id.setPlaceholderText("e.g. 1002")
        f_layout.addWidget(self.txt_emp_id)

        f_layout.addWidget(QLabel("Full Name:", objectName="FieldLabel"))
        self.txt_emp_name = QLineEdit()
        self.txt_emp_name.setPlaceholderText("e.g. Eng. Karim Ashraf")
        f_layout.addWidget(self.txt_emp_name)

        f_layout.addWidget(QLabel("Discipline (Required for Head):", objectName="FieldLabel"))
        self.cmb_emp_disc = QComboBox()
        f_layout.addWidget(self.cmb_emp_disc)

        btn_add_emp = QPushButton("Create Head Account")
        btn_add_emp.clicked.connect(self.on_add_employee)
        f_layout.addWidget(btn_add_emp)
        f_layout.addStretch()

        panel_left = CollapsiblePanel("New Head Creation", form_widget, horizontal=True)
        self.emp_splitter.addWidget(panel_left)

        # Table container
        table_widget = QWidget()
        t_layout = QVBoxLayout(table_widget)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter by Discipline:", objectName="FieldLabel"))
        self.cmb_filter_emp_disc = QComboBox()
        self.cmb_filter_emp_disc.addItem("All Disciplines", None)
        self.cmb_filter_emp_disc.currentIndexChanged.connect(self.update_users_views)
        filter_row.addWidget(self.cmb_filter_emp_disc)
        filter_row.addStretch()
        t_layout.addLayout(filter_row)

        self.tbl_employees = QTableWidget(0, 5)
        self.tbl_employees.setHorizontalHeaderLabels(["User ID", "Full Name", "Role", "Discipline", "Actions"])
        setup_modern_table(self.tbl_employees, row_height=46)
        self.tbl_employees.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_employees.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_employees.setColumnWidth(0, 95)
        self.tbl_employees.setColumnWidth(2, 90)
        self.tbl_employees.setColumnWidth(3, 140)
        self.tbl_employees.setColumnWidth(4, 180)
        self.tbl_employees.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        t_layout.addWidget(self.tbl_employees)

        panel_right = CollapsiblePanel("System Users & Heads List", table_widget, horizontal=True)
        self.emp_splitter.addWidget(panel_right)
        self.emp_splitter.setSizes([340, 660])

        layout.addWidget(self.emp_splitter)
        return widget

    def update_users_views(self):
        selected_filter = self.cmb_filter_emp_disc.currentData()
        self.tbl_employees.setRowCount(0)

        # Filter users list
        row_idx = 0
        for u in self.users_data:
            # Admin can only manage HEAD accounts in this view (B5)
            if self.user["role"] == ROLE_ADMIN and u.get("role") != ROLE_HEAD:
                continue

            u_disc = u.get("discipline_id")
            if selected_filter and u_disc != selected_filter:
                continue

            self.tbl_employees.insertRow(row_idx)
            self.tbl_employees.setItem(row_idx, 0, create_table_item(u["user_id"], Qt.AlignCenter))
            self.tbl_employees.setItem(row_idx, 1, create_table_item(u.get("full_name") or u["user_id"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_employees.setItem(row_idx, 2, create_table_item(u.get("role", "HEAD"), Qt.AlignCenter))

            # Discipline item - highlight if None (A3)
            disc_display = u.get("discipline_name") or u.get("discipline_id")
            disc_item = create_table_item(disc_display or "NO DISCIPLINE ASSIGNED", Qt.AlignLeft | Qt.AlignVCenter)
            if not disc_display:
                disc_item.setForeground(Qt.red)
            self.tbl_employees.setItem(row_idx, 3, disc_item)

            btn_edit = QPushButton("Edit")
            btn_edit.clicked.connect(lambda _, uid=u["user_id"]: self.on_edit_employee(uid))
            btn_rst = QPushButton("Reset Pass")
            btn_rst.clicked.connect(lambda _, uid=u["user_id"]: self.on_reset_password(uid))

            self.tbl_employees.setCellWidget(row_idx, 4, create_table_action_cell([btn_edit, btn_rst]))
            row_idx += 1

    def on_add_employee(self):
        emp_id = self.txt_emp_id.text().strip()
        emp_name = self.txt_emp_name.text().strip()
        disc_id = self.cmb_emp_disc.currentData()

        if not emp_id or not emp_name:
            QMessageBox.warning(self, "Error", "User ID and Full Name are required.")
            return
        if not disc_id:
            QMessageBox.warning(self, "Error", "Discipline is required for Head accounts.")
            return

        def created(_reply):
            self.txt_emp_id.clear()
            self.txt_emp_name.clear()
        self.mutate("CREATE_USER", {"user_id": emp_id, "full_name": emp_name, "role": ROLE_HEAD, "discipline_id": disc_id},
                    f"Head account '{emp_name}' created. Initial password is the User ID.", created,
                    "Could Not Create Account")

    def on_edit_employee(self, user_id: str):
        target = next((u for u in self.users_data if u["user_id"] == user_id), None)
        if not target:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Head - {user_id}")
        dialog.setFixedSize(380, 240)
        d_layout = QVBoxLayout(dialog)

        d_layout.addWidget(QLabel("Full Name:", objectName="FieldLabel"))
        txt_name = QLineEdit(dialog)
        txt_name.setText(target.get("full_name") or "")
        d_layout.addWidget(txt_name)

        d_layout.addWidget(QLabel("Discipline:", objectName="FieldLabel"))
        cmb_disc = QComboBox(dialog)
        for d in self.disciplines_data:
            if not d.get("is_hidden"):
                cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
        idx = cmb_disc.findData(target.get("discipline_id"))
        if idx >= 0:
            cmb_disc.setCurrentIndex(idx)
        d_layout.addWidget(cmb_disc)

        btn_save = QPushButton("Save Changes", dialog)
        btn_save.clicked.connect(lambda: dialog.accept())
        d_layout.addWidget(btn_save)

        if dialog.exec() == QDialog.Accepted:
            new_name = txt_name.text().strip()
            new_disc = cmb_disc.currentData()
            self.mutate("UPDATE_USER", {"user_id": user_id, "full_name": new_name, "discipline_id": new_disc},
                        f"Updated user '{user_id}'.", error_title="Could Not Update Account")

    def on_reset_password(self, user_id: str):
        confirm = QMessageBox.question(
            self, "Confirm Password Reset",
            f"Reset password for user '{user_id}' back to their User ID?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.mutate("RESET_PASSWORD", {"user_id": user_id},
                        f"Password for '{user_id}' was reset to the User ID (must be changed at next login).",
                        lambda r: self.reload_all_data(), "Could Not Reset Password")

    # ------------------- TAB 2: PROJECTS MANAGEMENT -------------------
    def create_project_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        self.prj_splitter = QSplitter(Qt.Horizontal, widget)

        # Form container
        form_w = QWidget()
        f_layout = QVBoxLayout(form_w)
        f_layout.addWidget(QLabel("Add New Project", objectName="SubTitle"))

        f_layout.addWidget(QLabel("Project ID (e.g. PRJ-03):", objectName="FieldLabel"))
        self.txt_prj_id = QLineEdit()
        f_layout.addWidget(self.txt_prj_id)

        f_layout.addWidget(QLabel("Project Name:", objectName="FieldLabel"))
        self.txt_prj_name = QLineEdit()
        f_layout.addWidget(self.txt_prj_name)

        f_layout.addWidget(QLabel("Description:", objectName="FieldLabel"))
        self.txt_prj_desc = QLineEdit()
        f_layout.addWidget(self.txt_prj_desc)

        btn_add = QPushButton("Add Project")
        btn_add.clicked.connect(self.on_add_project)
        f_layout.addWidget(btn_add)
        f_layout.addStretch()

        panel_left = CollapsiblePanel("New Project", form_w, horizontal=True)
        self.prj_splitter.addWidget(panel_left)

        # Table container
        tbl_w = QWidget()
        t_layout = QVBoxLayout(tbl_w)
        t_layout.addWidget(QLabel("Active & Archived Projects", objectName="SubTitle"))

        self.tbl_projects = QTableWidget(0, 4)
        self.tbl_projects.setHorizontalHeaderLabels(["ID", "Name", "Status", "Actions"])
        setup_modern_table(self.tbl_projects, row_height=46)
        self.tbl_projects.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_projects.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_projects.setColumnWidth(0, 95)
        self.tbl_projects.setColumnWidth(2, 120)
        self.tbl_projects.setColumnWidth(3, 190)
        self.tbl_projects.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        t_layout.addWidget(self.tbl_projects)

        panel_right = CollapsiblePanel("Projects Directory", tbl_w, horizontal=True)
        self.prj_splitter.addWidget(panel_right)
        self.prj_splitter.setSizes([340, 660])

        layout.addWidget(self.prj_splitter)
        return widget

    def update_projects_views(self):
        self.tbl_projects.setRowCount(0)
        prev_task_prj = self.cmb_task_prj.currentData()
        prev_timeline_prj = self.cmb_timeline_prj.currentData() if hasattr(self, "cmb_timeline_prj") else None
        self.cmb_task_prj.blockSignals(True)
        self.cmb_task_prj.clear()
        if hasattr(self, "cmb_timeline_prj"):
            self.cmb_timeline_prj.blockSignals(True)
            self.cmb_timeline_prj.clear()
        self.cmb_export_prj.clear()
        self.cmb_export_prj.addItem("All Projects", None)

        for r_idx, p in enumerate(self.projects_data):
            self.tbl_projects.insertRow(r_idx)
            self.tbl_projects.setItem(r_idx, 0, create_table_item(p["project_id"], Qt.AlignCenter))
            self.tbl_projects.setItem(r_idx, 1, create_table_item(p["name"], Qt.AlignLeft | Qt.AlignVCenter))

            st_str = "Hidden / Archived" if p.get("is_hidden") else "Active"
            self.tbl_projects.setItem(r_idx, 2, create_table_item(st_str, Qt.AlignCenter))

            btn_hide = QPushButton("Unhide" if p.get("is_hidden") else "Hide")
            btn_hide.clicked.connect(lambda _, pid=p["project_id"], h=p.get("is_hidden", 0): self.on_toggle_hide_project(pid, h))
            btn_del = QPushButton("Delete")
            btn_del.setObjectName("DangerButton")
            btn_del.clicked.connect(lambda _, pid=p["project_id"], pn=p["name"]: self.on_delete_project(pid, pn))
            self.tbl_projects.setCellWidget(r_idx, 3, create_table_action_cell([btn_hide, btn_del]))

            if not p.get("is_hidden"):
                self.cmb_task_prj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
                if hasattr(self, "cmb_timeline_prj"):
                    self.cmb_timeline_prj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
            self.cmb_export_prj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])

        idx = self.cmb_task_prj.findData(prev_task_prj)
        self.cmb_task_prj.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_task_prj.blockSignals(False)
        if hasattr(self, "cmb_timeline_prj"):
            idx = self.cmb_timeline_prj.findData(prev_timeline_prj)
            self.cmb_timeline_prj.setCurrentIndex(idx if idx >= 0 else 0)
            self.cmb_timeline_prj.blockSignals(False)
        self.update_tasks_views()
        self.on_timeline_project_selected()

    def on_add_project(self):
        pid = self.txt_prj_id.text().strip()
        pname = self.txt_prj_name.text().strip()
        pdesc = self.txt_prj_desc.text().strip()
        if not pid or not pname:
            QMessageBox.warning(self, "Error", "Project ID and Name are required.")
            return
        def added(_reply):
            self.txt_prj_id.clear()
            self.txt_prj_name.clear()
            self.txt_prj_desc.clear()
        self.mutate("ADD_PROJECT", {"project_id": pid, "name": pname, "description": pdesc},
                    f"Project '{pname}' added.", added, "Could Not Add Project")

    def on_delete_project(self, project_id: str, name: str):
        confirm = QMessageBox.question(
            self, "Delete Project",
            f"Delete project '{name}' ({project_id})?\n\n"
            "It and all its tasks will disappear from every screen. Their progress logs stay in the "
            "database and in Excel exports (marked Deleted). This cannot be undone from the app.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.mutate("DELETE_PROJECT", {"project_id": project_id}, f"Project '{name}' deleted.",
                        error_title="Could Not Delete Project")

    def on_delete_task(self, task_id: str, name: str):
        confirm = QMessageBox.question(
            self, "Delete Task",
            f"Delete task '{name}' ({task_id})?\n\n"
            "It will disappear from every screen. Its progress logs stay in the database and in Excel "
            "exports (marked Deleted). This cannot be undone from the app.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.mutate("DELETE_TASK", {"task_id": task_id}, f"Task '{name}' deleted.",
                        error_title="Could Not Delete Task")

    def on_toggle_hide_project(self, project_id: str, current_hidden: int):
        self.mutate("TOGGLE_HIDE_PROJECT", {"project_id": project_id, "current_hidden": current_hidden},
                    "Project visibility updated.")

    # ------------------- TAB 3: TASKS & DISCIPLINES TAB (A1, A2) -------------------
    def create_task_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.task_subtabs = QTabWidget(widget)
        self.task_subtabs.addTab(self.create_tasks_by_discipline_subtab(), "Tasks by Discipline")
        self.task_subtabs.addTab(self.create_pending_proposals_subtab(), "Pending Approvals")
        self.task_subtabs.addTab(self.create_pending_date_changes_subtab(), "Date Change Requests")
        self.task_subtabs.addTab(self.create_disciplines_management_subtab(), "Disciplines Management")

        layout.addWidget(self.task_subtabs)
        return widget

    def create_tasks_by_discipline_subtab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Top Project Selector (A1)
        top_prj_row = QHBoxLayout()
        top_prj_row.addWidget(QLabel("Select Project:", objectName="FieldLabel"))
        self.cmb_task_prj = QComboBox()
        self.cmb_task_prj.currentIndexChanged.connect(self.update_tasks_views)
        top_prj_row.addWidget(self.cmb_task_prj)

        btn_new_task = QPushButton("+ Add New Task Directly")
        btn_new_task.clicked.connect(self.on_open_create_task_dialog)
        top_prj_row.addWidget(btn_new_task)
        top_prj_row.addStretch()
        layout.addLayout(top_prj_row)

        # Tab bar with one tab per active discipline (A1)
        self.tabs_disciplines = QTabWidget()
        self.tabs_disciplines.currentChanged.connect(self.on_discipline_tab_changed)
        layout.addWidget(self.tabs_disciplines)

        return widget

    def on_open_create_task_dialog(self):
        p_id = self.cmb_task_prj.currentData()
        if not p_id:
            QMessageBox.warning(self, "Error", "Please select a Project first.")
            return

        # Determine currently selected discipline tab so dialog opens with it pre-selected
        curr_tab_idx = self.tabs_disciplines.currentIndex()
        curr_tab_text = self.tabs_disciplines.tabText(curr_tab_idx) if curr_tab_idx >= 0 else ""
        curr_disc_name = curr_tab_text.split(" (")[0].strip() if " (" in curr_tab_text else curr_tab_text.strip()

        dlg = QDialog(self)
        dlg.setWindowTitle("Create New Task & Assign to Head")
        dlg.setMinimumSize(500, 460)
        d_layout = QVBoxLayout(dlg)
        d_layout.setContentsMargins(22, 20, 22, 20)
        d_layout.setSpacing(12)

        title = QLabel(f"Add New Task - {self.cmb_task_prj.currentText()}", dlg)
        title.setObjectName("SubTitle")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        d_layout.addWidget(title)

        d_layout.addWidget(QLabel("Task Name (Required):", objectName="FieldLabel"))
        txt_name = QLineEdit(dlg)
        txt_name.setPlaceholderText("e.g. Electrical Main Distribution Board Wiring")
        d_layout.addWidget(txt_name)

        d_layout.addWidget(QLabel("Discipline (Required):", objectName="FieldLabel"))
        cmb_disc = QComboBox(dlg)
        sel_idx = 0
        active_discs = [d for d in self.disciplines_data if not d.get("is_hidden")]
        for idx, d in enumerate(active_discs):
            cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
            if d["name"] == curr_disc_name or d["discipline_id"] == curr_disc_name:
                sel_idx = idx
        cmb_disc.setCurrentIndex(sel_idx)
        d_layout.addWidget(cmb_disc)

        d_layout.addWidget(QLabel("Assign to Specific Head (Optional):", objectName="FieldLabel"))
        cmb_head = QComboBox(dlg)
        d_layout.addWidget(cmb_head)

        def update_head_options():
            cmb_head.clear()
            sel_disc = cmb_disc.currentData()
            cmb_head.addItem("All Heads in Discipline (Default)", None)
            heads = [
                u for u in self.users_data 
                if u.get("role") == ROLE_HEAD and u.get("discipline_id") == sel_disc
            ]
            for h in heads:
                name_disp = h.get("full_name") or h["user_id"]
                cmb_head.addItem(f"👤 {name_disp} ({h['user_id']})", h["user_id"])

        cmb_disc.currentIndexChanged.connect(update_head_options)
        update_head_options()

        dates_row = QHBoxLayout()
        b1 = QVBoxLayout()
        b1.addWidget(QLabel("Planned Start Date:", objectName="FieldLabel"))
        dt_start = QDateEdit(QDate.currentDate(), dlg)
        dt_start.setCalendarPopup(True)
        b1.addWidget(dt_start)
        dates_row.addLayout(b1)

        b2 = QVBoxLayout()
        b2.addWidget(QLabel("Planned End Date:", objectName="FieldLabel"))
        dt_end = QDateEdit(QDate.currentDate().addDays(7), dlg)
        dt_end.setCalendarPopup(True)
        b2.addWidget(dt_end)
        dates_row.addLayout(b2)
        d_layout.addLayout(dates_row)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", dlg)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_add = QPushButton("Create & Assign Task", dlg)
        btn_row.addWidget(btn_add)
        d_layout.addLayout(btn_row)

        # In-dialog validation: do NOT close dialog if invalid!
        def on_create_click():
            t_name = txt_name.text().strip()
            disc_id = cmb_disc.currentData()
            if not t_name:
                QMessageBox.warning(dlg, "Validation Error", "Task Name is required.")
                txt_name.setFocus()
                return
            if not disc_id:
                QMessageBox.warning(dlg, "Validation Error", "Discipline is required.")
                return
            if dt_start.date() > dt_end.date():
                QMessageBox.warning(dlg, "Validation Error", "Planned start date cannot be after end date.")
                return
            dlg.accept()

        btn_add.clicked.connect(on_create_click)

        if dlg.exec() == QDialog.Accepted:
            t_name = txt_name.text().strip()
            disc_id = cmb_disc.currentData()
            head_id = cmb_head.currentData()

            # Record target discipline so update_tasks_views automatically focuses on it
            self._target_disc_after_add = disc_id
            self._last_selected_disc = disc_id

            self.mutate("ADD_TASK", {
                "project_id": p_id,
                "name": t_name,
                "discipline_id": disc_id,
                "assigned_head_id": head_id,
                "planned_start_date": dt_start.date().toString("yyyy-MM-dd"),
                "planned_end_date": dt_end.date().toString("yyyy-MM-dd")
            }, None, lambda r: self.toast.show_message(
                f"Task '{r['task']['name']}' ({r['task']['task_id']}) added."), "Could Not Add Task")

    def update_disciplines_views(self):
        # Update user creation discipline combobox
        self.cmb_emp_disc.clear()
        self.cmb_filter_emp_disc.clear()
        self.cmb_filter_emp_disc.addItem("All Disciplines", None)
        self.cmb_export_disc.clear()
        self.cmb_export_disc.addItem("All Disciplines", None)

        for d in self.disciplines_data:
            if not d.get("is_hidden"):
                self.cmb_emp_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
            self.cmb_filter_emp_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
            self.cmb_export_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])

        self.update_disciplines_management_table()
        self.update_tasks_views()

    def update_tasks_views(self):
        curr_p_id = self.cmb_task_prj.currentData()

        # Remember currently selected tab before clearing
        current_disc = getattr(self, "_target_disc_after_add", None)
        if not current_disc:
            current_disc = getattr(self, "_last_selected_disc", None)
        if not current_disc:
            curr_idx = self.tabs_disciplines.currentIndex()
            if curr_idx >= 0:
                t_title = self.tabs_disciplines.tabText(curr_idx)
                current_disc = t_title.split(" (")[0].strip() if " (" in t_title else t_title.strip()

        # Block signals during rebuild so currentIndexChanged doesn't reset active tab tracking
        self.tabs_disciplines.blockSignals(True)
        self.tabs_disciplines.clear()

        # Build tabs for all active disciplines + "Unassigned" if any task has NULL discipline (A1)
        active_discs = [d for d in self.disciplines_data if not d.get("is_hidden")]
        target_tab_index = 0

        for idx, d in enumerate(active_discs):
            d_id = d["discipline_id"]
            d_name = d["name"]

            # Filter tasks for this project & discipline
            matching_tasks = [
                t for t in self.tasks_data 
                if t.get("project_id") == curr_p_id and t.get("discipline_id") == d_id
            ]

            tbl = self.create_discipline_task_table(matching_tasks)
            self.tabs_disciplines.addTab(tbl, f"{d_name} ({len(matching_tasks)})")

            if current_disc and (current_disc == d_id or current_disc == d_name):
                target_tab_index = idx

        # Check unassigned tasks
        unassigned_tasks = [
            t for t in self.tasks_data
            if t.get("project_id") == curr_p_id and not t.get("discipline_id")
        ]
        if unassigned_tasks:
            tbl_un = self.create_discipline_task_table(unassigned_tasks)
            self.tabs_disciplines.addTab(tbl_un, f"Unassigned ({len(unassigned_tasks)})")
            if current_disc == "Unassigned":
                target_tab_index = self.tabs_disciplines.count() - 1

        if self.tabs_disciplines.count() > 0:
            self.tabs_disciplines.setCurrentIndex(target_tab_index)
        
        self.tabs_disciplines.blockSignals(False)

    def create_discipline_task_table(self, tasks_list: list) -> QTableWidget:
        tbl = QTableWidget(0, 7)
        tbl.setHorizontalHeaderLabels([
            "Task ID", "Task Name", "Discipline", "Assigned Head", "Planned Dates", "Status", "Actions"
        ])
        setup_modern_table(tbl, row_height=46)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tbl.setColumnWidth(0, 95)
        tbl.setColumnWidth(2, 110)
        tbl.setColumnWidth(3, 170)
        tbl.setColumnWidth(4, 185)
        tbl.setColumnWidth(5, 95)
        tbl.setColumnWidth(6, 260)
        tbl.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)

        for r_idx, t in enumerate(tasks_list):
            tbl.insertRow(r_idx)
            tbl.setItem(r_idx, 0, create_table_item(t["task_id"], Qt.AlignCenter))
            tbl.setItem(r_idx, 1, create_table_item(t["name"], Qt.AlignLeft | Qt.AlignVCenter))
            tbl.setItem(r_idx, 2, create_table_item(t.get("discipline_name") or t.get("discipline_id") or "Unassigned", Qt.AlignCenter))

            head_display = t.get("assigned_head_name") or (f"ID: {t['assigned_head_id']}" if t.get("assigned_head_id") else "👥 All Heads (Discipline)")
            tbl.setItem(r_idx, 3, create_table_item(head_display, Qt.AlignLeft | Qt.AlignVCenter))

            p_dates = f"{t.get('planned_start_date') or 'TBD'} ➔ {t.get('planned_end_date') or 'TBD'}"
            tbl.setItem(r_idx, 4, create_table_item(p_dates, Qt.AlignCenter))

            tbl.setItem(r_idx, 5, create_table_item("Hidden" if t.get("is_hidden") else "Active", Qt.AlignCenter))

            btn_edit = QPushButton("Edit Task")
            btn_edit.clicked.connect(lambda _, task=t: self.on_admin_edit_task_details(task))

            btn_hide = QPushButton("Unhide" if t.get("is_hidden") else "Hide")
            btn_hide.clicked.connect(lambda _, tid=t["task_id"], h=t.get("is_hidden", 0): self.on_toggle_hide_task(tid, h))

            btn_del = QPushButton("Delete")
            btn_del.setObjectName("DangerButton")
            btn_del.clicked.connect(lambda _, tid=t["task_id"], tn=t["name"]: self.on_delete_task(tid, tn))

            tbl.setCellWidget(r_idx, 6, create_table_action_cell([btn_edit, btn_hide, btn_del]))

        return tbl

    def on_admin_edit_task_details(self, task: dict):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit Task Details - {task['task_id']}")
        dlg.setMinimumSize(480, 420)
        d_layout = QVBoxLayout(dlg)
        d_layout.setContentsMargins(20, 20, 20, 20)
        d_layout.setSpacing(12)

        title = QLabel(f"Edit Task: {task['name']} ({task['task_id']})", dlg)
        title.setObjectName("SubTitle")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        d_layout.addWidget(title)

        d_layout.addWidget(QLabel("Task Name:", objectName="FieldLabel"))
        txt_name = QLineEdit(dlg)
        txt_name.setText(task.get("name") or "")
        d_layout.addWidget(txt_name)

        d_layout.addWidget(QLabel("Discipline:", objectName="FieldLabel"))
        cmb_disc = QComboBox(dlg)
        curr_disc = task.get("discipline_id")
        disc_idx_to_select = 0
        for idx, d in enumerate(self.disciplines_data):
            if not d.get("is_hidden"):
                cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
                if d["discipline_id"] == curr_disc:
                    disc_idx_to_select = cmb_disc.count() - 1
        cmb_disc.setCurrentIndex(disc_idx_to_select)
        d_layout.addWidget(cmb_disc)

        d_layout.addWidget(QLabel("Assign to Head:", objectName="FieldLabel"))
        cmb_head = QComboBox(dlg)
        d_layout.addWidget(cmb_head)

        def update_head_options():
            cmb_head.clear()
            sel_disc = cmb_disc.currentData()
            cmb_head.addItem("All Heads in Discipline (Default)", None)
            heads = [
                u for u in self.users_data 
                if u.get("role") == ROLE_HEAD and u.get("discipline_id") == sel_disc
            ]
            sel_head_idx = 0
            for h in heads:
                name_disp = h.get("full_name") or h["user_id"]
                cmb_head.addItem(f"👤 {name_disp} ({h['user_id']})", h["user_id"])
                if h["user_id"] == task.get("assigned_head_id"):
                    sel_head_idx = cmb_head.count() - 1
            cmb_head.setCurrentIndex(sel_head_idx)

        cmb_disc.currentIndexChanged.connect(update_head_options)
        update_head_options()

        dates_row = QHBoxLayout()
        b1 = QVBoxLayout()
        b1.addWidget(QLabel("Planned Start Date:", objectName="FieldLabel"))
        s_date_str = task.get("planned_start_date") or datetime.now().strftime("%Y-%m-%d")
        dt_start = QDateEdit(QDate.fromString(s_date_str, "yyyy-MM-dd"), dlg)
        dt_start.setCalendarPopup(True)
        b1.addWidget(dt_start)
        dates_row.addLayout(b1)

        b2 = QVBoxLayout()
        b2.addWidget(QLabel("Planned End Date:", objectName="FieldLabel"))
        e_date_str = task.get("planned_end_date") or datetime.now().strftime("%Y-%m-%d")
        dt_end = QDateEdit(QDate.fromString(e_date_str, "yyyy-MM-dd"), dlg)
        dt_end.setCalendarPopup(True)
        b2.addWidget(dt_end)
        dates_row.addLayout(b2)
        d_layout.addLayout(dates_row)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", dlg)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("Save Changes", dlg)
        btn_save.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_save)
        d_layout.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            new_name = txt_name.text().strip()
            new_disc = cmb_disc.currentData()
            new_head = cmb_head.currentData()
            if not new_name or not new_disc:
                QMessageBox.warning(self, "Error", "Task Name and Discipline cannot be empty.")
                return

            if dt_start.date() > dt_end.date():
                QMessageBox.warning(self, "Error", "Planned start date cannot be after end date.")
                return
            self.mutate("UPDATE_TASK", {
                "task_id": task["task_id"],
                "name": new_name,
                "discipline_id": new_disc,
                "assigned_head_id": new_head,
                "planned_start_date": dt_start.date().toString("yyyy-MM-dd"),
                "planned_end_date": dt_end.date().toString("yyyy-MM-dd")
            }, f"Task '{task['task_id']}' updated.", error_title="Could Not Update Task")

    def on_admin_edit_task_dates(self, task_id: str, old_start: str, old_end: str):
        self.on_admin_edit_task_details({"task_id": task_id, "planned_start_date": old_start, "planned_end_date": old_end})

    # ------------------- TAB 4: PROJECT PROGRESSIVE TIMELINE -------------------
    def create_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Top Project Selector Bar
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Select Project Timeline:", objectName="FieldLabel"))
        self.cmb_timeline_prj = QComboBox()
        self.cmb_timeline_prj.setMinimumWidth(280)
        self.cmb_timeline_prj.currentIndexChanged.connect(self.on_timeline_project_selected)
        top_bar.addWidget(self.cmb_timeline_prj)

        btn_refresh_tl = QPushButton("Refresh Timeline")
        btn_refresh_tl.clicked.connect(self.on_timeline_project_selected)
        top_bar.addWidget(btn_refresh_tl)
        top_bar.addStretch()

        layout.addLayout(top_bar)

        # Progressive Timeline Component
        self.timeline_widget = ProjectProgressiveTimelineWidget()
        layout.addWidget(self.timeline_widget, 1)

        return widget

    def on_timeline_project_selected(self):
        if not hasattr(self, "cmb_timeline_prj"):
            return
        p_id = self.cmb_timeline_prj.currentData()
        if p_id and self.net_client.is_connected:
            self.net_client.call("GET_PROJECT_TIMELINE", {"project_id": p_id},
                                 lambda r: self.timeline_widget.load_timeline_data(r.get("data", {})),
                                 self.on_request_error)
        elif hasattr(self, "timeline_widget"):
            self.timeline_widget.load_timeline_data({})

    def on_toggle_hide_task(self, task_id: str, current_hidden: int):
        self.mutate("TOGGLE_HIDE_TASK", {"task_id": task_id, "current_hidden": current_hidden}, "Task visibility updated.")

    def on_discipline_tab_changed(self, idx: int):
        if idx >= 0 and hasattr(self, "tabs_disciplines"):
            t_title = self.tabs_disciplines.tabText(idx)
            self._last_selected_disc = t_title.split(" (")[0].strip() if " (" in t_title else t_title.strip()

    # ------------------- SUBTAB: PENDING TASK PROPOSALS (A1) -------------------
    def create_pending_proposals_subtab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.tbl_pending_proposals = QTableWidget(0, 7)
        self.tbl_pending_proposals.setHorizontalHeaderLabels([
            "Request ID", "Task Name", "Discipline", "Proposed Schedule", "Proposed By", "Project", "Actions"
        ])
        setup_modern_table(self.tbl_pending_proposals, row_height=46)
        self.tbl_pending_proposals.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_pending_proposals.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_pending_proposals.setColumnWidth(0, 95)
        self.tbl_pending_proposals.setColumnWidth(2, 110)
        self.tbl_pending_proposals.setColumnWidth(3, 185)
        self.tbl_pending_proposals.setColumnWidth(4, 140)
        self.tbl_pending_proposals.setColumnWidth(5, 140)
        self.tbl_pending_proposals.setColumnWidth(6, 180)
        self.tbl_pending_proposals.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        layout.addWidget(self.tbl_pending_proposals)
        return widget

    def update_proposals_views(self, proposals: list):
        pending = [p for p in proposals if p.get("status") == "PENDING"]
        self.task_subtabs.setTabText(1, f"Pending Approvals ({len(pending)})")
        self.tbl_pending_proposals.setRowCount(0)

        for r_idx, p in enumerate(pending):
            self.tbl_pending_proposals.insertRow(r_idx)
            self.tbl_pending_proposals.setItem(r_idx, 0, create_table_item(p["proposal_id"], Qt.AlignCenter))
            self.tbl_pending_proposals.setItem(r_idx, 1, create_table_item(p["task_name"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_pending_proposals.setItem(r_idx, 2, create_table_item(p.get("discipline_name") or p.get("discipline_id") or "General", Qt.AlignCenter))
            p_sched = f"{p.get('planned_start_date') or 'TBD'} ➔ {p.get('planned_end_date') or 'TBD'}"
            self.tbl_pending_proposals.setItem(r_idx, 3, create_table_item(p_sched, Qt.AlignCenter))
            self.tbl_pending_proposals.setItem(r_idx, 4, create_table_item(p.get("proposer_name") or p["proposed_by_id"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_pending_proposals.setItem(r_idx, 5, create_table_item(p.get("project_name") or p["project_id"], Qt.AlignLeft | Qt.AlignVCenter))

            btn_app = QPushButton("Approve")
            btn_app.setObjectName("SuccessButton")
            btn_app.clicked.connect(lambda _, pid=p["proposal_id"]: self.on_approve_proposal(pid))

            btn_rej = QPushButton("Reject")
            btn_rej.setObjectName("DangerButton")
            btn_rej.clicked.connect(lambda _, pid=p["proposal_id"]: self.on_reject_proposal(pid))

            self.tbl_pending_proposals.setCellWidget(r_idx, 6, create_table_action_cell([btn_app, btn_rej]))

    def on_approve_proposal(self, proposal_id: str):
        self.mutate("APPROVE_TASK_PROPOSAL", {"proposal_id": proposal_id},
                    "Proposal approved and task created.", error_title="Could Not Approve")

    def on_reject_proposal(self, proposal_id: str):
        reason, ok = QInputDialog.getText(self, "Reject Task Proposal", "Enter mandatory rejection reason:")
        if ok and reason.strip():
            self.mutate("REJECT_TASK_PROPOSAL", {"proposal_id": proposal_id, "reason": reason.strip()},
                        "Proposal rejected.", lambda r: self.reload_all_data(), "Could Not Reject")
        elif ok:
            QMessageBox.warning(self, "Error", "A rejection reason is mandatory.")

    # ------------------- SUBTAB: DATE CHANGE REQUESTS (A2) -------------------
    def create_pending_date_changes_subtab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.tbl_pending_date_changes = QTableWidget(0, 7)
        self.tbl_pending_date_changes.setHorizontalHeaderLabels([
            "Request ID", "Task Name", "Current Schedule", "Requested Schedule", "Reason", "Requested By", "Actions"
        ])
        setup_modern_table(self.tbl_pending_date_changes, row_height=46)
        self.tbl_pending_date_changes.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_pending_date_changes.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_pending_date_changes.setColumnWidth(0, 95)
        self.tbl_pending_date_changes.setColumnWidth(2, 175)
        self.tbl_pending_date_changes.setColumnWidth(3, 175)
        self.tbl_pending_date_changes.setColumnWidth(4, 150)
        self.tbl_pending_date_changes.setColumnWidth(5, 130)
        self.tbl_pending_date_changes.setColumnWidth(6, 180)
        self.tbl_pending_date_changes.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        layout.addWidget(self.tbl_pending_date_changes)
        return widget

    def update_date_change_views(self, requests: list):
        pending = [r for r in requests if r.get("status") == "PENDING"]
        self.task_subtabs.setTabText(2, f"Date Change Requests ({len(pending)})")
        self.tbl_pending_date_changes.setRowCount(0)

        for r_idx, req in enumerate(pending):
            self.tbl_pending_date_changes.insertRow(r_idx)
            self.tbl_pending_date_changes.setItem(r_idx, 0, create_table_item(req["request_id"], Qt.AlignCenter))
            self.tbl_pending_date_changes.setItem(r_idx, 1, create_table_item(f"{req.get('task_name')} ({req['task_id']})", Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_pending_date_changes.setItem(r_idx, 2, create_table_item(f"{req.get('old_start_date')} ➔ {req.get('old_end_date')}", Qt.AlignCenter))
            self.tbl_pending_date_changes.setItem(r_idx, 3, create_table_item(f"{req['new_start_date']} ➔ {req['new_end_date']}", Qt.AlignCenter))
            self.tbl_pending_date_changes.setItem(r_idx, 4, create_table_item(req["reason"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_pending_date_changes.setItem(r_idx, 5, create_table_item(req.get("requester_name") or req["requested_by_id"], Qt.AlignLeft | Qt.AlignVCenter))

            btn_app = QPushButton("Approve")
            btn_app.setObjectName("SuccessButton")
            btn_app.clicked.connect(lambda _, rid=req["request_id"]: self.on_approve_date_change(rid))

            btn_rej = QPushButton("Reject")
            btn_rej.setObjectName("DangerButton")
            btn_rej.clicked.connect(lambda _, rid=req["request_id"]: self.on_reject_date_change(rid))

            self.tbl_pending_date_changes.setCellWidget(r_idx, 6, create_table_action_cell([btn_app, btn_rej]))

    def on_approve_date_change(self, request_id: str):
        self.mutate("APPROVE_DATE_CHANGE", {"request_id": request_id},
                    "Date change approved and task schedule updated.", error_title="Could Not Approve")

    def on_reject_date_change(self, request_id: str):
        reason, ok = QInputDialog.getText(self, "Reject Date Change", "Enter mandatory rejection reason:")
        if ok and reason.strip():
            self.mutate("REJECT_DATE_CHANGE", {"request_id": request_id, "reason": reason.strip()},
                        "Date change request rejected.", lambda r: self.reload_all_data(), "Could Not Reject")
        elif ok:
            QMessageBox.warning(self, "Error", "A rejection reason is mandatory.")

    # ------------------- SUBTAB: DISCIPLINES MANAGEMENT (A1) -------------------
    def create_disciplines_management_subtab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        form_w = QWidget()
        f_layout = QVBoxLayout(form_w)
        f_layout.addWidget(QLabel("Add New Discipline", objectName="SubTitle"))

        f_layout.addWidget(QLabel("Discipline ID / Code (e.g. ELE):", objectName="FieldLabel"))
        self.txt_disc_id = QLineEdit()
        f_layout.addWidget(self.txt_disc_id)

        f_layout.addWidget(QLabel("Discipline Name:", objectName="FieldLabel"))
        self.txt_disc_name = QLineEdit()
        f_layout.addWidget(self.txt_disc_name)

        btn_add = QPushButton("Add Discipline")
        btn_add.clicked.connect(self.on_add_discipline)
        f_layout.addWidget(btn_add)
        f_layout.addStretch()

        p_left = CollapsiblePanel("Add Discipline", form_w, horizontal=True)

        tbl_w = QWidget()
        t_layout = QVBoxLayout(tbl_w)
        t_layout.addWidget(QLabel("System Disciplines Directory", objectName="SubTitle"))

        self.tbl_disciplines = QTableWidget(0, 4)
        self.tbl_disciplines.setHorizontalHeaderLabels(["ID", "Name", "Status", "Actions"])
        setup_modern_table(self.tbl_disciplines, row_height=46)
        self.tbl_disciplines.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_disciplines.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_disciplines.setColumnWidth(0, 95)
        self.tbl_disciplines.setColumnWidth(2, 110)
        self.tbl_disciplines.setColumnWidth(3, 110)
        self.tbl_disciplines.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        t_layout.addWidget(self.tbl_disciplines)

        p_right = CollapsiblePanel("Disciplines Directory", tbl_w, horizontal=True)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(p_left)
        splitter.addWidget(p_right)
        splitter.setSizes([340, 660])
        layout.addWidget(splitter)
        return widget

    def update_disciplines_management_table(self):
        self.tbl_disciplines.setRowCount(0)
        for r_idx, d in enumerate(self.disciplines_data):
            self.tbl_disciplines.insertRow(r_idx)
            self.tbl_disciplines.setItem(r_idx, 0, create_table_item(d["discipline_id"], Qt.AlignCenter))
            self.tbl_disciplines.setItem(r_idx, 1, create_table_item(d["name"], Qt.AlignLeft | Qt.AlignVCenter))

            st = "Hidden" if d.get("is_hidden") else "Active"
            self.tbl_disciplines.setItem(r_idx, 2, create_table_item(st, Qt.AlignCenter))

            btn_hide = QPushButton("Unhide" if d.get("is_hidden") else "Hide")
            btn_hide.clicked.connect(lambda _, did=d["discipline_id"], h=d.get("is_hidden", 0): self.on_toggle_hide_discipline(did, h))
            self.tbl_disciplines.setCellWidget(r_idx, 3, create_table_action_cell([btn_hide]))

    def on_add_discipline(self):
        did = self.txt_disc_id.text().strip().upper()
        dname = self.txt_disc_name.text().strip()
        if not did or not dname:
            QMessageBox.warning(self, "Error", "Discipline ID and Name are required.")
            return
        def added(_reply):
            self.txt_disc_id.clear()
            self.txt_disc_name.clear()
        self.mutate("ADD_DISCIPLINE", {"discipline_id": did, "name": dname},
                    f"Discipline '{dname}' added.", added, "Could Not Add Discipline")

    def on_toggle_hide_discipline(self, disc_id: str, current_hidden: int):
        self.mutate("TOGGLE_HIDE_DISCIPLINE", {"discipline_id": disc_id, "current_hidden": current_hidden},
                    "Discipline visibility updated.")

    # ------------------- TAB 4: ANALYSIS TAB -------------------
    def create_analysis_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)

        self.kpi_logs = KpiMetricCard("Total Logs", "0", "📋", "#8B5CF6", "Recorded by team")
        self.kpi_revs = KpiMetricCard("Total Revisions", "0", "🔄", "#F59E0B", "Rework iterations")
        self.kpi_prjs = KpiMetricCard("Active Projects", "0", "📁", "#10B981", "Currently active")
        self.kpi_emps = KpiMetricCard("Active Heads", "0", "👥", "#3B82F6", "Supervising disciplines")

        metrics_row.addWidget(self.kpi_logs)
        metrics_row.addWidget(self.kpi_revs)
        metrics_row.addWidget(self.kpi_prjs)
        metrics_row.addWidget(self.kpi_emps)
        layout.addLayout(metrics_row)

        splitter = QSplitter(Qt.Horizontal)

        # Left: Employee breakdown
        c_emp = QFrame(splitter)
        c_emp.setObjectName("CardFrame")
        ce_l = QVBoxLayout(c_emp)
        ce_l.setContentsMargins(10, 10, 10, 10)
        ce_l.addWidget(QLabel("Employee Rework & Revisions", objectName="SubTitle"))
        self.tbl_emp_analysis = QTableWidget(0, 6)
        self.tbl_emp_analysis.setHorizontalHeaderLabels([
            "User ID", "Full Name", "Discipline", "Logs", "New", "Revisions"
        ])
        setup_modern_table(self.tbl_emp_analysis, row_height=42, min_col_width=75)
        self.tbl_emp_analysis.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_emp_analysis.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_emp_analysis.setColumnWidth(0, 85)
        self.tbl_emp_analysis.setColumnWidth(2, 115)
        self.tbl_emp_analysis.setColumnWidth(3, 70)
        self.tbl_emp_analysis.setColumnWidth(4, 70)
        self.tbl_emp_analysis.setColumnWidth(5, 80)
        ce_l.addWidget(self.tbl_emp_analysis)
        splitter.addWidget(c_emp)

        # Right: Project breakdown
        c_prj = QFrame(splitter)
        c_prj.setObjectName("CardFrame")
        cp_l = QVBoxLayout(c_prj)
        cp_l.setContentsMargins(10, 10, 10, 10)
        cp_l.addWidget(QLabel("Project Progress Breakdown", objectName="SubTitle"))
        self.tbl_prj_analysis = QTableWidget(0, 6)
        self.tbl_prj_analysis.setHorizontalHeaderLabels([
            "Project ID", "Project Name", "Tasks", "Done", "In Progress", "Revisions"
        ])
        setup_modern_table(self.tbl_prj_analysis, row_height=42, min_col_width=75)
        self.tbl_prj_analysis.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_prj_analysis.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_prj_analysis.setColumnWidth(0, 90)
        self.tbl_prj_analysis.setColumnWidth(2, 65)
        self.tbl_prj_analysis.setColumnWidth(3, 65)
        self.tbl_prj_analysis.setColumnWidth(4, 90)
        self.tbl_prj_analysis.setColumnWidth(5, 80)
        cp_l.addWidget(self.tbl_prj_analysis)
        splitter.addWidget(c_prj)

        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)
        return widget

    def update_analytics_views(self, data: dict):
        self.kpi_logs.set_value(data.get("total_logs", 0))
        self.kpi_revs.set_value(data.get("total_revisions", 0))
        self.kpi_prjs.set_value(data.get("active_projects", 0))
        self.kpi_emps.set_value(data.get("active_employees", 0))

        # Employee breakdown
        self.tbl_emp_analysis.setRowCount(0)
        for r_idx, s in enumerate(data.get("employee_breakdown", [])):
            self.tbl_emp_analysis.insertRow(r_idx)
            self.tbl_emp_analysis.setItem(r_idx, 0, create_table_item(s["user_id"], Qt.AlignCenter))
            self.tbl_emp_analysis.setItem(r_idx, 1, create_table_item(s.get("full_name") or s["user_id"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_emp_analysis.setItem(r_idx, 2, create_table_item(s.get("discipline_name") or s.get("discipline_id") or "Unassigned", Qt.AlignCenter))
            self.tbl_emp_analysis.setItem(r_idx, 3, create_table_item(str(s["total_logs"]), Qt.AlignCenter))
            self.tbl_emp_analysis.setItem(r_idx, 4, create_table_item(str(s["new_logs"]), Qt.AlignCenter))
            self.tbl_emp_analysis.setItem(r_idx, 5, create_table_item(str(s["rev_logs"]), Qt.AlignCenter))

        # Project breakdown
        self.tbl_prj_analysis.setRowCount(0)
        for r_idx, p in enumerate(data.get("project_breakdown", [])):
            self.tbl_prj_analysis.insertRow(r_idx)
            self.tbl_prj_analysis.setItem(r_idx, 0, create_table_item(p["project_id"], Qt.AlignCenter))
            self.tbl_prj_analysis.setItem(r_idx, 1, create_table_item(p["project_name"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_prj_analysis.setItem(r_idx, 2, create_table_item(str(p["total_tasks"]), Qt.AlignCenter))
            self.tbl_prj_analysis.setItem(r_idx, 3, create_table_item(str(p["done_count"]), Qt.AlignCenter))
            self.tbl_prj_analysis.setItem(r_idx, 4, create_table_item(str(p["in_prog_count"]), Qt.AlignCenter))
            self.tbl_prj_analysis.setItem(r_idx, 5, create_table_item(str(p["total_revisions"]), Qt.AlignCenter))

    # ------------------- TAB 5: EXCEL EXPORT (A4, B2) -------------------
    def create_export_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        card = QFrame()
        card.setObjectName("CardFrame")
        c_layout = QVBoxLayout(card)
        c_layout.addWidget(QLabel("Export Progress Logs with Discipline Categorization (A4)", objectName="SubTitle"))

        filters_grid = QHBoxLayout()

        b_p = QVBoxLayout()
        b_p.addWidget(QLabel("Project Filter:", objectName="FieldLabel"))
        self.cmb_export_prj = QComboBox()
        b_p.addWidget(self.cmb_export_prj)
        filters_grid.addLayout(b_p)

        b_d = QVBoxLayout()
        b_d.addWidget(QLabel("Discipline Filter:", objectName="FieldLabel"))
        self.cmb_export_disc = QComboBox()
        self.cmb_export_disc.currentIndexChanged.connect(self.update_export_heads_filter)
        b_d.addWidget(self.cmb_export_disc)
        filters_grid.addLayout(b_d)

        b_h = QVBoxLayout()
        b_h.addWidget(QLabel("Head Employee Filter:", objectName="FieldLabel"))
        self.cmb_export_head = QComboBox()
        self.cmb_export_head.addItem("All Heads", None)
        b_h.addWidget(self.cmb_export_head)
        filters_grid.addLayout(b_h)

        c_layout.addLayout(filters_grid)

        self.btn_export = QPushButton("Export Categorized Excel Report")
        self.btn_export.setMinimumHeight(44)
        self.btn_export.clicked.connect(self.on_request_excel_export)
        c_layout.addWidget(self.btn_export)

        c_layout.addStretch()
        layout.addWidget(card)
        return widget

    def update_export_heads_filter(self):
        selected_disc = self.cmb_export_disc.currentData()
        self.cmb_export_head.clear()
        self.cmb_export_head.addItem("All Heads", None)
        for u in self.users_data:
            if u.get("role") == ROLE_HEAD:
                if not selected_disc or u.get("discipline_id") == selected_disc:
                    self.cmb_export_head.addItem(f"{u.get('full_name') or u['user_id']} ({u['user_id']})", u["user_id"])

    def on_request_excel_export(self):
        filters = {
            "project_id": self.cmb_export_prj.currentData(),
            "discipline_id": self.cmb_export_disc.currentData(),
            "employee_id": self.cmb_export_head.currentData(),
        }
        self.btn_export.setEnabled(False)
        self.toast.show_message("Generating the Excel report on the Central Server...", duration_ms=10000)
        run_async(self.net_client.export_excel(filters), self._on_export_ready, self._on_export_failed)

    def _on_export_failed(self, exc):
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "Export Error", describe_error(exc))

    def _on_export_ready(self, result):
        self.btn_export.setEnabled(True)
        raw_bytes, default_name = result
        save_excel_report(self, raw_bytes, default_name)

    def on_task_proposal_event(self, data: dict):
        prop = data.get("proposal", {})
        if data.get("type") == "NEW_TASK_PROPOSAL_EVENT":
            self.toast.show_message(f"New task request from {prop.get('proposed_by_id')}: '{prop.get('task_name')}'.")

    def on_task_date_change_event(self, data: dict):
        if data.get("event") == "CREATED":
            self.toast.show_message(f"New date change request for task {data.get('request', {}).get('task_id')}.")

    def restore_layout(self):
        w = max(self.width(), 1050)
        defaults = [int(w * 0.382), int(w * 0.618)]
        settings = app_settings("AdminWorkspace")
        uid = self.user["user_id"]
        restore_splitter(self.emp_splitter, settings, f"{uid}/emp_splitter_sizes", defaults)
        restore_splitter(self.prj_splitter, settings, f"{uid}/prj_splitter_sizes", defaults)

    def save_layout(self):
        settings = app_settings("AdminWorkspace")
        uid = self.user["user_id"]
        settings.setValue(f"{uid}/emp_splitter_sizes", self.emp_splitter.sizes())
        settings.setValue(f"{uid}/prj_splitter_sizes", self.prj_splitter.sizes())


class AdminWorkspace(RoleWindow):
    def __init__(self, user_dict: dict, net_client: NetworkClient):
        name = user_dict.get("full_name") or user_dict["user_id"]
        super().__init__(f"Admin Workspace - {name}", f"Admin Control Center - {name}",
                         AdminPanel(user_dict, net_client))


def save_excel_report(parent, raw_bytes: bytes, default_name: str):
    """Ask where to save a server-generated workbook and write it."""
    file_path, _ = QFileDialog.getSaveFileName(parent, "Save Excel Report", default_name, "Excel Files (*.xlsx)")
    if not file_path:
        return
    try:
        with open(file_path, "wb") as f:
            f.write(raw_bytes)
    except OSError as e:
        QMessageBox.critical(parent, "Save Failed", f"Could not save the report:\n{e}")
        return
    QMessageBox.information(parent, "Success", f"Excel report saved to:\n{file_path}")
