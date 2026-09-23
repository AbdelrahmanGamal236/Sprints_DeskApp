from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QListWidget, QListWidgetItem, 
    QComboBox, QTabWidget, QMessageBox, QFileDialog, QTableWidget, 
    QTableWidgetItem, QHeaderView
)
from app.core.config import ROLE_HEAD
from app.core.auth import hash_password
from app.database.db_manager import DBManager
from app.network.client import NetworkClient
from app.services.excel_service import ExcelExportService
from app.ui.components import ToastNotifier, CopyrightFooter

class AdminWorkspace(QMainWindow):
    """Admin Management Workspace."""
    def __init__(self, user_dict: dict, db_manager: DBManager, net_client: NetworkClient):
        super().__init__()
        self.user = user_dict
        self.db = db_manager
        self.net_client = net_client
        self.excel_service = ExcelExportService(self.db)
        self.logout_requested = False

        self.setWindowTitle(f"Admin Workspace - {self.user['user_id']}")
        self.setMinimumSize(950, 680)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header
        top_bar = QHBoxLayout()
        header = QLabel("Admin Workspace", self)
        header.setObjectName("HeaderTitle")
        top_bar.addWidget(header)
        top_bar.addStretch()

        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)

        main_layout.addLayout(top_bar)

        self.toast = ToastNotifier(self)
        main_layout.addWidget(self.toast)

        # Tab Widget
        tabs = QTabWidget(self)

        # Tab 1: Employee Management
        tabs.addTab(self.create_employee_tab(), "Manage Employees")

        # Tab 2: Project Management
        tabs.addTab(self.create_project_tab(), "Manage Projects")

        # Tab 3: Task Management
        tabs.addTab(self.create_task_tab(), "Manage Tasks")

        # Tab 4: Excel Export
        tabs.addTab(self.create_export_tab(), "Excel Reports")

        main_layout.addWidget(tabs)
        main_layout.addWidget(CopyrightFooter(self))
        self.reload_all_data()

    # ------------------- EMPLOYEE TAB -------------------
    def create_employee_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # Left: Form
        form_card = QFrame()
        form_card.setObjectName("CardFrame")
        f_layout = QVBoxLayout(form_card)

        f_layout.addWidget(QLabel("Add New Employee", objectName="SubTitle"))

        f_layout.addWidget(QLabel("Employee ID / Badge Number:", objectName="FieldLabel"))
        self.txt_emp_id = QLineEdit()
        self.txt_emp_id.setPlaceholderText("e.g. 1002, 1003")
        f_layout.addWidget(self.txt_emp_id)

        btn_add_emp = QPushButton("Add Employee")
        btn_add_emp.clicked.connect(self.on_add_employee)
        f_layout.addWidget(btn_add_emp)
        f_layout.addStretch()

        # Right: List
        list_card = QFrame()
        list_card.setObjectName("CardFrame")
        l_layout = QVBoxLayout(list_card)
        l_layout.addWidget(QLabel("Existing Employees (Head)", objectName="SubTitle"))

        self.tbl_employees = QTableWidget(0, 3)
        self.tbl_employees.setHorizontalHeaderLabels(["Employee ID", "Role", "Actions"])
        self.tbl_employees.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        l_layout.addWidget(self.tbl_employees)

        layout.addWidget(form_card, 1)
        layout.addWidget(list_card, 2)
        return widget

    def on_add_employee(self):
        emp_id = self.txt_emp_id.text().strip()
        if not emp_id:
            QMessageBox.warning(self, "Error", "Employee ID cannot be empty.")
            return

        pwd_hash, pwd_salt = hash_password(emp_id) # Initial password = ID
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (emp_id,))
            if cursor.fetchone():
                QMessageBox.warning(self, "Error", f"User ID '{emp_id}' already exists.")
                return

            cursor.execute("""
            INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password)
            VALUES (?, ?, ?, ?, 1)
            """, (emp_id, pwd_hash, pwd_salt, ROLE_HEAD))
            conn.commit()

        self.txt_emp_id.clear()
        self.toast.show_message(f"Employee '{emp_id}' added successfully! Default password = '{emp_id}'.")
        self.reload_all_data()
        self.net_client.send_action("DATA_UPDATE_EVENT", {"reason": "EMPLOYEE_ADDED"})

    def on_reset_password(self, emp_id: str):
        confirm = QMessageBox.question(
            self, "Reset Password", 
            f"Reset password for Employee '{emp_id}' back to their User ID?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            pwd_hash, pwd_salt = hash_password(emp_id)
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 1
                WHERE user_id = ?
                """, (pwd_hash, pwd_salt, emp_id))
                conn.commit()
            self.toast.show_message(f"Password for '{emp_id}' reset to '{emp_id}'.")

    # ------------------- PROJECT TAB -------------------
    def create_project_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        form_card = QFrame()
        form_card.setObjectName("CardFrame")
        f_layout = QVBoxLayout(form_card)

        f_layout.addWidget(QLabel("Add New Project", objectName="SubTitle"))

        f_layout.addWidget(QLabel("Project ID:", objectName="FieldLabel"))
        self.txt_prj_id = QLineEdit()
        self.txt_prj_id.setPlaceholderText("e.g. PRJ-03")
        f_layout.addWidget(self.txt_prj_id)

        f_layout.addWidget(QLabel("Project Name:", objectName="FieldLabel"))
        self.txt_prj_name = QLineEdit()
        f_layout.addWidget(self.txt_prj_name)

        f_layout.addWidget(QLabel("Description:", objectName="FieldLabel"))
        self.txt_prj_desc = QLineEdit()
        f_layout.addWidget(self.txt_prj_desc)

        btn_add_prj = QPushButton("Add Project")
        btn_add_prj.clicked.connect(self.on_add_project)
        f_layout.addWidget(btn_add_prj)
        f_layout.addStretch()

        list_card = QFrame()
        list_card.setObjectName("CardFrame")
        l_layout = QVBoxLayout(list_card)
        l_layout.addWidget(QLabel("Projects List", objectName="SubTitle"))

        self.tbl_projects = QTableWidget(0, 4)
        self.tbl_projects.setHorizontalHeaderLabels(["ID", "Name", "Status", "Actions"])
        self.tbl_projects.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        l_layout.addWidget(self.tbl_projects)

        layout.addWidget(form_card, 1)
        layout.addWidget(list_card, 2)
        return widget

    def on_add_project(self):
        p_id = self.txt_prj_id.text().strip()
        name = self.txt_prj_name.text().strip()
        desc = self.txt_prj_desc.text().strip()

        if not p_id or not name:
            QMessageBox.warning(self, "Error", "Project ID and Name are required.")
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?", (p_id,))
            if cursor.fetchone():
                QMessageBox.warning(self, "Error", f"Project ID '{p_id}' already exists.")
                return

            cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                           (p_id, name, desc))
            
            # Automatically assign all current HEAD employees to new project
            cursor.execute("SELECT user_id FROM users WHERE role = ?", (ROLE_HEAD,))
            heads = cursor.fetchall()
            for h in heads:
                cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)",
                               (h["user_id"], p_id))

            conn.commit()

        self.txt_prj_id.clear()
        self.txt_prj_name.clear()
        self.txt_prj_desc.clear()
        self.toast.show_message(f"Project '{name}' added successfully!")
        self.reload_all_data()
        self.net_client.send_action("DATA_UPDATE_EVENT", {"reason": "PROJECT_ADDED"})

    def on_toggle_hide_project(self, project_id: str, current_hidden: int):
        new_hidden = 0 if current_hidden else 1
        action_name = "Hide" if new_hidden else "Unhide"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE projects SET is_hidden = ? WHERE project_id = ?", (new_hidden, project_id))
            conn.commit()

        self.toast.show_message(f"Project '{project_id}' soft-deleted / {action_name.lower()}d.")
        self.reload_all_data()
        self.net_client.send_action("DATA_UPDATE_EVENT", {"reason": "PROJECT_VISIBILITY_CHANGED"})

    # ------------------- TASK TAB -------------------
    def create_task_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        form_card = QFrame()
        form_card.setObjectName("CardFrame")
        f_layout = QVBoxLayout(form_card)

        f_layout.addWidget(QLabel("Add New Task", objectName="SubTitle"))

        f_layout.addWidget(QLabel("Select Project:", objectName="FieldLabel"))
        self.cmb_task_prj = QComboBox()
        f_layout.addWidget(self.cmb_task_prj)

        f_layout.addWidget(QLabel("Task ID:", objectName="FieldLabel"))
        self.txt_task_id = QLineEdit()
        self.txt_task_id.setPlaceholderText("e.g. TSK-04")
        f_layout.addWidget(self.txt_task_id)

        f_layout.addWidget(QLabel("Task Name:", objectName="FieldLabel"))
        self.txt_task_name = QLineEdit()
        f_layout.addWidget(self.txt_task_name)

        btn_add_task = QPushButton("Add Task")
        btn_add_task.clicked.connect(self.on_add_task)
        f_layout.addWidget(btn_add_task)
        f_layout.addStretch()

        list_card = QFrame()
        list_card.setObjectName("CardFrame")
        l_layout = QVBoxLayout(list_card)
        l_layout.addWidget(QLabel("Tasks List", objectName="SubTitle"))

        self.tbl_tasks = QTableWidget(0, 5)
        self.tbl_tasks.setHorizontalHeaderLabels(["ID", "Project", "Name", "Status", "Actions"])
        self.tbl_tasks.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        l_layout.addWidget(self.tbl_tasks)

        layout.addWidget(form_card, 1)
        layout.addWidget(list_card, 2)
        return widget

    def on_add_task(self):
        p_id = self.cmb_task_prj.currentData()
        t_id = self.txt_task_id.text().strip()
        t_name = self.txt_task_name.text().strip()

        if not p_id or not t_id or not t_name:
            QMessageBox.warning(self, "Error", "Project, Task ID, and Task Name are required.")
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (t_id,))
            if cursor.fetchone():
                QMessageBox.warning(self, "Error", f"Task ID '{t_id}' already exists.")
                return

            cursor.execute("INSERT INTO tasks (task_id, project_id, name) VALUES (?, ?, ?)",
                           (t_id, p_id, t_name))
            conn.commit()

        self.txt_task_id.clear()
        self.txt_task_name.clear()
        self.toast.show_message(f"Task '{t_name}' added successfully!")
        self.reload_all_data()
        self.net_client.send_action("DATA_UPDATE_EVENT", {"reason": "TASK_ADDED"})

    def on_toggle_hide_task(self, task_id: str, current_hidden: int):
        new_hidden = 0 if current_hidden else 1
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET is_hidden = ? WHERE task_id = ?", (new_hidden, task_id))
            conn.commit()

        self.toast.show_message(f"Task '{task_id}' visibility toggled.")
        self.reload_all_data()
        self.net_client.send_action("DATA_UPDATE_EVENT", {"reason": "TASK_VISIBILITY_CHANGED"})

    # ------------------- EXPORT TAB -------------------
    def create_export_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        card = QFrame()
        card.setObjectName("CardFrame")
        c_layout = QVBoxLayout(card)

        c_layout.addWidget(QLabel("Export Progress Logs to Excel", objectName="SubTitle"))

        c_layout.addWidget(QLabel("Filter by Project (Optional):", objectName="FieldLabel"))
        self.cmb_export_prj = QComboBox()
        c_layout.addWidget(self.cmb_export_prj)

        c_layout.addSpacing(12)

        btn_export_all = QPushButton("Export All Logs to Excel")
        btn_export_all.clicked.connect(lambda: self.on_export_excel(filter_project=False))
        c_layout.addWidget(btn_export_all)

        btn_export_single = QPushButton("Export Filtered Project Logs to Excel")
        btn_export_single.clicked.connect(lambda: self.on_export_excel(filter_project=True))
        c_layout.addWidget(btn_export_single)

        c_layout.addStretch()
        layout.addWidget(card)
        return widget

    def on_export_excel(self, filter_project: bool):
        project_id = self.cmb_export_prj.currentData() if filter_project else None
        
        default_filename = f"Progress_Logs_{project_id or 'ALL'}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel Report", default_filename, "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            saved_path = self.excel_service.export_logs_to_excel(file_path, project_id=project_id)
            QMessageBox.information(self, "Export Success", f"Excel report saved to:\n{saved_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error exporting Excel file:\n{e}")

    # ------------------- RELOAD DATA -------------------
    def reload_all_data(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Employees
            cursor.execute("SELECT * FROM users WHERE role = 'HEAD'")
            employees = cursor.fetchall()
            self.tbl_employees.setRowCount(0)
            for r_idx, emp in enumerate(employees):
                self.tbl_employees.insertRow(r_idx)
                self.tbl_employees.setItem(r_idx, 0, QTableWidgetItem(emp["user_id"]))
                self.tbl_employees.setItem(r_idx, 1, QTableWidgetItem(emp["role"]))

                btn_rst = QPushButton("🔄 Reset Pass")
                btn_rst.clicked.connect(lambda _, eid=emp["user_id"]: self.on_reset_password(eid))
                self.tbl_employees.setCellWidget(r_idx, 2, btn_rst)

            # Projects
            cursor.execute("SELECT * FROM projects")
            projects = cursor.fetchall()
            self.tbl_projects.setRowCount(0)
            self.cmb_task_prj.clear()
            self.cmb_export_prj.clear()
            self.cmb_export_prj.addItem("All Projects", None)

            for r_idx, p in enumerate(projects):
                self.tbl_projects.insertRow(r_idx)
                self.tbl_projects.setItem(r_idx, 0, QTableWidgetItem(p["project_id"]))
                self.tbl_projects.setItem(r_idx, 1, QTableWidgetItem(p["name"]))
                
                status_str = "Hidden / Soft-Deleted" if p["is_hidden"] else "Active"
                self.tbl_projects.setItem(r_idx, 2, QTableWidgetItem(status_str))

                btn_hide = QPushButton("Unhide" if p["is_hidden"] else "Hide / Delete")
                if not p["is_hidden"]:
                    btn_hide.setObjectName("DangerButton")
                btn_hide.clicked.connect(lambda _, pid=p["project_id"], h=p["is_hidden"]: self.on_toggle_hide_project(pid, h))
                self.tbl_projects.setCellWidget(r_idx, 3, btn_hide)

                if not p["is_hidden"]:
                    self.cmb_task_prj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])
                self.cmb_export_prj.addItem(f"{p['name']} ({p['project_id']})", p["project_id"])

            # Tasks
            cursor.execute("""
            SELECT t.*, p.name AS project_name FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.project_id
            """)
            tasks = cursor.fetchall()
            self.tbl_tasks.setRowCount(0)
            for r_idx, t in enumerate(tasks):
                self.tbl_tasks.insertRow(r_idx)
                self.tbl_tasks.setItem(r_idx, 0, QTableWidgetItem(t["task_id"]))
                self.tbl_tasks.setItem(r_idx, 1, QTableWidgetItem(t["project_name"] or t["project_id"]))
                self.tbl_tasks.setItem(r_idx, 2, QTableWidgetItem(t["name"]))
                
                t_status = "Hidden" if t["is_hidden"] else "Active"
                self.tbl_tasks.setItem(r_idx, 3, QTableWidgetItem(t_status))

                btn_t_hide = QPushButton("Unhide" if t["is_hidden"] else "Hide / Delete")
                if not t["is_hidden"]:
                    btn_t_hide.setObjectName("DangerButton")
                btn_t_hide.clicked.connect(lambda _, tid=t["task_id"], h=t["is_hidden"]: self.on_toggle_hide_task(tid, h))
                self.tbl_tasks.setCellWidget(r_idx, 4, btn_t_hide)

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()
