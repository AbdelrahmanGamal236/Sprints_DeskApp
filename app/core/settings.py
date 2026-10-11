import os

from PySide6.QtCore import QSettings

ORGANIZATION = "SprintsDeskApp"


def app_settings(name: str) -> QSettings:
    """
    Per-user UI settings (remembered server IP, layout).
    DESKAPP_SETTINGS_DIR stores them in INI files under that folder instead of the Windows registry,
    which isolates tests and lets several client instances run side by side on one PC.
    """
    folder = os.environ.get("DESKAPP_SETTINGS_DIR")
    if folder:
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
        return QSettings(QSettings.IniFormat, QSettings.UserScope, ORGANIZATION, name)
    return QSettings(ORGANIZATION, name)
