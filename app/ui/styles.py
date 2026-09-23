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
    background-color: #27272A;
    border-radius: 10px;
    border: 1px solid #3F3F46;
    padding: 16px;
}

/* Splitter */
QSplitter::handle {
    background-color: #3F3F46;
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
    padding: 9px 18px;
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
    background-color: #3F3F46;
    color: #71717A;
}

QPushButton#DangerButton {
    background-color: #EF4444;
}

QPushButton#DangerButton:hover {
    background-color: #DC2626;
}

QPushButton#SuccessButton {
    background-color: #10B981;
}

QPushButton#SuccessButton:hover {
    background-color: #059669;
}

/* LineEdits and TextEdits */
QLineEdit, QTextEdit, QDateEdit, QComboBox {
    background-color: #18181B;
    color: #F4F4F5;
    border: 1px solid #3F3F46;
    border-radius: 8px;
    padding: 9px 12px;
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
    background-color: #27272A;
    color: #F4F4F5;
    border: 1px solid #3F3F46;
    border-radius: 8px;
    gridline-color: #3F3F46;
}

QListWidget::item, QTableWidget::item {
    padding: 6px;
}

QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #7C3AED;
    color: #FFFFFF;
}

QHeaderView::section {
    background-color: #18181B;
    color: #C4B5FD;
    padding: 8px;
    font-weight: bold;
    border: 1px solid #3F3F46;
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
"""
