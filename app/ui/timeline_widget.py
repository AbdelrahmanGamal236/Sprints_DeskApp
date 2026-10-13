from datetime import datetime, timedelta
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QDate, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QLinearGradient, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QToolTip, QButtonGroup
)

# Bold in both states so the checked button is not wider than the space Qt measured for it
FILTER_BUTTON_QSS = 'QPushButton { font-weight: bold; padding: 6px 14px; } QPushButton:checked { background-color: #7C3AED; color: #FFFFFF; }'


class TimelineCanvas(QWidget):
    """Custom canvas that renders the progressive Gantt/timeline schedule of tasks."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.tasks = []
        self.min_date = datetime.now()
        self.max_date = datetime.now() + timedelta(days=30)
        self.total_days = 30
        self.row_height = 46
        self.header_height = 42
        self.left_margin = 340
        self.hovered_task = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def set_tasks(self, tasks: list):
        self.tasks = tasks
        self.calculate_date_bounds()
        total_h = self.header_height + max(len(self.tasks), 1) * self.row_height + 30
        self.setMinimumHeight(total_h)
        self.update()

    def calculate_date_bounds(self):
        valid_starts = []
        valid_ends = []
        for t in self.tasks:
            s_str = t.get("planned_start_date")
            e_str = t.get("planned_end_date")
            if s_str:
                try:
                    valid_starts.append(datetime.strptime(s_str, "%Y-%m-%d"))
                except ValueError:
                    pass
            if e_str:
                try:
                    valid_ends.append(datetime.strptime(e_str, "%Y-%m-%d"))
                except ValueError:
                    pass

        now = datetime.now()
        if valid_starts and valid_ends:
            min_s = min(valid_starts)
            max_e = max(valid_ends)
            self.min_date = min(min_s, now) - timedelta(days=2)
            self.max_date = max(max_e, now + timedelta(days=3)) + timedelta(days=3)
        else:
            self.min_date = now - timedelta(days=3)
            self.max_date = now + timedelta(days=27)

        self.total_days = max((self.max_date - self.min_date).days, 7)

    def _date_to_x(self, dt: datetime, available_width: int) -> float:
        delta = (dt - self.min_date).total_seconds() / 86400.0
        pct = max(0.0, min(1.0, delta / self.total_days))
        return self.left_margin + pct * available_width

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        chart_width = max(w - self.left_margin - 30, 200)

        # Background
        painter.fillRect(0, 0, w, h, QColor("#18181B"))

        # Empty state
        if not self.tasks:
            painter.setPen(QColor("#71717A"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(QRect(0, 50, w, 100), Qt.AlignCenter, "No tasks scheduled for this project/discipline.")
            return

        # ----------------- 1. HEADER ROW (TIMELINE AXIS) -----------------
        painter.fillRect(0, 0, w, self.header_height, QColor("#141416"))
        painter.setPen(QPen(QColor("#27272A"), 1))
        painter.drawLine(0, self.header_height, w, self.header_height)
        painter.drawLine(self.left_margin, 0, self.left_margin, h)

        # Left Header Label
        painter.setPen(QColor("#C4B5FD"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QRect(16, 0, self.left_margin - 24, self.header_height), Qt.AlignVCenter | Qt.AlignLeft, "Task & Assigned Head")

        # Date Axis Ticks
        step_days = max(1, self.total_days // 10)
        curr = self.min_date
        painter.setFont(QFont("Segoe UI", 9))
        while curr <= self.max_date:
            x = self._date_to_x(curr, chart_width)
            # Vertical grid line
            painter.setPen(QPen(QColor("#27272A"), 1, Qt.DotLine))
            painter.drawLine(int(x), self.header_height, int(x), h)

            # Date text in header
            painter.setPen(QColor("#A1A1AA"))
            date_str = curr.strftime("%b %d")
            painter.drawText(QRect(int(x) - 30, 8, 60, 24), Qt.AlignCenter, date_str)

            curr += timedelta(days=step_days)

        # Today Indicator Line
        today = datetime.now()
        if self.min_date <= today <= self.max_date:
            tx = self._date_to_x(today, chart_width)
            painter.setPen(QPen(QColor("#F43F5E"), 2, Qt.DashLine))
            painter.drawLine(int(tx), 0, int(tx), h)

            # Today pill
            pill_rect = QRectF(tx - 24, 2, 48, 18)
            painter.setBrush(QColor("#F43F5E"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(pill_rect, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(pill_rect, Qt.AlignCenter, "TODAY")

        # ----------------- 2. TASK ROWS -----------------
        for idx, t in enumerate(self.tasks):
            y = self.header_height + idx * self.row_height

            # Alternating row background
            if idx % 2 == 1:
                painter.fillRect(0, y, w, self.row_height, QColor("#1C1C20"))

            # Hover highlight
            if self.hovered_task == t:
                painter.fillRect(0, y, w, self.row_height, QColor("#2D2640"))

            # Row divider
            painter.setPen(QPen(QColor("#27272A"), 1))
            painter.drawLine(0, y + self.row_height, w, y + self.row_height)

            # Left Info: Task Name, ID, Discipline Pill, Assigned Head
            name = t.get("name") or "Unnamed"
            tid = t.get("task_id") or ""
            disc = t.get("discipline_id") or "GEN"
            head_name = t.get("assigned_head_name") or (f"ID: {t['assigned_head_id']}" if t.get("assigned_head_id") else "All Heads")

            # Discipline tag, sized to its text (e.g. "Infrastructure")
            pill_font = QFont("Segoe UI", 8, QFont.Bold)
            pill_w = min(max(QFontMetrics(pill_font).horizontalAdvance(disc) + 12, 38), 96)
            disc_pill = QRectF(14, y + 13, pill_w, 20)
            painter.setBrush(QColor("#3B0764"))
            painter.setPen(QColor("#C4B5FD"))
            painter.drawRoundedRect(disc_pill, 4, 4)
            painter.setPen(QColor("#EDE9FE"))
            painter.setFont(pill_font)
            painter.drawText(disc_pill, Qt.AlignCenter, disc)

            # Task title and Head, shortened with "..." when too long (full text in the tooltip)
            text_x = int(14 + pill_w + 8)
            text_w = self.left_margin - text_x - 10
            title_font = QFont("Segoe UI", 9, QFont.DemiBold)
            painter.setPen(QColor("#F4F4F5"))
            painter.setFont(title_font)
            task_label = QFontMetrics(title_font).elidedText(f"{name} ({tid})", Qt.ElideRight, text_w)
            painter.drawText(QRect(text_x, y + 6, text_w, 18), Qt.AlignVCenter | Qt.AlignLeft, task_label)

            head_font = QFont("Segoe UI", 8)
            painter.setPen(QColor("#A1A1AA"))
            painter.setFont(head_font)
            head_str = QFontMetrics(head_font).elidedText(f"Head: {head_name}", Qt.ElideRight, text_w)
            painter.drawText(QRect(text_x, y + 24, text_w, 16), Qt.AlignVCenter | Qt.AlignLeft, head_str)

            # ----------------- PROGRESSIVE TIMELINE BAR -----------------
            s_str = t.get("planned_start_date")
            e_str = t.get("planned_end_date")
            pct = int(t.get("progress_percentage") or 0)
            stage = t.get("progress_stage") or "Not Started"

            if s_str and e_str:
                try:
                    s_dt = datetime.strptime(s_str, "%Y-%m-%d")
                    e_dt = datetime.strptime(e_str, "%Y-%m-%d")
                    bx_start = self._date_to_x(s_dt, chart_width)
                    bx_end = self._date_to_x(e_dt, chart_width)
                    bar_w = max(bx_end - bx_start, 24.0)

                    bar_y = y + 11
                    bar_h = 24.0
                    bar_rect = QRectF(bx_start, bar_y, bar_w, bar_h)

                    # Background Track
                    painter.setBrush(QColor("#27272A"))
                    painter.setPen(QPen(QColor("#3F3F46"), 1))
                    painter.drawRoundedRect(bar_rect, 6, 6)

                    # Progressive Fill
                    if pct > 0:
                        fill_w = max(bar_w * (pct / 100.0), 8.0)
                        fill_rect = QRectF(bx_start, bar_y, fill_w, bar_h)

                        # Gradient based on completion
                        grad = QLinearGradient(bx_start, bar_y, bx_start + fill_w, bar_y)
                        if pct >= 100 or stage == "Done":
                            grad.setColorAt(0.0, QColor("#059669"))
                            grad.setColorAt(1.0, QColor("#10B981"))
                        elif stage == "Revision":
                            grad.setColorAt(0.0, QColor("#D97706"))
                            grad.setColorAt(1.0, QColor("#F59E0B"))
                        else:
                            grad.setColorAt(0.0, QColor("#6D28D9"))
                            grad.setColorAt(1.0, QColor("#8B5CF6"))

                        painter.setBrush(QBrush(grad))
                        painter.setPen(Qt.NoPen)
                        painter.drawRoundedRect(fill_rect, 6, 6)

                    # Text inside bar (percentage)
                    painter.setPen(QColor("#FFFFFF"))
                    painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                    pct_text = f"{pct}%"
                    painter.drawText(bar_rect, Qt.AlignCenter, pct_text)

                    # Stage Pill after the bar
                    stage_pill_x = bx_start + bar_w + 8
                    if stage_pill_x + 85 < w:
                        stage_rect = QRectF(stage_pill_x, bar_y + 2, 78, 20)
                        if stage == "Done":
                            s_bg, s_fg = QColor("#064E3B"), QColor("#34D399")
                        elif stage == "In Progress":
                            s_bg, s_fg = QColor("#2E1065"), QColor("#C4B5FD")
                        elif stage == "Revision":
                            s_bg, s_fg = QColor("#78350F"), QColor("#FBBF24")
                        elif stage == "Hold":
                            s_bg, s_fg = QColor("#7C2D12"), QColor("#FB923C")
                        else:
                            s_bg, s_fg = QColor("#27272A"), QColor("#A1A1AA")

                        painter.setBrush(s_bg)
                        painter.setPen(Qt.NoPen)
                        painter.drawRoundedRect(stage_rect, 4, 4)
                        painter.setPen(s_fg)
                        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                        painter.drawText(stage_rect, Qt.AlignCenter, stage.upper())

                except Exception:
                    pass

    def mouseMoveEvent(self, event):
        pos = event.position()
        y = pos.y()
        chart_w = max(self.width() - self.left_margin - 30, 200)

        hit_task = None
        if y > self.header_height:
            row_idx = int((y - self.header_height) // self.row_height)
            if 0 <= row_idx < len(self.tasks):
                hit_task = self.tasks[row_idx]

        if hit_task != self.hovered_task:
            self.hovered_task = hit_task
            self.update()

        if hit_task:
            s_date = hit_task.get("planned_start_date") or "TBD"
            e_date = hit_task.get("planned_end_date") or "TBD"
            pct = hit_task.get("progress_percentage", 0)
            stage = hit_task.get("progress_stage", "Not Started")
            head = hit_task.get("assigned_head_name") or hit_task.get("assigned_head_id") or "All Heads"
            revs = hit_task.get("revision_count", 0)
            team_assign = hit_task.get("latest_assigned_to") or "Unassigned team member"

            tip = (
                f"<b>{hit_task.get('name')}</b> ({hit_task.get('task_id')})<br/>"
                f"<b>Discipline:</b> {hit_task.get('discipline_name')}<br/>"
                f"<b>Assigned Head:</b> {head}<br/>"
                f"<b>Schedule:</b> {s_date} to {e_date}<br/>"
                f"<b>Progress:</b> {pct}% ({stage})<br/>"
                f"<b>Revisions:</b> {revs} logs<br/>"
                f"<b>Team Member:</b> {team_assign}"
            )
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()


class ProjectProgressiveTimelineWidget(QWidget):
    """
    Executive Project Progressive Timeline & Gantt Chart Component.
    Complies with UI/UX Golden Ratio and Zinc/Purple dark theme standards.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_tasks = []
        self.active_discipline = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ----------------- 1. METRICS & OVERALL PROGRESS CARD -----------------
        self.card_summary = QFrame()
        self.card_summary.setObjectName("CardFrame")
        c_layout = QVBoxLayout(self.card_summary)
        c_layout.setContentsMargins(18, 14, 18, 14)
        c_layout.setSpacing(10)

        top_info = QHBoxLayout()
        self.lbl_prj_name = QLabel("Project Progressive Schedule Timeline", objectName="HeaderTitle")
        top_info.addWidget(self.lbl_prj_name)
        top_info.addStretch()

        # Stats badges
        self.lbl_total_tasks = QLabel("Tasks: 0")
        self.lbl_total_tasks.setStyleSheet("background-color: #27272A; color: #F4F4F5; padding: 4px 10px; border-radius: 6px; font-weight: bold;")
        top_info.addWidget(self.lbl_total_tasks)

        self.lbl_done_tasks = QLabel("Done: 0")
        self.lbl_done_tasks.setStyleSheet("background-color: #064E3B; color: #34D399; padding: 4px 10px; border-radius: 6px; font-weight: bold;")
        top_info.addWidget(self.lbl_done_tasks)

        self.lbl_in_prog = QLabel("In Progress: 0")
        self.lbl_in_prog.setStyleSheet("background-color: #2E1065; color: #C4B5FD; padding: 4px 10px; border-radius: 6px; font-weight: bold;")
        top_info.addWidget(self.lbl_in_prog)

        c_layout.addLayout(top_info)

        # Progressive Progress Bar
        bar_row = QHBoxLayout()
        bar_row.setSpacing(12)

        self.progress_track = QFrame()
        self.progress_track.setFixedHeight(12)
        self.progress_track.setStyleSheet("background-color: #18181B; border-radius: 6px; border: 1px solid #3F3F46;")
        track_layout = QHBoxLayout(self.progress_track)
        track_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_fill = QFrame()
        self.progress_fill.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6D28D9, stop:1 #A78BFA); border-radius: 5px;")
        track_layout.addWidget(self.progress_fill)
        self.progress_spacer = QFrame()
        track_layout.addWidget(self.progress_spacer)

        bar_row.addWidget(self.progress_track, 1)

        self.lbl_pct = QLabel("0% Overall", objectName="SubTitle")
        self.lbl_pct.setStyleSheet("font-weight: bold; color: #C4B5FD; min-width: 90px;")
        bar_row.addWidget(self.lbl_pct)

        c_layout.addLayout(bar_row)
        layout.addWidget(self.card_summary)

        # ----------------- 2. DISCIPLINE FILTER BAR -----------------
        self.filter_scroll = QScrollArea()
        self.filter_scroll.setFixedHeight(62)
        self.filter_scroll.setWidgetResizable(True)
        self.filter_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        filter_container = QWidget()
        self.filter_layout = QHBoxLayout(filter_container)
        self.filter_layout.setContentsMargins(4, 4, 4, 4)
        self.filter_layout.setSpacing(6)

        self.filter_group = QButtonGroup(self)
        self.btn_filter_all = QPushButton("All Disciplines")
        self.btn_filter_all.setCheckable(True)
        self.btn_filter_all.setChecked(True)
        self.btn_filter_all.setStyleSheet(FILTER_BUTTON_QSS)
        self.btn_filter_all.clicked.connect(lambda: self.on_discipline_filter(None))
        self.filter_group.addButton(self.btn_filter_all)
        self.filter_layout.addWidget(self.btn_filter_all)
        self.filter_layout.addStretch()

        self.filter_scroll.setWidget(filter_container)
        layout.addWidget(self.filter_scroll)

        # ----------------- 3. SCROLLABLE TIMELINE CANVAS -----------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: 1px solid #3F3F46; border-radius: 8px; background-color: #18181B; }")

        self.canvas = TimelineCanvas()
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, 1)

    def load_timeline_data(self, data: dict):
        if not data:
            self.all_tasks = []
            self.canvas.set_tasks([])
            self.lbl_prj_name.setText("Select a Project to View Progressive Timeline")
            self.lbl_pct.setText("0% Overall")
            self.lbl_total_tasks.setText("Tasks: 0")
            self.lbl_done_tasks.setText("Done: 0")
            self.lbl_in_prog.setText("In Progress: 0")
            return

        p_name = data.get("project_name") or data.get("project_id") or "Project"
        self.lbl_prj_name.setText(f"Project Timeline: {p_name} ({data.get('project_id')})")

        total = data.get("total_tasks", 0)
        done = data.get("completed_tasks", 0)
        in_prog = data.get("in_progress_tasks", 0)
        overall = data.get("overall_progress_percentage", 0)

        self.lbl_total_tasks.setText(f"Tasks: {total}")
        self.lbl_done_tasks.setText(f"Done: {done}")
        self.lbl_in_prog.setText(f"In Progress: {in_prog}")
        self.lbl_pct.setText(f"{overall}% Overall")

        # Update progressive bar layout ratios
        fill_ratio = max(1, overall)
        space_ratio = max(0, 100 - overall)
        self.progress_track.layout().setStretch(0, fill_ratio)
        self.progress_track.layout().setStretch(1, space_ratio)

        self.all_tasks = data.get("tasks", [])
        # A discipline filter from the previous project must not hide this project's tasks
        if self.active_discipline and not any(t.get("discipline_id") == self.active_discipline for t in self.all_tasks):
            self.active_discipline = None
            self.btn_filter_all.setChecked(True)
        self.rebuild_discipline_filters()
        self.apply_filter()

    def rebuild_discipline_filters(self):
        # Clear existing discipline buttons except "All"
        while self.filter_layout.count() > 2:
            item = self.filter_layout.takeAt(1)
            widget = item.widget()
            if widget:
                self.filter_group.removeButton(widget)
                widget.deleteLater()

        # Gather active disciplines from tasks
        seen_discs = {}
        for t in self.all_tasks:
            d_id = t.get("discipline_id")
            d_name = t.get("discipline_name") or d_id
            if d_id and d_id not in seen_discs:
                seen_discs[d_id] = d_name

        for d_id, d_name in seen_discs.items():
            btn = QPushButton(f"{d_name} ({d_id})")
            btn.setCheckable(True)
            btn.setChecked(d_id == self.active_discipline)
            btn.setStyleSheet(FILTER_BUTTON_QSS)
            btn.clicked.connect(lambda _, did=d_id: self.on_discipline_filter(did))
            self.filter_group.addButton(btn)
            self.filter_layout.insertWidget(self.filter_layout.count() - 1, btn)

    def on_discipline_filter(self, disc_id):
        self.active_discipline = disc_id
        self.apply_filter()

    def apply_filter(self):
        if not self.active_discipline:
            filtered = list(self.all_tasks)
        else:
            filtered = [t for t in self.all_tasks if t.get("discipline_id") == self.active_discipline]

        self.canvas.set_tasks(filtered)
