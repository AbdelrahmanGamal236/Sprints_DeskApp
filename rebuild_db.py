import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from app.core.config import DEFAULT_DISCIPLINES, ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
from app.database.db_manager import DBManager, hash_password

def run_rebuild():
    db_file = Path("data/central_app.db")
    backup_dir = Path("data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if db_file.exists():
        backup_path = backup_dir / f"central_app_backup_pre_rebuild_{timestamp}.db"
        shutil.copy2(db_file, backup_path)
        print(f"Backed up existing database to: {backup_path}")
        
        # Remove current DB file to do a 100% clean rebuild without schema or constraint conflicts
        db_file.unlink()
        print("Removed old database file for clean rebuild.")
    
    # Initialize brand new database with clean schema
    print("Initializing fresh database via DBManager...")
    db = DBManager(standalone=False)
    
    # Insert clean standard data
    today_str = datetime.now().strftime("%Y-%m-%d")
    end_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Projects
        cursor.execute("SELECT project_id FROM projects WHERE project_id = 'PRJ-01'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                           ("PRJ-01", "Project Alpha", "Main Core System Development"))
            cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                           ("PRJ-02", "Project Beta", "Hardware LAN Setup & Wiring"))
            print("Seeded projects PRJ-01 and PRJ-02.")
            
        # 2. Seed Head 1001 with default discipline AI
        cursor.execute("SELECT user_id FROM users WHERE user_id = '1001'")
        if not cursor.fetchone():
            pwd_hash, pwd_salt = hash_password("1001")
            cursor.execute("""
            INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password, discipline_id)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """, ("1001", "Eng. Abdelrahman", pwd_hash, pwd_salt, ROLE_HEAD, "AI"))
            print("Seeded Head 1001 (Eng. Abdelrahman) under AI.")
            
        # 3. Assign all heads to PRJ-01 and PRJ-02 in employee_projects
        cursor.execute("SELECT user_id FROM users WHERE role = 'HEAD'")
        heads = [r["user_id"] for r in cursor.fetchall()]
        for hid in heads:
            cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, 'PRJ-01')", (hid,))
            cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, 'PRJ-02')", (hid,))
        print(f"Assigned {len(heads)} heads to PRJ-01 and PRJ-02.")
        
        # 4. Seed clean, initial tasks with all disciplines
        seed_tasks = [
            ("TSK-01", "PRJ-01", "Urban Master Plan Coordination", "URB", "4003"),
            ("TSK-02", "PRJ-01", "Structural Core Shear Walls & Foundations", "STR", "4007"),
            ("TSK-03", "PRJ-01", "Interior Fit-Out & Material Selection", "INT", "4013"),
            ("TSK-04", "PRJ-01", "Architectural Facade & Elevation Drafting", "ARC", "4033"),
            ("TSK-05", "PRJ-01", "BIM 3D Model Federation & Clash Resolution", "BIM", "4018"),
            ("TSK-06", "PRJ-01", "HVAC Chilled Water & Ducting Layout", "MEC", "5026"),
            ("TSK-07", "PRJ-01", "Electrical Main Distribution Board Wiring", "ELE", "5079"),
            ("TSK-08", "PRJ-01", "AI Predictive Scheduling & Automation", "AI", "5051"),
            ("TSK-09", "PRJ-01", "Site Quality Assurance & Standards Audit", "QC", None),
            ("TSK-10", "PRJ-01", "Infrastructure Drainage & Trench Cabling", "Infrastructure", "5065"),
        ]
        
        for tid, pid, tname, disc, hid in seed_tasks:
            cursor.execute("""
            INSERT INTO tasks (
                task_id, project_id, name, description, is_hidden,
                discipline_id, planned_start_date, planned_end_date, assigned_head_id
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
            """, (tid, pid, tname, f"Seed Task for {disc}", disc, today_str, end_str, hid))
        
        conn.commit()
        print(f"Seeded {len(seed_tasks)} baseline tasks across all disciplines.")

    print("\nDatabase rebuild successfully completed!")

if __name__ == "__main__":
    run_rebuild()
