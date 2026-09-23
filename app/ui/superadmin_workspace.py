from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTabWidget, 
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from app.core.config import ALL_ROLES
from app.core.auth import hash_password
from app.database.db_manager import DBManager
from app.network.client import NetworkClient
from app.ui.admin_workspace import AdminWorkspace
from app.ui.coo_workspace import CooWorkspace
from app.ui.components import ToastNotifier, CopyrightFooter

class SuperAdminWorkspace(QMainWindow):
    """Super Admin Master Management Workspace."""
    def __init__(self, user_dict: dict, db_manager: DBManager, net_client: NetworkClient):
        super().__init__()
        self.user = user_dict
        self.db = db_manager
        self.net_client = net_client
        self.logout_requested = False

        self.setWindowTitle(f"Super Admin Master Console - {self.user['user_id']}")
        self.setMinimumSize(1050, 750)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        top_bar = QHBoxLayout()
        header = QLabel("Super Admin Master Administration Console", self)
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

        tabs = QTabWidget(self)

        # Tab 1: System Accounts & Roles
        tabs.addTab(self.create_accounts_tab(), "Manage Accounts & Roles")

        # Tab 2: Admin Tools
        self.admin_sub = AdminWorkspace(self.user, self.db, self.net_client)
        tabs.addTab(self.admin_sub.centralWidget(), "Admin Tools")

        # Tab 3: COO Oversight Tools
        self.coo_sub = CooWorkspace(self.user, self.db, self.net_client)
        tabs.addTab(self.coo_sub.centralWidget(), "COO Executive Oversight")

        main_layout.addWidget(tabs)
        main_layout.addWidget(CopyrightFooter(self))
        self.reload_accounts()

    def create_accounts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # Form
        form_card = QFrame()
        form_card.setObjectName("CardFrame")
        f_layout = QVBoxLayout(form_card)

        f_layout.addWidget(QLabel("Create / Update System User Account", objectName="SubTitle"))

        f_layout.addWidget(QLabel("User ID / Username:", objectName="FieldLabel"))
        self.txt_user_id = QLineEdit()
        self.txt_user_id.setPlaceholderText("e.g. admin2, coo2")
        f_layout.addWidget(self.txt_user_id)

        f_layout.addWidget(QLabel("Role:", objectName="FieldLabel"))
        self.cmb_role = QComboBox()
        for r in ALL_ROLES:
            self.cmb_role.addItem(r)
        f_layout.addWidget(self.cmb_role)

        btn_save_user = QPushButton("Create User Account")
        btn_save_user.clicked.connect(self.on_create_user)
        f_layout.addWidget(btn_save_user)
        f_layout.addStretch()

        # Table
        list_card = QFrame()
        list_card.setObjectName("CardFrame")
        l_layout = QVBoxLayout(list_card)
        l_layout.addWidget(QLabel("All System User Accounts", objectName="SubTitle"))

        self.tbl_users = QTableWidget(0, 4)
        self.tbl_users.setHorizontalHeaderLabels(["User ID", "Role", "Must Reset Pass?", "Actions"])
        self.tbl_users.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        l_layout.addWidget(self.tbl_users)

        layout.addWidget(form_card, 1)
        layout.addWidget(list_card, 2)
        return widget

    def on_create_user(self):
        u_id = self.txt_user_id.text().strip()
        role = self.cmb_role.currentText()

        if not u_id:
            QMessageBox.warning(self, "Error", "User ID cannot be empty.")
            return

        pwd_hash, pwd_salt = hash_password(u_id) # Initial pass = ID

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (u_id,))
            if cursor.fetchone():
                QMessageBox.warning(self, "Error", f"User ID '{u_id}' already exists.")
                return

            cursor.execute("""
            INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password)
            VALUES (?, ?, ?, ?, 1)
            """, (u_id, pwd_hash, pwd_salt, role))
            conn.commit()

        self.txt_user_id.clear()
        self.toast.show_message(f"User account '{u_id}' ({role}) created successfully!")
        self.reload_accounts()

    def on_reset_user_pass(self, user_id: str):
        pwd_hash, pwd_salt = hash_password(user_id)
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 1 
            WHERE user_id = ?
            """, (pwd_hash, pwd_salt, user_id))
            conn.commit()
        self.toast.show_message(f"Password for '{user_id}' reset to '{user_id}'.")
        self.reload_accounts()

    def reload_accounts(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY created_at ASC")
            users = cursor.fetchall()

        self.tbl_users.setRowCount(0)
        for r_idx, u in enumerate(users):
            self.tbl_users.insertRow(r_idx)
            self.tbl_users.setItem(r_idx, 0, QTableWidgetItem(u["user_id"]))
            self.tbl_users.setItem(r_idx, 1, QTableWidgetItem(u["role"]))
            self.tbl_users.setItem(r_idx, 2, QTableWidgetItem("Yes" if u["must_change_password"] else "No"))

            btn_reset = QPushButton("Reset Pass")
            btn_reset.clicked.connect(lambda _, uid=u["user_id"]: self.on_reset_user_pass(uid))
            self.tbl_users.setCellWidget(r_idx, 3, btn_reset)

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()
