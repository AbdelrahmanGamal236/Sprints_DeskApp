import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from pathlib import Path
from app.database.db_manager import DBManager

class ExcelExportService:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager

    def export_logs_to_excel(self, output_path: str = None, project_id: str = None,
                             discipline_id: str = None, employee_id: str = None,
                             start_date: str = None, end_date: str = None) -> bytes:
        """
        Exports progress logs to an Excel workbook (.xlsx).
        Supports multi-sheet per discipline when discipline_id is None / "ALL".
        Returns the raw binary bytes of the workbook, and saves to output_path if provided.
        """
        # Fetch all matching logs
        logs = self.db.get_progress_logs(
            project_id=project_id,
            discipline_id=discipline_id,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date
        )

        wb = openpyxl.Workbook()
        # Remove default sheet so we add explicitly named sheets
        default_sheet = wb.active

        # Styling definitions
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='D1D5DB'),
            right=Side(style='thin', color='D1D5DB'),
            top=Side(style='thin', color='D1D5DB'),
            bottom=Side(style='thin', color='D1D5DB')
        )
        data_font = Font(name="Calibri", size=10)
        hidden_font = Font(name="Calibri", size=10, italic=True, color="6B7280")

        headers = [
            "Log ID", "Employee ID", "Employee Name", "Head Discipline",
            "Project Name", "Task ID", "Task Name", "Task Discipline", "Assigned To",
            "Entry Context", "Start Date", "End Date", "Task Status",
            "Notes", "Submission Time", "Sync Status"
        ]

        def populate_sheet(ws, sheet_rows, title):
            ws.title = title[:31] # Excel max sheet title is 31 chars
            ws.append(headers)

            # Style header row
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = thin_border
            ws.row_dimensions[1].height = 28

            # Style data rows
            for r_idx, r in enumerate(sheet_rows, start=2):
                p_display = r["project_name"] or r["project_id"] or "Unknown Project"
                if r["project_hidden"]:
                    p_display += " (Hidden)"

                t_display = r["task_name"] or r["task_id"] or "Unknown Task"
                if r["task_hidden"]:
                    t_display += " (Hidden)"

                entry_type = r.get("entry_type") or "NEW"
                rev_num = r.get("revision_number") or 0
                if entry_type == "REVISION":
                    ctx_display = f"Revision (R{rev_num})"
                elif entry_type == "CONTINUATION":
                    ctx_display = "Continuation"
                else:
                    ctx_display = "New Task"

                task_disc = r.get("task_discipline_name") or r.get("task_discipline_id") or "Unassigned"
                head_disc = r.get("head_discipline_name") or r.get("discipline_id") or "Unassigned"

                row_data = [
                    r["log_id"],
                    r["employee_id"],
                    r.get("employee_name") or r["employee_id"],
                    head_disc,
                    p_display,
                    r["task_id"],
                    t_display,
                    task_disc,
                    r.get("assigned_to") or "",
                    ctx_display,
                    r["start_date"],
                    r["end_date"],
                    r["progress_stage"],
                    r.get("notes") or "",
                    r["submitted_at"],
                    r.get("sync_status") or "SYNCED"
                ]
                ws.append(row_data)

                for col_idx in range(1, len(headers) + 1):
                    cell = ws.cell(row=r_idx, column=col_idx)
                    cell.font = hidden_font if (r["project_hidden"] or r["task_hidden"]) else data_font
                    cell.border = thin_border
                    if col_idx in (1, 2, 4, 6, 8, 10, 11, 12, 13, 15, 16):
                        cell.alignment = Alignment(horizontal="center", vertical="center")

                ws.row_dimensions[r_idx].height = 20

            # Footer
            footer_row = ws.max_row + 2
            ws.cell(row=footer_row, column=1, value="© All Rights Reserved to Eng. Abdelrahman Gamal & Eng. Tolimy")
            ws.cell(row=footer_row, column=1).font = Font(name="Calibri", size=10, italic=True, bold=True, color="475569")

            # Column auto-widths
            for col in ws.columns:
                max_len = max(len(str(c.value or '')) for c in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        # 1. Main Sheet "All Logs"
        populate_sheet(default_sheet, logs, "All Logs")

        # 2. Per-Discipline sheets if discipline_id is None / All
        if not discipline_id:
            # Group logs by task discipline
            disciplines = self.db.get_disciplines(include_hidden=True)
            disc_map = {d["discipline_id"]: d["name"] for d in disciplines}

            # Map logs to discipline
            grouped = {}
            for l in logs:
                d_id = l.get("task_discipline_id") or l.get("discipline_id") or "Unassigned"
                grouped.setdefault(d_id, []).append(l)

            for d_id, d_logs in grouped.items():
                if d_logs: # Skip empty ones
                    d_name = disc_map.get(d_id, d_id)
                    ws_disc = wb.create_sheet()
                    populate_sheet(ws_disc, d_logs, d_name)

        import io
        buf = io.BytesIO()
        wb.save(buf)
        excel_bytes = buf.getvalue()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(excel_bytes)

        return excel_bytes
