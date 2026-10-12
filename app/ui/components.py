from PySide6.QtCore import Qt, QTimer, Signal, QObject, QEvent
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QWidget, QApplication, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QMainWindow, QMessageBox
)


class ToastOverlay(QFrame):
    """
    The one notification bar of a window: floats at the bottom centre above the content, never takes
    layout space, hides itself after a few seconds. Kinds: success (green), queued/warning (amber),
    error (red).
    """
    STYLES = {
        "success": ("#064E3B", "#10B981"),
        "warning": ("#78350F", "#F59E0B"),
        "error": ("#7F1D1D", "#EF4444"),
    }

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("DeskToastOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # never blocks the buttons underneath
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.label = QLabel("", self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 600; background: transparent; border: none;")
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        window.installEventFilter(self)
        self.hide()

    @classmethod
    def for_window(cls, window: QWidget) -> "ToastOverlay":
        overlay = window.findChild(ToastOverlay, "DeskToastOverlay", Qt.FindDirectChildrenOnly)
        return overlay or cls(window)

    def show_message(self, text: str, kind: str = "success", duration_ms: int = 3500):
        bg, border = self.STYLES.get(kind, self.STYLES["success"])
        self.setStyleSheet(f"QFrame#DeskToastOverlay {{ background-color: {bg}; border: 1px solid {border}; "
                           f"border-radius: 8px; }}")
        self.label.setText(text)
        self._reposition()
        self.show()
        self.raise_()
        self.timer.start(duration_ms)

    def _reposition(self):
        win = self.parentWidget()
        width = max(320, min(720, win.width() - 40))
        self.setFixedWidth(width)
        self.adjustSize()
        self.move((win.width() - width) // 2, win.height() - self.height() - 44)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == event.Type.Resize and self.isVisible():
            self._reposition()
        return False


class ToastNotifier(QWidget):
    """
    Handle used by panels to show notifications. It is an invisible placeholder; messages appear in the
    owning window's single bottom ToastOverlay (so embedded panels share one notification bar).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(0, 0)
        self.hide()

    def _overlay(self) -> ToastOverlay:
        return ToastOverlay.for_window(self.window())

    @property
    def label(self) -> QLabel:
        return self._overlay().label

    def show_message(self, text: str, is_error: bool = False, is_warning: bool = False, duration_ms: int = 3500):
        kind = "error" if is_error else ("warning" if is_warning else "success")
        if is_error and duration_ms == 3500:
            duration_ms = 7000  # errors stay a little longer
        self._overlay().show_message(text, kind, duration_ms)


class ConnectionBanner(QLabel):
    """Red bar at the top of a workspace while the Central Server is unreachable."""
    def __init__(self, net_client, offline_hint: str = "", parent=None):
        super().__init__(parent)
        self.offline_hint = offline_hint or "Changes cannot be saved until the connection returns."
        self.setWordWrap(True)
        self.setStyleSheet("background-color: #7F1D1D; color: #FFFFFF; border: 1px solid #EF4444; "
                           "border-radius: 6px; padding: 6px 10px; font-weight: 600;")
        net_client.connection_status_changed.connect(self.on_status)
        self.setVisible(not net_client.is_connected)

    def on_status(self, connected: bool, message: str):
        if connected:
            self.hide()
        else:
            self.setText(f"Not connected to the Central Server - reconnecting automatically. {self.offline_hint}")
            self.show()


class SyncStatusBadge(QLabel):
    """Live badge widget indicating connection and offline queue status."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.update_status(False, "Initializing...", 0)

    def update_status(self, is_connected: bool, status_msg: str = "", pending_count: int = 0, failed_count: int = 0):
        if is_connected:
            self.setObjectName("SyncBadgeConnected")
            text = "Connected (LAN)"
            if pending_count > 0:
                text += f" - Syncing {pending_count} pending..."
        else:
            self.setObjectName("SyncBadgeDisconnected")
            text = f"Offline ({pending_count} queued)"
            if status_msg:
                text += f" - {status_msg}"
        if failed_count:
            text += f" - {failed_count} failed"
        self.setText(text)
        # objectName drives the colour in the QSS; re-polish so the new name takes effect
        self.style().unpolish(self)
        self.style().polish(self)


def describe_error(exc: Exception) -> str:
    """User-facing text for a failed server request."""
    from app.network.client import ServerError, OfflineError
    if isinstance(exc, OfflineError):
        return "Not connected to the Central Server. Check the network connection and try again."
    if isinstance(exc, TimeoutError):
        return str(exc) or "The Central Server did not respond in time."
    if isinstance(exc, ServerError):
        return str(exc)
    return f"Unexpected error: {exc}"


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
        info_label.setStyleSheet("font-weight: 600; color: #D4D4D8;")
        layout.addWidget(info_label)

        msg_card = QFrame(self)
        msg_card.setStyleSheet("background-color: #27272A; border: 1px solid #8B5CF6; border-radius: 8px; padding: 12px;")
        msg_layout = QVBoxLayout(msg_card)
        self.msg_text = QLabel(message, msg_card)
        self.msg_text.setWordWrap(True)
        self.msg_text.setStyleSheet("font-size: 14px; color: #FAFAFA;")
        msg_layout.addWidget(self.msg_text)
        layout.addWidget(msg_card)

        instruction = QLabel("You must explicitly Accept or Deny this request to dismiss this dialog.", self)
        instruction.setStyleSheet("font-size: 11px; color: #A1A1AA; font-style: italic;")
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
        self.setStyleSheet("font-size: 11px; color: #71717A; padding: 6px; font-weight: 500;")


class ChangeDebouncer(QObject):
    """Collects DATA_CHANGED scopes for a short moment and reloads once (avoids reload storms)."""
    def __init__(self, callback, delay_ms: int = 250, parent=None):
        super().__init__(parent)
        self._callback = callback
        self._scopes = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._fire)

    def add(self, scopes):
        self._scopes.update(scopes)
        self._timer.start()

    def _fire(self):
        scopes, self._scopes = self._scopes, set()
        if scopes:
            self._callback(scopes)


class RoleWindow(QMainWindow):
    """
    Top-level window for one role: header with the user's name, Logout button, a content panel and the
    footer. The panel may implement restore_layout()/save_layout() to persist splitter sizes per user.
    """
    def __init__(self, window_title: str, header_text: str, panel: QWidget, min_size=(1050, 750)):
        super().__init__()
        self.panel = panel
        self.logout_requested = False
        self.setWindowTitle(window_title)
        self.setMinimumSize(*min_size)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        header = QLabel(header_text, self)
        header.setObjectName("HeaderTitle")
        top_bar.addWidget(header)
        top_bar.addStretch()
        btn_logout = QPushButton("Logout", self)
        btn_logout.setObjectName("DangerButton")
        btn_logout.clicked.connect(self.on_logout)
        top_bar.addWidget(btn_logout)
        layout.addLayout(top_bar)

        net_client = getattr(panel, "net_client", None)
        if net_client is not None:
            layout.addWidget(ConnectionBanner(net_client, parent=self))

        layout.addWidget(panel, 1)
        layout.addWidget(CopyrightFooter(self))
        self._layout_restored = False

    def on_logout(self):
        confirm = QMessageBox.question(self, "Confirm Logout", "Are you sure you want to log out?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.logout_requested = True
            self.close()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._layout_restored and hasattr(self.panel, "restore_layout"):
            self._layout_restored = True
            self.panel.restore_layout()

    def closeEvent(self, event):
        if hasattr(self.panel, "save_layout"):
            self.panel.save_layout()
        super().closeEvent(event)


def restore_splitter(splitter: QSplitter, settings, key: str, default_sizes: list):
    saved = settings.value(key)
    try:
        sizes = [int(x) for x in saved] if saved else default_sizes
    except (TypeError, ValueError):
        sizes = default_sizes
    splitter.setSizes(sizes)


# =========================================================================
# MODERN TABLE UI & COMPONENT HELPERS
# =========================================================================

def setup_modern_table(table: QTableWidget, row_height: int = 46, min_col_width: int = 80):
    """
    Standardizes table appearance across all workspaces:
    - Consistent row height so buttons never overlap adjacent rows
    - Full row selection with dark zinc/purple theme highlight
    - Text centering & clean scrollbars
    - Protection against clipped text and ugly borders
    """
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setMinimumSectionSize(row_height)
    table.verticalHeader().setVisible(True)
    table.verticalHeader().setHighlightSections(False)
    
    table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
    table.horizontalHeader().setMinimumSectionSize(min_col_width)
    table.horizontalHeader().setHighlightSections(False)
    
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)


def create_table_action_cell(buttons: list[QPushButton]) -> QWidget:
    """
    Wraps action button(s) in a dedicated container cell with generous margins and padding.
    Guarantees buttons never touch borders or bleed into neighboring rows.
    """
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)
    for btn in buttons:
        btn.setFixedHeight(28)
        btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(btn)
    return widget


def create_table_item(text: str, align: Qt.AlignmentFlag = Qt.AlignCenter, tooltip: str = None) -> QTableWidgetItem:
    """
    Creates a styled QTableWidgetItem with guaranteed alignment and hover tooltip
    to prevent text truncation frustration.
    """
    val = str(text) if text is not None else ""
    item = QTableWidgetItem(val)
    item.setTextAlignment(align)
    item.setToolTip(tooltip if tooltip is not None else val)
    return item


class KpiMetricCard(QFrame):
    """
    Executive-level Dashboard KPI Card.
    Features: Category label, bold numerical metric, subtitle, left accent border, and icon badge.
    """
    def __init__(self, title: str, initial_value: str = "0", icon: str = "", accent_color: str = "#8B5CF6", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.accent_color = accent_color
        self.setMinimumHeight(96)
        self.setStyleSheet(f"QFrame#KpiCard {{ border-left: 4px solid {accent_color}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Left Info Stack
        left_stack = QVBoxLayout()
        left_stack.setSpacing(2)

        self.lbl_title = QLabel(title.upper(), self)
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #A1A1AA; letter-spacing: 0.5px;")
        left_stack.addWidget(self.lbl_title)

        self.lbl_value = QLabel(initial_value, self)
        self.lbl_value.setStyleSheet(f"font-size: 24px; font-weight: 800; color: #FFFFFF;")
        left_stack.addWidget(self.lbl_value)

        if subtitle:
            lbl_sub = QLabel(subtitle, self)
            lbl_sub.setStyleSheet("font-size: 11px; color: #71717A;")
            left_stack.addWidget(lbl_sub)

        left_stack.addStretch()
        layout.addLayout(left_stack, 1)

        # Right Icon Badge
        self.icon_badge = QLabel(icon, self)
        self.icon_badge.setAlignment(Qt.AlignCenter)
        self.icon_badge.setFixedSize(38, 38)
        r, g, b = int(accent_color[1:3], 16), int(accent_color[3:5], 16), int(accent_color[5:7], 16)
        self.icon_badge.setStyleSheet(f"""
            background-color: rgba({r}, {g}, {b}, 40);
            color: {accent_color};
            border-radius: 8px;
            font-size: 12px;
            font-weight: 800;
        """)
        layout.addWidget(self.icon_badge)
        self.icon_badge.setVisible(bool(icon))

    def set_value(self, val):
        self.lbl_value.setText(str(val))


class CollapsiblePanel(QFrame):
    """
    A resizable and collapsible panel (A6).
    Integrated with QSplitter: when collapsed, frees up screen real estate
    smoothly without creating an empty void or distorted box.
    """
    toggled = Signal(bool)

    def __init__(self, title: str, content_widget: QWidget, horizontal: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("CollapsiblePanel")
        self.title_text = title
        self.horizontal = horizontal
        self.is_collapsed = False
        self.content_widget = content_widget
        self._saved_sizes = None

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 6, 6, 6)
        self.main_layout.setSpacing(6)

        # Header Bar Widget
        self.header_frame = QFrame(self)
        self.header_frame.setObjectName("CollapsibleHeader")
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(10, 6, 10, 6)
        h_layout.setSpacing(8)

        self.header_label = QLabel(title, self.header_frame)
        self.header_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #E4E4E7;")
        h_layout.addWidget(self.header_label)
        h_layout.addStretch()

        self.btn_toggle = QPushButton(self.header_frame)
        self.btn_toggle.setObjectName("CollapseToggle")
        self.btn_toggle.setFixedSize(28, 24)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setText("◀" if horizontal else "▲")
        self.btn_toggle.setToolTip(f"Collapse {title}")
        self.btn_toggle.clicked.connect(self.toggle_collapsed)
        h_layout.addWidget(self.btn_toggle)

        self.main_layout.addWidget(self.header_frame)
        self.main_layout.addWidget(self.content_widget, 1)

    def toggle_collapsed(self):
        self.set_collapsed(not self.is_collapsed)

    def _get_parent_splitter(self) -> QSplitter | None:
        p = self.parentWidget()
        if isinstance(p, QSplitter):
            return p
        if p and isinstance(p.parentWidget(), QSplitter):
            return p.parentWidget()
        if isinstance(self.parent(), QSplitter):
            return self.parent()
        return None

    def set_collapsed(self, collapsed: bool):
        self.is_collapsed = collapsed
        splitter = self._get_parent_splitter()

        if collapsed:
            self.content_widget.setVisible(False)
            if self.horizontal:
                self.header_label.setVisible(False)
                self.btn_toggle.setText("▶")
                self.btn_toggle.setToolTip(f"Expand {self.title_text}")
                if splitter:
                    self._saved_sizes = splitter.sizes()
                    idx = splitter.indexOf(self)
                    if idx >= 0 and len(self._saved_sizes) >= 2:
                        new_sizes = list(self._saved_sizes)
                        collapsed_size = 44
                        freed = max(0, new_sizes[idx] - collapsed_size)
                        other_idx = 1 if idx == 0 else 0
                        new_sizes[other_idx] += freed
                        new_sizes[idx] = collapsed_size
                        self.setFixedWidth(collapsed_size)
                        splitter.setSizes(new_sizes)
                    else:
                        self.setFixedWidth(44)
                else:
                    self.setFixedWidth(44)
            else:
                self.btn_toggle.setText("▼")
                self.btn_toggle.setToolTip(f"Expand {self.title_text}")
                h_size = self.header_frame.sizeHint().height() + 14
                if splitter:
                    self._saved_sizes = splitter.sizes()
                    idx = splitter.indexOf(self)
                    if idx >= 0 and len(self._saved_sizes) >= 2:
                        new_sizes = list(self._saved_sizes)
                        freed = max(0, new_sizes[idx] - h_size)
                        other_idx = 1 if idx == 0 else 0
                        new_sizes[other_idx] += freed
                        new_sizes[idx] = h_size
                        self.setFixedHeight(h_size)
                        splitter.setSizes(new_sizes)
                    else:
                        self.setFixedHeight(h_size)
                else:
                    self.setFixedHeight(h_size)
        else:
            self.content_widget.setVisible(True)
            self.header_label.setVisible(True)
            if self.horizontal:
                self.btn_toggle.setText("◀")
                self.btn_toggle.setToolTip(f"Collapse {self.title_text}")
                self.setMinimumWidth(0)
                self.setMaximumWidth(16777215)
                if splitter and self._saved_sizes:
                    splitter.setSizes(self._saved_sizes)
            else:
                self.btn_toggle.setText("▲")
                self.btn_toggle.setToolTip(f"Collapse {self.title_text}")
                self.setMinimumHeight(0)
                self.setMaximumHeight(16777215)
                if splitter and self._saved_sizes:
                    splitter.setSizes(self._saved_sizes)

        self.toggled.emit(collapsed)


class BusyButton:
    """Disables a button while a request runs: `done = BusyButton(btn)` then call `done()` in the callbacks."""
    def __init__(self, button: QPushButton = None):
        self.button = button if isinstance(button, QPushButton) else None
        if self.button is not None:
            self.button.setEnabled(False)

    def __call__(self, *_):
        if self.button is not None:
            try:
                self.button.setEnabled(True)
            except RuntimeError:  # button already deleted (table rebuilt)
                pass


class SmoothScrolling(QObject):
    """
    Application-wide: lists and tables scroll by pixels instead of jumping a whole row, and the mouse
    wheel moves a comfortable distance. Installed once on the QApplication, so every view gets it.
    """
    WHEEL_STEP_PX = 24

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Polish and isinstance(obj, QAbstractItemView):
            obj.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            obj.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            obj.verticalScrollBar().setSingleStep(self.WHEEL_STEP_PX)
            obj.horizontalScrollBar().setSingleStep(self.WHEEL_STEP_PX)
        return False


def install_smooth_scrolling(app) -> SmoothScrolling:
    f = SmoothScrolling(app)
    app.installEventFilter(f)
    return f
