import asyncio
import logging
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, 
    QHBoxLayout, QFrame, QMessageBox, QApplication
)
from app.core.config import DEFAULT_WS_PORT
from app.network.client import NetworkClient
from app.ui.components import CopyrightFooter

logger = logging.getLogger(__name__)

class PasswordChangeDialog(QDialog):
    """Forced Password Change Dialog on First Login or Admin Reset (B1 - Server Enforced)."""
    def __init__(self, user_id: str, server_ip: str, port: int = DEFAULT_WS_PORT, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.server_ip = server_ip
        self.port = port
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

        # Change password via Central Server action (B1)
        try:
            res = NetworkClient.sync_change_password_server(
                self.server_ip, self.port, self.user_id, new_pwd, force=True
            )
            if res.get("success"):
                QMessageBox.information(self, "Success", "Password updated successfully!")
                self.accept()
            else:
                QMessageBox.critical(self, "Error", res.get("error", "Failed to update password."))
        except Exception as e:
            QMessageBox.critical(self, "Server Error", f"Cannot reach Central Server at {self.server_ip}: {e}")


class LoginDialog(QDialog):
    """User Login Dialog with Server-Side Authentication & IP Memory (B1, B6)."""
    def __init__(self, default_server_ip: str = "127.0.0.1", port: int = DEFAULT_WS_PORT, parent=None):
        super().__init__(parent)
        self.port = port
        self.authenticated_user = None

        # Restore remembered Central Server IP from QSettings (B6)
        settings = QSettings("SprintsDeskApp", "ClientConfig")
        self.selected_server_ip = settings.value("server_ip", default_server_ip)

        self.setWindowTitle("DeskApp Workstation Login")
        self.setFixedSize(840, 520)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ----------------- LEFT HERO PANEL -----------------
        left_hero = QFrame(self)
        left_hero.setStyleSheet("background-color: #141417; border-right: 1px solid #27272A;")
        left_layout = QVBoxLayout(left_hero)
        left_layout.setContentsMargins(40, 40, 40, 40)

        left_layout.addStretch(1)
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

        subtitle = QLabel("Please login with your assigned User ID and Password", right_panel)
        subtitle.setStyleSheet("font-size: 13px; color: #A1A1AA; font-weight: 500;")
        right_layout.addWidget(subtitle)

        right_layout.addSpacing(14)

        lbl_id = QLabel("User Name / ID", right_panel)
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
        self.txt_ip.setPlaceholderText("e.g. 192.168.1.50 or 127.0.0.1")
        self.txt_ip.setMinimumHeight(40)
        right_layout.addWidget(lbl_ip)
        right_layout.addWidget(self.txt_ip)

        right_layout.addSpacing(14)

        self.btn_login = QPushButton("Login", right_panel)
        self.btn_login.setMinimumHeight(44)
        self.btn_login.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_login.clicked.connect(self.on_login)
        right_layout.addWidget(self.btn_login)

        self.lbl_status = QLabel("", right_panel)
        self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 12px;")
        right_layout.addWidget(self.lbl_status)

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

        self.lbl_status.setText(f"Connecting to Central Server at {server_ip}...")
        self.btn_login.setEnabled(False)
        QApplication.processEvents()

        # Connect to Central Server and authenticate over WebSocket (B1)
        try:
            auth_response = NetworkClient.sync_authenticate_server(
                server_ip, self.port, user_id, password, timeout=3.5
            )
        except Exception as e:
            self.lbl_status.setText("")
            self.btn_login.setEnabled(True)
            QMessageBox.critical(
                self, "Connection Error",
                f"Cannot reach Central Server at {server_ip}\n\nMake sure the Central Server daemon is running and port {self.port} is open."
            )
            return

        self.btn_login.setEnabled(True)
        self.lbl_status.setText("")

        if not auth_response or not auth_response.get("success"):
            err_msg = auth_response.get("error", "Invalid User ID or Password.") if auth_response else "Authentication failed."
            QMessageBox.critical(self, "Authentication Failed", err_msg)
            return

        # Authentication succeeded
        user_data = auth_response["user"]

        # Persist remembered server IP to QSettings (B6)
        settings = QSettings("SprintsDeskApp", "ClientConfig")
        settings.setValue("server_ip", server_ip)
        self.selected_server_ip = server_ip

        # Check mandatory password change (B1)
        if user_data.get("must_change_password") == 1:
            pwd_dialog = PasswordChangeDialog(user_id, server_ip, self.port, self)
            if pwd_dialog.exec() != QDialog.Accepted:
                return

        self.authenticated_user = user_data
        self.accept()
