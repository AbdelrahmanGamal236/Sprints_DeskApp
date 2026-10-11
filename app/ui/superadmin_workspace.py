from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QTabWidget,
    QMessageBox, QTableWidget, QHeaderView, QSplitter, QDialog, QFormLayout, QSpinBox, QFrame, QGridLayout
)
from app.core.config import ALL_ROLES, ROLE_HEAD
from app.network.client import NetworkClient
from app.ui.admin_workspace import AdminPanel
from app.ui.coo_workspace import CooPanel
from app.ui.components import (
    ToastNotifier, CollapsiblePanel, RoleWindow, ChangeDebouncer, BusyButton,
    setup_modern_table, create_table_action_cell, create_table_item, describe_error
)


class EditAccountDialog(QDialog):
    """Super Admin edit of any account: name, role and (for Heads) discipline."""
    def __init__(self, user: dict, disciplines: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Account - {user['user_id']}")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self.txt_name = QLineEdit(user.get("full_name") or "", self)
        form.addRow("Full Name:", self.txt_name)
        self.cmb_role = QComboBox(self)
        for r in ALL_ROLES:
            self.cmb_role.addItem(r)
        self.cmb_role.setCurrentText(user.get("role") or ROLE_HEAD)
        form.addRow("Role:", self.cmb_role)
        self.cmb_disc = QComboBox(self)
        for d in disciplines:
            if not d.get("is_hidden"):
                self.cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
        idx = self.cmb_disc.findData(user.get("discipline_id"))
        if idx >= 0:
            self.cmb_disc.setCurrentIndex(idx)
        form.addRow("Discipline (Heads):", self.cmb_disc)
        self.cmb_role.currentTextChanged.connect(lambda r: self.cmb_disc.setEnabled(r == ROLE_HEAD))
        self.cmb_disc.setEnabled(self.cmb_role.currentText() == ROLE_HEAD)
        row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save", self)
        btn_save.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        form.addRow(row)

    def values(self) -> dict:
        role = self.cmb_role.currentText()
        return {"full_name": self.txt_name.text().strip(), "role": role,
                "discipline_id": self.cmb_disc.currentData() if role == ROLE_HEAD else None}


class SuperAdminPanel(QWidget):
    """Super Admin console: all accounts, Admin tools, COO tools and system settings."""
    def __init__(self, user_dict: dict, net_client: NetworkClient, parent=None):
        super().__init__(parent)
        self.user = user_dict
        self.net_client = net_client
        self.users_data = []
        self.disciplines_data = []
        self.settings_labels = {}
        self.settings_inputs = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        self.toast = ToastNotifier(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.create_accounts_tab(), "Master Accounts && Roles")
        self.admin_sub = AdminPanel(self.user, self.net_client)
        self.tabs.addTab(self.admin_sub, "Admin Operations")
        self.coo_sub = CooPanel(self.user, self.net_client)
        self.tabs.addTab(self.coo_sub, "COO Executive Oversight")
        self.tabs.addTab(self.create_settings_tab(), "System Settings")
        main_layout.addWidget(self.tabs)

        self._changes = ChangeDebouncer(self.reload_scopes, parent=self)
        self.net_client.data_changed.connect(self._changes.add)
        self.net_client.connection_status_changed.connect(lambda ok, _msg: ok and self.reload_all())

        self.reload_all()

    # ------------------------------------------------------------------ data
    def reload_all(self):
        self.reload_scopes({"users", "disciplines", "settings"})

    def reload_scopes(self, scopes):
        if not self.net_client.is_connected:
            return
        err = lambda e: self.toast.show_message(describe_error(e), is_error=True)
        if "users" in scopes:
            self.net_client.call("GET_USERS", {}, self._on_users, err)
        if "disciplines" in scopes:
            self.net_client.call("GET_DISCIPLINES", {"include_hidden": True}, self._on_disciplines, err)
        if "settings" in scopes or "users" in scopes:
            self.net_client.call("GET_SETTINGS", {}, self._on_settings, err)

    def _on_users(self, r):
        self.users_data = r.get("users", [])
        self.populate_users_table()

    def _on_disciplines(self, r):
        self.disciplines_data = r.get("disciplines", [])
        current = self.cmb_disc.currentData()
        self.cmb_disc.clear()
        for d in self.disciplines_data:
            if not d.get("is_hidden"):
                self.cmb_disc.addItem(f"{d['name']} ({d['discipline_id']})", d["discipline_id"])
        idx = self.cmb_disc.findData(current)
        if idx >= 0:
            self.cmb_disc.setCurrentIndex(idx)

    # ------------------------------------------------------------------ accounts tab
    def create_accounts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        self.accounts_splitter = QSplitter(Qt.Horizontal, widget)

        form_w = QWidget()
        f_layout = QVBoxLayout(form_w)
        f_layout.addWidget(QLabel("Create System User Account", objectName="SubTitle"))
        f_layout.addWidget(QLabel("User ID / Username:", objectName="FieldLabel"))
        self.txt_user_id = QLineEdit()
        self.txt_user_id.setPlaceholderText("e.g. admin2, coo2, or a fingerprint ID")
        f_layout.addWidget(self.txt_user_id)
        f_layout.addWidget(QLabel("Full Name:", objectName="FieldLabel"))
        self.txt_full_name = QLineEdit()
        self.txt_full_name.setPlaceholderText("e.g. Eng. Tarek Omar")
        f_layout.addWidget(self.txt_full_name)
        f_layout.addWidget(QLabel("Role:", objectName="FieldLabel"))
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
        info = QLabel("New accounts log in with their User ID as the password and must change it at first login.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        f_layout.addWidget(info)
        f_layout.addStretch()
        self.accounts_splitter.addWidget(CollapsiblePanel("Account Creator", form_w, horizontal=True))

        tbl_w = QWidget()
        t_layout = QVBoxLayout(tbl_w)
        t_layout.addWidget(QLabel("All System User Accounts", objectName="SubTitle"))
        self.tbl_users = QTableWidget(0, 6)
        self.tbl_users.setHorizontalHeaderLabels(["User ID", "Full Name", "Role", "Discipline", "Must Change Password", "Actions"])
        setup_modern_table(self.tbl_users, row_height=46)
        self.tbl_users.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_users.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_users.setColumnWidth(0, 95)
        self.tbl_users.setColumnWidth(2, 105)
        self.tbl_users.setColumnWidth(3, 130)
        self.tbl_users.setColumnWidth(4, 150)
        self.tbl_users.setColumnWidth(5, 190)
        self.tbl_users.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        t_layout.addWidget(self.tbl_users)
        self.accounts_splitter.addWidget(CollapsiblePanel("Accounts Directory", tbl_w, horizontal=True))
        self.accounts_splitter.setSizes([350, 650])
        layout.addWidget(self.accounts_splitter)
        return widget

    def on_role_selection_changed(self):
        is_head = self.cmb_role.currentText() == ROLE_HEAD
        self.lbl_disc.setVisible(is_head)
        self.cmb_disc.setVisible(is_head)

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
            btn_edit = QPushButton("Edit")
            btn_edit.clicked.connect(lambda _, user=u: self.on_edit_user(user))
            btn_reset = QPushButton("Reset Pass")
            btn_reset.clicked.connect(lambda _, uid=u["user_id"]: self.on_reset_pass(uid))
            btn_reset.setEnabled(u["user_id"] != self.user["user_id"])
            self.tbl_users.setCellWidget(r_idx, 5, create_table_action_cell([btn_edit, btn_reset]))

    def on_create_user(self):
        uid = self.txt_user_id.text().strip()
        fname = self.txt_full_name.text().strip()
        role = self.cmb_role.currentText()
        disc = self.cmb_disc.currentData() if role == ROLE_HEAD else None
        if not uid or not fname:
            QMessageBox.warning(self, "Error", "User ID and Full Name are required.")
            return

        busy = BusyButton(self.sender())

        def created(_reply):
            busy()
            self.txt_user_id.clear()
            self.txt_full_name.clear()
            self.toast.show_message(f"{role} account '{uid}' created. Initial password is the User ID.")

        self.net_client.call("CREATE_USER", {"user_id": uid, "full_name": fname, "role": role, "discipline_id": disc},
                             created, lambda e: (busy(), QMessageBox.critical(self, "Could Not Create Account", describe_error(e))))

    def on_edit_user(self, user: dict):
        dlg = EditAccountDialog(user, self.disciplines_data, self)
        if dlg.exec() != QDialog.Accepted:
            return
        values = dlg.values()
        if not values["full_name"]:
            QMessageBox.warning(self, "Error", "Full Name is required.")
            return
        if user["user_id"] == self.user["user_id"] and values["role"] != user.get("role"):
            QMessageBox.warning(self, "Error", "You cannot change your own role.")
            return
        self.net_client.call("UPDATE_USER", dict(values, user_id=user["user_id"]),
                             lambda _r: self.toast.show_message(f"Account '{user['user_id']}' updated."),
                             lambda e: QMessageBox.critical(self, "Could Not Update Account", describe_error(e)))

    def on_reset_pass(self, user_id: str):
        confirm = QMessageBox.question(self, "Confirm Reset", f"Reset password for '{user_id}' back to the User ID?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            def done(_reply):
                self.toast.show_message(f"Password for '{user_id}' reset to the User ID (must be changed at next login).")
                self.reload_scopes({"users"})
            self.net_client.call("RESET_PASSWORD", {"user_id": user_id}, done,
                                 lambda e: QMessageBox.critical(self, "Could Not Reset Password", describe_error(e)))

    # ------------------------------------------------------------------ settings tab
    def create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        card = QFrame()
        card.setObjectName("CardFrame")
        c_layout = QVBoxLayout(card)
        c_layout.addWidget(QLabel("System Settings", objectName="SubTitle"))
        self.settings_form = QFormLayout()
        c_layout.addLayout(self.settings_form)
        self.btn_save_settings = QPushButton("Save Settings")
        self.btn_save_settings.clicked.connect(self.on_save_settings)
        c_layout.addWidget(self.btn_save_settings)
        c_layout.addStretch()
        layout.addWidget(card, 1)

        info_card = QFrame()
        info_card.setObjectName("CardFrame")
        i_layout = QVBoxLayout(info_card)
        i_layout.addWidget(QLabel("Central Server Status", objectName="SubTitle"))
        self.info_grid = QGridLayout()
        i_layout.addLayout(self.info_grid)
        i_layout.addStretch()
        layout.addWidget(info_card, 1)
        return widget

    def _on_settings(self, r):
        settings = r.get("settings", {})
        labels = r.get("labels", {})
        if labels and not self.settings_inputs:
            for key, label in labels.items():
                value = settings.get(key)
                if isinstance(value, int):
                    w = QSpinBox()
                    w.setRange(1, 365)
                else:
                    w = QLineEdit()
                self.settings_inputs[key] = w
                self.settings_form.addRow(label + ":", w)
        for key, w in self.settings_inputs.items():
            if key in settings:
                if isinstance(w, QSpinBox):
                    w.setValue(int(settings[key]))
                else:
                    w.setText(str(settings[key]))
        info = r.get("info")
        if info:
            rows = [
                ("Listening port", str(info.get("port"))),
                ("Protocol version", str(info.get("protocol"))),
                ("Database file", info.get("db_path", "")),
                ("Schema version", str(info.get("schema_version"))),
                ("Users / Projects / Tasks", "{users} / {projects} / {tasks}".format(**info.get("counts", {}))),
                ("Progress logs", str(info.get("counts", {}).get("progress_logs"))),
                ("Backup folder", info.get("backup_folder", "")),
                ("Backups kept", str(info.get("backup_count"))),
                ("Latest backup", info.get("last_backup") or "none yet"),
                ("Users connected now", ", ".join(info.get("connected_users", [])) or "-"),
            ]
            while self.info_grid.count():
                item = self.info_grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            for i, (k, v) in enumerate(rows):
                lbl_k = QLabel(k + ":", objectName="FieldLabel")
                lbl_v = QLabel(v)
                lbl_v.setTextInteractionFlags(Qt.TextSelectableByMouse)
                lbl_v.setWordWrap(True)
                self.info_grid.addWidget(lbl_k, i, 0)
                self.info_grid.addWidget(lbl_v, i, 1)

    def on_save_settings(self):
        values = {k: (w.value() if isinstance(w, QSpinBox) else w.text().strip()) for k, w in self.settings_inputs.items()}
        self.net_client.call("UPDATE_SETTINGS", {"settings": values},
                             lambda r: (self._on_settings(r), self.toast.show_message("System settings saved.")),
                             lambda e: QMessageBox.critical(self, "Settings Not Saved", describe_error(e)))

    # ------------------------------------------------------------------ layout persistence
    def restore_layout(self):
        self.admin_sub.restore_layout()
        self.coo_sub.restore_layout()

    def save_layout(self):
        self.admin_sub.save_layout()
        self.coo_sub.save_layout()


class SuperAdminWorkspace(RoleWindow):
    def __init__(self, user_dict: dict, net_client: NetworkClient):
        name = user_dict.get("full_name") or user_dict["user_id"]
        super().__init__(f"Super Admin Master Console - {name}", "Super Admin Master Administration Console",
                         SuperAdminPanel(user_dict, net_client), min_size=(1100, 780))
