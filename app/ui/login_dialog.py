from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, 
    QHBoxLayout, QFrame, QMessageBox
)
from app.database.db_manager import DBManager
from app.core.auth import verify_password, hash_password
from app.ui.components import CopyrightFooter

class PasswordChangeDialog(QDialog):
    """Forced Password Change Dialog on First Login or Admin Reset."""
    def __init__(self, user_id: str, db_manager: DBManager, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.db = db_manager
        self.setWindowTitle("Mandatory Password Update")
        self.setMinimumWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header = QLabel("Password Change Required", self)
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #C4B5FD;")
        layout.addWidget(header)

        info = QLabel(f"Welcome, User '{user_id}'. You must update your default password before continuing.", self)
        info.setWordWrap(True)
        info.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(info)

        lbl_new = QLabel("New Password:", self)
        lbl_new.setObjectName("FieldLabel")
        self.txt_new = QLineEdit(self)
        self.txt_new.setEchoMode(QLineEdit.Password)
        layout.addWidget(lbl_new)
        layout.addWidget(self.txt_new)

        lbl_confirm = QLabel("Confirm New Password:", self)
        lbl_confirm.setObjectName("FieldLabel")
        self.txt_confirm = QLineEdit(self)
        self.txt_confirm.setEchoMode(QLineEdit.Password)
        layout.addWidget(lbl_confirm)
        layout.addWidget(self.txt_confirm)

        self.btn_submit = QPushButton("Update Password & Continue", self)
        self.btn_submit.clicked.connect(self.on_submit)
        layout.addWidget(self.btn_submit)

        layout.addWidget(CopyrightFooter(self))

    def on_submit(self):
        new_pwd = self.txt_new.text().strip()
        confirm_pwd = self.txt_confirm.text().strip()

        if not new_pwd:
            QMessageBox.warning(self, "Validation Error", "Password cannot be empty.")
            return

        if new_pwd == self.user_id:
            QMessageBox.warning(self, "Validation Error", "New password cannot be the same as your User ID.")
            return

        if new_pwd != confirm_pwd:
            QMessageBox.warning(self, "Validation Error", "Passwords do not match.")
            return

        # Update in database
        pwd_hash, pwd_salt = hash_password(new_pwd)
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users 
            SET password_hash = ?, password_salt = ?, must_change_password = 0 
            WHERE user_id = ?
            """, (pwd_hash, pwd_salt, self.user_id))
            conn.commit()

        QMessageBox.information(self, "Success", "Password updated successfully!")
        self.accept()


class LoginDialog(QDialog):
    """User Login Dialog with embedded Server IP setting."""
    def __init__(self, db_manager: DBManager, default_server_ip: str = "127.0.0.1", parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.authenticated_user = None
        self.selected_server_ip = default_server_ip
        
        self.setWindowTitle("Offline Workstation Login")
        self.setFixedSize(840, 520)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ----------------- LEFT HERO PANEL -----------------
        left_hero = QFrame(self)
        left_hero.setStyleSheet("background-color: #141417; border-right: 1px solid #27272A;")
        left_layout = QVBoxLayout(left_hero)
        left_layout.setContentsMargins(40, 40, 40, 40)

        # Top DEV pill badge (Removed)
        # badge_layout = QHBoxLayout()
        # badge_pill = QLabel("DEV", left_hero)
        # badge_pill.setObjectName("HeroBadgePill")
        # badge_layout.addWidget(badge_pill)
        # badge_layout.addStretch()
        # left_layout.addLayout(badge_layout)

        left_layout.addStretch(1)

        # Main Hero Title
        hero_title = QLabel("Welcome\nBack !", left_hero)
        hero_title.setObjectName("HeroMainTitle")
        left_layout.addWidget(hero_title)

        left_layout.addStretch(1)
        main_layout.addWidget(left_hero, 1)

        # ----------------- RIGHT FORM PANEL -----------------
        right_panel = QFrame(self)
        right_panel.setStyleSheet("background-color: #242428;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(44, 40, 44, 30)
        right_layout.setSpacing(10)

        title = QLabel("Login", right_panel)
        title.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFFFFF; font-family: 'Segoe UI', sans-serif;")
        right_layout.addWidget(title)

        subtitle = QLabel("Welcome Back! Please login to your account", right_panel)
        subtitle.setStyleSheet("font-size: 13px; color: #A1A1AA; font-weight: 500;")
        right_layout.addWidget(subtitle)

        right_layout.addSpacing(14)

        lbl_id = QLabel("User Name", right_panel)
        lbl_id.setObjectName("FieldLabel")
        self.txt_id = QLineEdit(right_panel)
        self.txt_id.setPlaceholderText("e.g. 1001, admin, coo")
        self.txt_id.setMinimumHeight(40)
        right_layout.addWidget(lbl_id)
        right_layout.addWidget(self.txt_id)

        lbl_pwd = QLabel("Password", right_panel)
        lbl_pwd.setObjectName("FieldLabel")
        self.txt_pwd = QLineEdit(right_panel)
        self.txt_pwd.setEchoMode(QLineEdit.Password)
        self.txt_pwd.setPlaceholderText("Enter password")
        self.txt_pwd.setMinimumHeight(40)
        self.txt_pwd.returnPressed.connect(self.on_login)
        right_layout.addWidget(lbl_pwd)
        right_layout.addWidget(self.txt_pwd)

        lbl_ip = QLabel("Central Server LAN IP", right_panel)
        lbl_ip.setObjectName("FieldLabel")
        self.txt_ip = QLineEdit(right_panel)
        self.txt_ip.setText(self.selected_server_ip)
        self.txt_ip.setPlaceholderText("127.0.0.1 or LAN IP")
        self.txt_ip.setMinimumHeight(40)
        right_layout.addWidget(lbl_ip)
        right_layout.addWidget(self.txt_ip)

        right_layout.addSpacing(14)

        self.btn_login = QPushButton("Login", right_panel)
        self.btn_login.setMinimumHeight(44)
        self.btn_login.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_login.clicked.connect(self.on_login)
        right_layout.addWidget(self.btn_login)

        right_layout.addStretch()
        right_layout.addWidget(CopyrightFooter(right_panel))

        main_layout.addWidget(right_panel, 1)

    def on_login(self):
        user_id = self.txt_id.text().strip()
        password = self.txt_pwd.text().strip()
        server_ip = self.txt_ip.text().strip() or "127.0.0.1"

        if not user_id or not password:
            QMessageBox.warning(self, "Login Error", "Please enter both User ID and Password.")
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()

        if not user or not verify_password(password, user["password_hash"], user["password_salt"]):
            QMessageBox.critical(self, "Authentication Failed", "Invalid User ID or Password.")
            return

        user_dict = dict(user)

        # Check mandatory password change
        if user_dict["must_change_password"] == 1:
            pwd_dialog = PasswordChangeDialog(user_id, self.db, self)
            if pwd_dialog.exec() != QDialog.Accepted:
                return

        self.authenticated_user = user_dict
        self.selected_server_ip = server_ip
        self.accept()
