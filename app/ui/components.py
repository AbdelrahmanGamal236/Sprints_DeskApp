from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, 
    QFrame, QWidget, QApplication
)

class ToastNotifier(QFrame):
    """Inline / Toast style confirmation message box."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CardFrame")
        self.layout = QHBoxLayout(self)
        self.label = QLabel("", self)
        self.layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, is_error: bool = False, is_warning: bool = False, duration_ms: int = 3500):
        self.label.setText(text)
        if is_error:
            self.setStyleSheet("QFrame#CardFrame { background-color: #7F1D1D; border: 1px solid #EF4444; color: #FFFFFF; }")
        elif is_warning:
            self.setStyleSheet("QFrame#CardFrame { background-color: #78350F; border: 1px solid #F59E0B; color: #FFFFFF; }")
        else:
            self.setStyleSheet("QFrame#CardFrame { background-color: #064E3B; border: 1px solid #10B981; color: #FFFFFF; }")
        self.show()
        self.timer.start(duration_ms)


class SyncStatusBadge(QLabel):
    """Live badge widget indicating connection and offline queue status."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.update_status(False, "Initializing...", 0)

    def update_status(self, is_connected: bool, status_msg: str = "", pending_count: int = 0):
        if is_connected:
            self.setObjectName("SyncBadgeConnected")
            text = "Connected (LAN)"
            if pending_count > 0:
                text += f" - Syncing {pending_count} pending..."
        else:
            self.setObjectName("SyncBadgeDisconnected")
            text = f"Disconnected / Offline ({pending_count} queued)"
            if status_msg:
                text += f" - {status_msg}"
        self.setText(text)
        self.setStyleSheet(self.styleSheet()) # Force restyle refresh


class BlockingCenterModal(QDialog):
    """
    COO Priority Notification Modal.
    STRICT REQUIREMENT: MUST NOT BE DISMISSIBLE by closing window or ESC key.
    Forces explicit click of Accept or Deny.
    """
    response_submitted = Signal(str) # Emits 'ACCEPTED' or 'DENIED'

    def __init__(self, notification_id: str, coo_id: str, message: str, parent=None):
        super().__init__(parent)
        self.notification_id = notification_id
        self.coo_id = coo_id
        self.user_choice = None

        # Modal Window Flags: No close button, modal behavior
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setModal(True)
        self.setWindowTitle("URGENT: COO Priority Notification")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        header = QLabel("PRIORITY REQUEST FROM COO", self)
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #F59E0B;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        info_label = QLabel(f"COO ({coo_id}) has dispatched an urgent instruction:", self)
        info_label.setStyleSheet("font-weight: 600; color: #CBD5E1;")
        layout.addWidget(info_label)

        msg_card = QFrame(self)
        msg_card.setStyleSheet("background-color: #1E293B; border: 1px solid #3B82F6; border-radius: 8px; padding: 12px;")
        msg_layout = QVBoxLayout(msg_card)
        self.msg_text = QLabel(message, msg_card)
        self.msg_text.setWordWrap(True)
        self.msg_text.setStyleSheet("font-size: 14px; color: #F8FAFC;")
        msg_layout.addWidget(self.msg_text)
        layout.addWidget(msg_card)

        instruction = QLabel("You must explicitly Accept or Deny this request to dismiss this dialog.", self)
        instruction.setStyleSheet("font-size: 11px; color: #94A3B8; italic: true;")
        instruction.setAlignment(Qt.AlignCenter)
        layout.addWidget(instruction)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_accept = QPushButton("ACCEPT", self)
        self.btn_accept.setObjectName("SuccessButton")
        self.btn_accept.setMinimumHeight(40)
        self.btn_accept.clicked.connect(self.on_accept)

        self.btn_deny = QPushButton("DENY", self)
        self.btn_deny.setObjectName("DangerButton")
        self.btn_deny.setMinimumHeight(40)
        self.btn_deny.clicked.connect(self.on_deny)

        btn_layout.addWidget(self.btn_accept)
        btn_layout.addWidget(self.btn_deny)
        layout.addLayout(btn_layout)

    def on_accept(self):
        self.user_choice = "ACCEPTED"
        self.response_submitted.emit("ACCEPTED")
        self.accept()

    def on_deny(self):
        self.user_choice = "DENIED"
        self.response_submitted.emit("DENIED")
        self.reject()

    def closeEvent(self, event):
        # PREVENT WINDOW CLOSING VIA ALT+F4 OR CLOSE BUTTON
        if self.user_choice is None:
            event.ignore()
        else:
            event.accept()

    def keyPressEvent(self, event):
        # PREVENT ESCAPE KEY DISMISSAL
        if event.key() == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)


class CopyrightFooter(QLabel):
    """Global Copyright Footer Widget."""
    def __init__(self, parent=None):
        super().__init__("© All Rights Reserved to Eng. Abdelrahman Gamal & Eng. Tolimy", parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("font-size: 11px; color: #64748B; padding: 6px; font-weight: 500;")

