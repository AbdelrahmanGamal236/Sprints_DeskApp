import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from pathlib import Path
from app.database.db_manager import DBManager

class ExcelExportService:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager

    def export_logs_to_excel(self, output_path: str, project_id: str = None) -> str:
        """
        Exports logs to an Excel file (.xlsx).
        If project_id is provided, filters for that project only.
        Returns the absolute file path of the generated report.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT 
                l.log_id,
                l.employee_id,
                p.name AS project_name,
                p.is_hidden AS project_hidden,
                t.name AS task_name,
                t.is_hidden AS task_hidden,
                l.start_date,
                l.end_date,
                l.progress_percentage,
                l.progress_stage,
                l.entry_type,
                l.revision_number,
                l.notes,
                l.submitted_at,
                l.sync_status
            FROM progress_logs l
            LEFT JOIN projects p ON l.project_id = p.project_id
            LEFT JOIN tasks t ON l.task_id = t.task_id
            """
            params = []
            if project_id:
                query += " WHERE l.project_id = ?"
                params.append(project_id)

            query += " ORDER BY l.submitted_at DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Progress Logs"

        # Styling
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid") # Dark slate
        thin_border = Border(
            left=Side(style='thin', color='D1D5DB'),
            right=Side(style='thin', color='D1D5DB'),
            top=Side(style='thin', color='D1D5DB'),
            bottom=Side(style='thin', color='D1D5DB')
        )
        data_font = Font(name="Calibri", size=10)
        hidden_font = Font(name="Calibri", size=10, italic=True, color="6B7280")

        headers = [
            "Log ID", "Employee ID", "Project Name", "Task Name", "Entry Context", 
            "Start Date", "End Date", "Task Status", 
            "Notes", "Submission Time", "Sync Status"
        ]
        ws.append(headers)

        # Apply header styles
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        ws.row_dimensions[1].height = 28

        # Populate rows
        for row_idx, r in enumerate(rows, start=2):
            proj_display = r["project_name"] or "Unknown Project"
            if r["project_hidden"]:
                proj_display += " (Hidden)"

            task_display = r["task_name"] or "Unknown Task"
            if r["task_hidden"]:
                task_display += " (Hidden)"

            entry_type = r["entry_type"] if ("entry_type" in r.keys() and r["entry_type"]) else "NEW"
            rev_num = r["revision_number"] if ("revision_number" in r.keys() and r["revision_number"]) else 0

            if entry_type == "REVISION":
                ctx_display = f"Revision (R{rev_num})"
            elif entry_type == "CONTINUATION":
                ctx_display = "Continuation"
            else:
                ctx_display = "New Task"

            row_data = [
                r["log_id"],
                r["employee_id"],
                proj_display,
                task_display,
                ctx_display,
                r["start_date"],
                r["end_date"],
                r["progress_stage"],
                r["notes"] or "",
                r["submitted_at"],
                r["sync_status"]
            ]
            ws.append(row_data)

            # Row styling
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = hidden_font if (r["project_hidden"] or r["task_hidden"]) else data_font
                cell.border = thin_border
                if col_idx in (1, 2, 5, 6, 7, 10, 11):
                    cell.alignment = Alignment(horizontal="center", vertical="center")

            ws.row_dimensions[row_idx].height = 20

        # Add Footer Row in Excel
        footer_row = ws.max_row + 2
        ws.cell(row=footer_row, column=1, value="© All Rights Reserved to Eng. Abdelrahman Gamal & Eng. Tolimy")
        ws.cell(row=footer_row, column=1).font = Font(name="Calibri", size=10, italic=True, bold=True, color="475569")

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(output_path)
        return str(Path(output_path).resolve())
