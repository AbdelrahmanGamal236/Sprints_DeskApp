from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QFrame, QCheckBox, QDateEdit,
    QFileDialog, QMessageBox, QDialog
)

from app.network.client import NetworkClient, run_async
from app.ui.components import ToastNotifier, describe_error


def save_excel_report(parent, raw_bytes: bytes, default_name: str):
    """Ask where to save a server-generated workbook and write it."""
    file_path, _ = QFileDialog.getSaveFileName(parent, "Save Excel Report", default_name, "Excel Files (*.xlsx)")
    if not file_path:
        return
    try:
        with open(file_path, "wb") as f:
            f.write(raw_bytes)
    except OSError as e:
        QMessageBox.critical(parent, "Save Failed", f"Could not save the report:\n{e}")
        return
    QMessageBox.information(parent, "Success", f"Excel report saved to:\n{file_path}")


class ExportPanel(QWidget):
    """
    Excel export with filters (project, discipline, Head, optional date range). The workbook is built on
    the Central Server; this panel only collects filters and saves the downloaded file.
    """
    def __init__(self, net_client: NetworkClient, toast: ToastNotifier = None, parent=None):
        super().__init__(parent)
        self.net_client = net_client
        self.toast = toast
        self.users_data = []

        layout = QVBoxLayout(self)
        card = QFrame(self)
        card.setObjectName("CardFrame")
        c_layout = QVBoxLayout(card)
        c_layout.addWidget(QLabel("Export Progress Logs to Excel", objectName="SubTitle"))

        row = QHBoxLayout()
        self.cmb_project = self._combo(row, "Project:")
        self.cmb_discipline = self._combo(row, "Discipline:")
        self.cmb_head = self._combo(row, "Head:")
        self.cmb_discipline.currentIndexChanged.connect(self._fill_heads)
        c_layout.addLayout(row)

        dates = QHBoxLayout()
        self.chk_dates = QCheckBox("Only logs submitted between:", self)
        dates.addWidget(self.chk_dates)
        dates.addWidget(QLabel("From", self))
        self.dt_from = QDateEdit(QDate.currentDate().addMonths(-1), self)
        self.dt_from.setCalendarPopup(True)
        dates.addWidget(self.dt_from)
        dates.addWidget(QLabel("To", self))
        self.dt_to = QDateEdit(QDate.currentDate(), self)
        self.dt_to.setCalendarPopup(True)
        dates.addWidget(self.dt_to)
        dates.addStretch()
        self.chk_dates.toggled.connect(self._toggle_dates)
        self._toggle_dates(False)
        c_layout.addLayout(dates)

        hint = QLabel("The workbook has an 'All Logs' sheet (every log, newest first), a 'Task Summary' sheet (each "
                      "task's dates and latest status), one sheet per discipline and a 'Report Info' sheet. "
                      "Hidden or deleted projects, tasks and disciplines are labelled and their logs are kept.", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        c_layout.addWidget(hint)

        self.btn_export = QPushButton("Generate Excel Report", self)
        self.btn_export.setMinimumHeight(44)
        self.btn_export.clicked.connect(self.on_export)
        c_layout.addWidget(self.btn_export)
        c_layout.addStretch()
        layout.addWidget(card)

        self.net_client.data_changed.connect(
            lambda scopes: bool(set(scopes) & {"projects", "disciplines", "users"}) and self.reload())
        self.net_client.connection_status_changed.connect(lambda ok, _m: ok and self.reload())
        self.reload()

    def _combo(self, row, label):
        box = QVBoxLayout()
        box.addWidget(QLabel(label, objectName="FieldLabel"))
        cmb = QComboBox(self)
        cmb.setMinimumWidth(180)
        box.addWidget(cmb)
        row.addLayout(box)
        return cmb

    def _toggle_dates(self, on: bool):
        self.dt_from.setEnabled(on)
        self.dt_to.setEnabled(on)

    def _notify(self, text: str, error: bool = False):
        if self.toast:
            self.toast.show_message(text, is_error=error, duration_ms=8000)

    # ------------------------------------------------------------------ lists
    def reload(self):
        if not self.net_client.is_connected:
            return
        err = lambda e: self._notify(describe_error(e), True)
        self.net_client.call("GET_PROJECTS", {"include_hidden": True}, self._on_projects, err)
        self.net_client.call("GET_DISCIPLINES", {"include_hidden": True}, self._on_disciplines, err)
        self.net_client.call("GET_USERS", {"role": "HEAD"}, self._on_users, err)

    @staticmethod
    def _refill(cmb: QComboBox, all_label: str, items: list):
        current = cmb.currentData()
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(all_label, None)
        for label, value in items:
            cmb.addItem(label, value)
        idx = cmb.findData(current)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)
        cmb.blockSignals(False)

    def _on_projects(self, r):
        self._refill(self.cmb_project, "All Projects",
                     [(f"{p['name']} ({p['project_id']})" + (" (Hidden)" if p.get("is_hidden") else ""), p["project_id"])
                      for p in r.get("projects", [])])

    def _on_disciplines(self, r):
        self._refill(self.cmb_discipline, "All Disciplines",
                     [(f"{d['name']} ({d['discipline_id']})" + (" (Hidden)" if d.get("is_hidden") else ""), d["discipline_id"])
                      for d in r.get("disciplines", [])])
        self._fill_heads()

    def _on_users(self, r):
        self.users_data = [u for u in r.get("users", []) if u.get("role") == "HEAD"]
        self._fill_heads()

    def _fill_heads(self, *_):
        disc = self.cmb_discipline.currentData()
        self._refill(self.cmb_head, "All Heads",
                     [(f"{u.get('full_name') or u['user_id']} ({u['user_id']})", u["user_id"])
                      for u in self.users_data if not disc or u.get("discipline_id") == disc])

    # ------------------------------------------------------------------ export
    def current_filters(self) -> dict:
        filters = {
            "project_id": self.cmb_project.currentData(),
            "discipline_id": self.cmb_discipline.currentData(),
            "employee_id": self.cmb_head.currentData(),
        }
        if self.chk_dates.isChecked():
            filters["start_date"] = self.dt_from.date().toString("yyyy-MM-dd")
            filters["end_date"] = self.dt_to.date().toString("yyyy-MM-dd")
        return filters

    def on_export(self):
        if self.chk_dates.isChecked() and self.dt_from.date() > self.dt_to.date():
            QMessageBox.warning(self, "Invalid Dates", "The 'From' date cannot be after the 'To' date.")
            return
        self.btn_export.setEnabled(False)
        self._notify("Generating the Excel report on the Central Server...")
        run_async(self.net_client.export_excel(self.current_filters()), self._on_ready, self._on_failed)

    def _on_failed(self, exc):
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "Export Error", describe_error(exc))

    def _on_ready(self, result):
        self.btn_export.setEnabled(True)
        raw_bytes, default_name, reply = result
        logs, tasks = reply.get("log_count"), reply.get("task_count")
        if logs == 0 and tasks == 0:
            QMessageBox.information(self, "Nothing to Export",
                                    "No tasks or progress logs match these filters. Change the filters and try again.")
            return
        if logs is not None:
            self._notify(f"Report ready: {logs} progress logs, {tasks} tasks.")
        save_excel_report(self, raw_bytes, default_name)


class ExportDialog(QDialog):
    """ExportPanel in its own window (used by the COO dashboard)."""
    def __init__(self, net_client: NetworkClient, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Excel Report")
        self.setMinimumWidth(760)
        layout = QVBoxLayout(self)
        self.panel = ExportPanel(net_client, parent=self)
        layout.addWidget(self.panel)
