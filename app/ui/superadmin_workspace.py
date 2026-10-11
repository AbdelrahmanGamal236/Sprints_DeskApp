from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame, QComboBox, QTabWidget, 
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter
)
from app.core.config import ALL_ROLES, ROLE_HEAD
from app.network.client import NetworkClient
from app.ui.admin_workspace import AdminWorkspace
from app.ui.coo_workspace import CooWorkspace
from app.ui.components import (
    ToastNotifier, CopyrightFooter, CollapsiblePanel,
    setup_modern_table, create_table_action_cell, create_table_item
)

class SuperAdminWorkspace(QMainWindow):
    """Super Admin Master Management Workspace (B5 Server Permissions)."""
    def __init__(self, user_dict: dict, db_manager, net_client: NetworkClient):
        super().__init__()
        self.user = user_dict
        self.db = db_manager
        self.net_client = net_client
        self.logout_requested = False

        self.users_data = []
        self.disciplines_data = []

        self.setWindowTitle(f"Super Admin Master Console - {self.user.get('full_name') or self.user['user_id']}")
        self.setMinimumSize(1100, 780)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

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
        tabs.addTab(self.create_accounts_tab(), "Master Accounts & Roles")

        # Tab 2: Admin Tools
        self.admin_sub = AdminWorkspace(self.user, self.db, self.net_client)
        tabs.addTab(self.admin_sub.centralWidget(), "Admin Operations")

        # Tab 3: COO Oversight Tools
        self.coo_sub = CooWorkspace(self.user, self.db, self.net_client)
        tabs.addTab(self.coo_sub.centralWidget(), "COO Executive Oversight")

        main_layout.addWidget(tabs)
        main_layout.addWidget(CopyrightFooter(self))

        self.net_client.response_received.connect(self.on_server_response)
        self.net_client.global_refresh_received.connect(self.reload_accounts)

        self.reload_accounts()

    def create_accounts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        splitter = QSplitter(Qt.Horizontal, widget)

        # Form
        form_w = QWidget()
        f_layout = QVBoxLayout(form_w)
        f_layout.addWidget(QLabel("Create / Update System User Account", objectName="SubTitle"))

        f_layout.addWidget(QLabel("User ID / Username:", objectName="FieldLabel"))
        self.txt_user_id = QLineEdit()
        self.txt_user_id.setPlaceholderText("e.g. admin2, coo2")
        f_layout.addWidget(self.txt_user_id)

        f_layout.addWidget(QLabel("Full Name:", objectName="FieldLabel"))
        self.txt_full_name = QLineEdit()
        self.txt_full_name.setPlaceholderText("e.g. Eng. Tarek Omar")
        f_layout.addWidget(self.txt_full_name)

        f_layout.addWidget(QLabel("Role (Super Admin Can Create Any Role):", objectName="FieldLabel"))
        self.cmb_role = QComboBox()
        for r in ALL_ROLES:
            self.cmb_role.addItem(r)
        self.cmb_role.currentIndexChanged.connect(self.on_role_selection_changed)
        f_layout.addWidget(self.cmb_role)

        self.lbl_disc = QLabel("Discipline (Required for HEAD):", objectName="FieldLabel")
        f_layout.addWidget(self.lbl_disc)
        self.cmb_disc = QComboBox()
        f_layout.addWidget(self.cmb_disc)

        btn_save = QPushButton("Create System Account")
        btn_save.clicked.connect(self.on_create_user)
        f_layout.addWidget(btn_save)
        f_layout.addStretch()

        p_left = CollapsiblePanel("Account Creator", form_w, horizontal=True)
        splitter.addWidget(p_left)

        # Table
        tbl_w = QWidget()
        t_layout = QVBoxLayout(tbl_w)
        t_layout.addWidget(QLabel("All System User Accounts Directory", objectName="SubTitle"))

        self.tbl_users = QTableWidget(0, 6)
        self.tbl_users.setHorizontalHeaderLabels([
            "User ID", "Full Name", "Role", "Discipline", "Must Reset Pass?", "Actions"
        ])
        setup_modern_table(self.tbl_users, row_height=46)
        self.tbl_users.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_users.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_users.setColumnWidth(0, 95)
        self.tbl_users.setColumnWidth(2, 95)
        self.tbl_users.setColumnWidth(3, 130)
        self.tbl_users.setColumnWidth(4, 125)
        self.tbl_users.setColumnWidth(5, 120)
        self.tbl_users.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        t_layout.addWidget(self.tbl_users)

        p_right = CollapsiblePanel("Accounts Directory", tbl_w, horizontal=True)
        splitter.addWidget(p_right)
        splitter.setSizes([350, 650])

        layout.addWidget(splitter)
        return widget

    def on_role_selection_changed(self):
        is_head = self.cmb_role.currentText() == ROLE_HEAD
        self.lbl_disc.setVisible(is_head)
        self.cmb_disc.setVisible(is_head)

    def reload_accounts(self):
        self.net_client.send_action("GET_USERS", {})
        self.net_client.send_action("GET_DISCIPLINES", {"include_hidden": True})

    def on_server_response(self, resp_type: str, data: dict):
        if resp_type == "USERS_RESPONSE":
            self.users_data = data.get("users", [])
            self.populate_users_table()
        elif resp_type == "DISCIPLINES_RESPONSE":
            self.disciplines_data = data.get("disciplines", [])
            self.cmb_disc.clear()
            for d in self.disciplines_data:
                if not d.get("is_hidden"):
                    self.cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
        elif resp_type == "CREATE_USER_RESPONSE":
            if data.get("success"):
                self.toast.show_message("Account created successfully.")
                self.reload_accounts()
            else:
                QMessageBox.critical(self, "Error", data.get("error", "Failed to create user."))
        elif resp_type == "RESET_PASSWORD_RESPONSE":
            if data.get("success"):
                self.toast.show_message("Password reset successfully.")
                self.reload_accounts()

    def populate_users_table(self):
        self.tbl_users.setRowCount(0)
        for r_idx, u in enumerate(self.users_data):
            self.tbl_users.insertRow(r_idx)
            self.tbl_users.setItem(r_idx, 0, create_table_item(u["user_id"], Qt.AlignCenter))
            self.tbl_users.setItem(r_idx, 1, create_table_item(u.get("full_name") or u["user_id"], Qt.AlignLeft | Qt.AlignVCenter))
            self.tbl_users.setItem(r_idx, 2, create_table_item(u.get("role", ""), Qt.AlignCenter))

            d_str = u.get("discipline_name") or u.get("discipline_id") or "N/A"
            self.tbl_users.setItem(r_idx, 3, create_table_item(d_str, Qt.AlignCenter))
            self.tbl_users.setItem(r_idx, 4, create_table_item("Yes" if u.get("must_change_password") else "No", Qt.AlignCenter))

            btn_reset = QPushButton("Reset Pass")
            btn_reset.clicked.connect(lambda _, uid=u["user_id"]: self.on_reset_pass(uid))
            self.tbl_users.setCellWidget(r_idx, 5, create_table_action_cell([btn_reset]))

    def on_create_user(self):
        uid = self.txt_user_id.text().strip()
        fname = self.txt_full_name.text().strip()
        role = self.cmb_role.currentText()
        disc = self.cmb_disc.currentData() if role == ROLE_HEAD else None

        if not uid or not fname:
            QMessageBox.warning(self, "Error", "User ID and Full Name are required.")
            return

        self.net_client.send_action("CREATE_USER", {
            "user_id": uid,
            "full_name": fname,
            "role": role,
            "discipline_id": disc
        })
        self.txt_user_id.clear()
        self.txt_full_name.clear()

    def on_reset_pass(self, user_id: str):
        confirm = QMessageBox.question(
            self, "Confirm Reset", f"Reset password for '{user_id}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.net_client.send_action("RESET_PASSWORD", {"user_id": user_id})

    def on_logout(self):
        confirm = QMessageBox.question(
            self, "Confirm Logout", "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()
