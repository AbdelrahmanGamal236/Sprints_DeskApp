# Modern Dark Zinc & Vibrant Purple QSS Theme styling for PySide6 Desktop Application

DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #18181B;
    color: #F4F4F5;
    font-family: 'Segoe UI', Arial, sans-serif;
}

QWidget {
    background-color: #18181B;
    color: #F4F4F5;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

/* Card Containers */
QFrame#CardFrame {
    background-color: #202024;
    border-radius: 10px;
    border: 1px solid #2E2E33;
    padding: 12px;
}

QFrame#CollapsiblePanel {
    background-color: #1A1A1E;
    border-radius: 8px;
    border: 1px solid #2E2E33;
}

QFrame#CollapsibleHeader {
    background-color: #242428;
    border-radius: 6px;
    border: 1px solid #333338;
}

/* KPI Metric Cards */
QFrame#KpiCard {
    background-color: #202024;
    border-radius: 8px;
    border: 1px solid #2E2E33;
    padding: 10px 14px;
}

QFrame#KpiCard:hover {
    border: 1px solid #4F46E5;
    background-color: #242428;
}

/* Splitter */
QSplitter::handle {
    background-color: #2E2E33;
}

QSplitter::handle:hover {
    background-color: #8B5CF6;
}

QPushButton#CollapseToggle {
    background-color: #27272A;
    color: #A1A1AA;
    border: 1px solid #3F3F46;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: bold;
}

QPushButton#CollapseToggle:hover {
    background-color: #3F3F46;
    color: #FFFFFF;
}

/* Labels */
QLabel {
    color: #F4F4F5;
}

QLabel#HeaderTitle {
    font-size: 20px;
    font-weight: bold;
    color: #F4F4F5;
}

QLabel#SubTitle {
    font-size: 14px;
    font-weight: 600;
    color: #A1A1AA;
}

QLabel#FieldLabel {
    font-size: 12px;
    font-weight: 600;
    color: #E4E4E7;
}

/* Hero Badge Pill */
QLabel#HeroBadgePill {
    background-color: #7C3AED;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: bold;
    padding: 6px 12px;
    border-radius: 6px;
}

QLabel#HeroMainTitle {
    font-size: 40px;
    font-weight: 800;
    color: #FFFFFF;
    line-height: 1.2;
}

/* Buttons */
QPushButton {
    background-color: #8B5CF6;
    color: #FFFFFF;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    border: none;
}

QPushButton:hover {
    background-color: #7C3AED;
}

QPushButton:pressed {
    background-color: #6D28D9;
}

QPushButton:disabled {
    background-color: #2E2E33;
    color: #71717A;
}

QPushButton#DangerButton {
    background-color: #EF4444;
    color: #FFFFFF;
}

QPushButton#DangerButton:hover {
    background-color: #DC2626;
}

QPushButton#SuccessButton {
    background-color: #10B981;
    color: #FFFFFF;
}

QPushButton#SuccessButton:hover {
    background-color: #059669;
}

/* Table Specific Action Buttons */
QTableWidget QPushButton {
    background-color: #7C3AED;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    min-height: 26px;
    max-height: 28px;
    border: none;
}

QTableWidget QPushButton:hover {
    background-color: #6D28D9;
}

QTableWidget QPushButton:pressed {
    background-color: #5B21B6;
}

QTableWidget QPushButton#DangerButton {
    background-color: #EF4444;
    color: #FFFFFF;
}

QTableWidget QPushButton#DangerButton:hover {
    background-color: #DC2626;
}

QTableWidget QPushButton#SuccessButton {
    background-color: #10B981;
    color: #FFFFFF;
}

QTableWidget QPushButton#SuccessButton:hover {
    background-color: #059669;
}

/* LineEdits and TextEdits */
QLineEdit, QTextEdit, QDateEdit, QComboBox {
    background-color: #18181B;
    color: #F4F4F5;
    border: 1px solid #3F3F46;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #8B5CF6;
}

QLineEdit:focus, QTextEdit:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid #8B5CF6;
}

/* Radio Buttons & Checkboxes */
QRadioButton, QCheckBox {
    color: #E4E4E7;
    font-weight: 500;
    spacing: 6px;
}

QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid #52525B;
    background-color: #18181B;
}

QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background-color: #8B5CF6;
    border: 1px solid #A78BFA;
}

/* Lists and Tables */
QListWidget, QTableWidget {
    background-color: #1A1A1E;
    alternate-background-color: #222226;
    color: #F4F4F5;
    border: 1px solid #2E2E33;
    border-radius: 8px;
    gridline-color: #27272A;
    outline: none;
}

QListWidget::item, QTableWidget::item {
    padding: 4px 8px;
}

QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #6D28D9;
    color: #FFFFFF;
}

QHeaderView {
    background-color: #161619;
    border: none;
}

QHeaderView::section {
    background-color: #202024;
    color: #E4E4E7;
    font-weight: 700;
    font-size: 12px;
    padding: 6px 8px;
    border-top: none;
    border-left: none;
    border-right: 1px solid #2E2E33;
    border-bottom: 2px solid #7C3AED;
}

QHeaderView::section:vertical {
    background-color: #1A1A1E;
    color: #71717A;
    font-weight: 600;
    font-size: 11px;
    padding: 4px;
    border-top: none;
    border-left: none;
    border-bottom: 1px solid #242428;
    border-right: 1px solid #2E2E33;
}

QTableCornerButton::section {
    background-color: #202024;
    border: none;
    border-bottom: 2px solid #7C3AED;
    border-right: 1px solid #2E2E33;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #3F3F46;
    border-radius: 8px;
    background-color: #27272A;
}

QTabBar::tab {
    background-color: #18181B;
    color: #A1A1AA;
    padding: 10px 22px;
    font-weight: 600;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #27272A;
    color: #C4B5FD;
    border-bottom: 3px solid #8B5CF6;
}

/* Status Badges */
QLabel#SyncBadgeConnected {
    background-color: #059669;
    color: #FFFFFF;
    border-radius: 12px;
    padding: 4px 14px;
    font-weight: bold;
    font-size: 11px;
}

QLabel#SyncBadgeDisconnected {
    background-color: #DC2626;
    color: #FFFFFF;
    border-radius: 12px;
    padding: 4px 14px;
    font-weight: bold;
    font-size: 11px;
}

/* Sleek Modern Scrollbars */
QScrollBar:vertical {
    background-color: #18181B;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #3F3F46;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background-color: #8B5CF6;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #18181B;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #3F3F46;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #8B5CF6;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ToolTip Styling */
QToolTip {
    background-color: #141416;
    color: #F4F4F5;
    border: 1px solid #7C3AED;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
}
"""

