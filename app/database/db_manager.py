import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from app.core.config import CENTRAL_DB_PATH, CLIENT_QUEUE_DB_PATH, ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
from app.core.auth import hash_password

class DBManager:
    def __init__(self, central_db_path: Path = CENTRAL_DB_PATH):
        self.db_path = central_db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                full_name TEXT,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('HEAD', 'ADMIN', 'COO', 'SUPER_ADMIN')),
                must_change_password INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Auto-Migration checks for users
            cursor.execute("PRAGMA table_info(users)")
            user_cols = [col["name"] for col in cursor.fetchall()]
            if "full_name" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

            # Ensure default users have full names
            cursor.execute("UPDATE users SET full_name = 'Eng. Abdelrahman' WHERE user_id = '1001' AND (full_name IS NULL OR full_name = '')")
            cursor.execute("UPDATE users SET full_name = 'Admin Manager' WHERE user_id = 'admin' AND (full_name IS NULL OR full_name = '')")
            cursor.execute("UPDATE users SET full_name = 'Chief Operating Officer' WHERE user_id = 'coo' AND (full_name IS NULL OR full_name = '')")
            cursor.execute("UPDATE users SET full_name = 'System Super Admin' WHERE user_id = 'superadmin' AND (full_name IS NULL OR full_name = '')")

            # Projects table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Tasks table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );
            """)

            # Employee Projects Assignment
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_projects (
                employee_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(employee_id, project_id),
                FOREIGN KEY(employee_id) REFERENCES users(user_id),
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );
            """)

            # Progress Logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS progress_logs (
                log_id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                progress_percentage INTEGER DEFAULT 0,
                progress_stage TEXT NOT NULL,
                entry_type TEXT DEFAULT 'NEW',
                revision_number INTEGER DEFAULT 0,
                notes TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status TEXT DEFAULT 'SYNCED',
                FOREIGN KEY(employee_id) REFERENCES users(user_id),
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            """)

            # Auto-Migration checks for progress_logs
            cursor.execute("PRAGMA table_info(progress_logs)")
            columns = [col["name"] for col in cursor.fetchall()]
            if "entry_type" not in columns:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN entry_type TEXT DEFAULT 'NEW'")
            if "revision_number" not in columns:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN revision_number INTEGER DEFAULT 0")

            # Priority Notifications
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS priority_notifications (
                notification_id TEXT PRIMARY KEY,
                coo_id TEXT NOT NULL,
                target_employee_id TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'ACCEPTED', 'DENIED')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP,
                FOREIGN KEY(coo_id) REFERENCES users(user_id),
                FOREIGN KEY(target_employee_id) REFERENCES users(user_id)
            );
            """)

            # Task Proposals (Head requests -> Admin approves/rejects)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_proposals (
                proposal_id TEXT PRIMARY KEY,
                task_id TEXT,
                project_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                proposed_by_id TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
                admin_id TEXT,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decided_at TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(proposed_by_id) REFERENCES users(user_id)
            );
            """)

            # Auto-Migration for tasks (add proposed_by_id)
            cursor.execute("PRAGMA table_info(tasks)")
            task_cols = [col["name"] for col in cursor.fetchall()]
            if "proposed_by_id" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN proposed_by_id TEXT")

            conn.commit()
        
        self.seed_defaults()

    def seed_defaults(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check default superadmin
            cursor.execute("SELECT * FROM users WHERE user_id = 'superadmin'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("superadmin")
                cursor.execute(
                    "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                    ("superadmin", "System Super Admin", pwd_hash, pwd_salt, ROLE_SUPER_ADMIN, 0)
                )

            # Check default admin
            cursor.execute("SELECT * FROM users WHERE user_id = 'admin'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("admin")
                cursor.execute(
                    "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                    ("admin", "Admin Manager", pwd_hash, pwd_salt, ROLE_ADMIN, 0)
                )

            # Check default coo
            cursor.execute("SELECT * FROM users WHERE user_id = 'coo'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("coo")
                cursor.execute(
                    "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                    ("coo", "Chief Operating Officer", pwd_hash, pwd_salt, ROLE_COO, 0)
                )

            # Check default sample employee (Head 1001)
            cursor.execute("SELECT * FROM users WHERE user_id = '1001'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("1001")
                cursor.execute(
                    "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                    ("1001", "Eng. Abdelrahman", pwd_hash, pwd_salt, ROLE_HEAD, 1)
                )

            # Check sample projects
            cursor.execute("SELECT * FROM projects")
            if not cursor.fetchall():
                p1_id = "PRJ-01"
                p2_id = "PRJ-02"
                cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                               (p1_id, "Project Alpha", "Main Core System Development"))
                cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                               (p2_id, "Project Beta", "Hardware LAN Setup & Wiring"))

                # Sample Tasks
                cursor.execute("INSERT INTO tasks (task_id, project_id, name, description) VALUES (?, ?, ?, ?)",
                               ("TSK-01", p1_id, "Database Schema & Migration", "Design SQLite schema"))
                cursor.execute("INSERT INTO tasks (task_id, project_id, name, description) VALUES (?, ?, ?, ?)",
                               ("TSK-02", p1_id, "PySide6 GUI Layout", "Build Head workspace"))
                cursor.execute("INSERT INTO tasks (task_id, project_id, name, description) VALUES (?, ?, ?, ?)",
                               ("TSK-03", p2_id, "Router & Switch Config", "Configure local LAN TCP/IP"))

                # Assign 1001 to both projects
                cursor.execute("INSERT INTO employee_projects (employee_id, project_id) VALUES (?, ?)", ("1001", p1_id))
                cursor.execute("INSERT INTO employee_projects (employee_id, project_id) VALUES (?, ?)", ("1001", p2_id))

            conn.commit()

    def get_next_revision_number(self, employee_id: str, project_id: str, task_id: str) -> int:
        """Calculates the next revision number R{N} for an employee on a specific task."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_rev
            FROM progress_logs
            WHERE employee_id = ? AND project_id = ? AND task_id = ? AND entry_type = 'REVISION'
            """, (employee_id, project_id, task_id))
            row = cursor.fetchone()
            return row["next_rev"] if row else 1

    def generate_next_task_id(self, project_id: str = None) -> str:
        """Auto-generates sequential task ID (e.g. TSK-04) without collisions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT task_id FROM tasks WHERE task_id LIKE 'TSK-%'")
            t_ids = [row["task_id"] for row in cursor.fetchall() if row["task_id"]]
            cursor.execute("SELECT task_id FROM task_proposals WHERE task_id LIKE 'TSK-%'")
            p_ids = [row["task_id"] for row in cursor.fetchall() if row["task_id"]]

            max_num = 0
            for tid in t_ids + p_ids:
                try:
                    num_part = int(tid.split("-")[1])
                    if num_part > max_num:
                        max_num = num_part
                except (IndexError, ValueError):
                    continue
            return f"TSK-{max_num + 1:02d}"

    def create_task_proposal(self, project_id: str, task_name: str, proposed_by_id: str) -> dict:
        proposal_id = f"PROP-{uuid.uuid4().hex[:8].upper()}"
        task_id = self.generate_next_task_id(project_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO task_proposals (proposal_id, task_id, project_id, task_name, proposed_by_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            """, (proposal_id, task_id, project_id, task_name, proposed_by_id, now_str))
            conn.commit()
        return {
            "proposal_id": proposal_id,
            "task_id": task_id,
            "project_id": project_id,
            "task_name": task_name,
            "proposed_by_id": proposed_by_id,
            "status": "PENDING",
            "created_at": now_str
        }

    def approve_task_proposal(self, proposal_id: str, admin_id: str) -> dict:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_proposals WHERE proposal_id = ?", (proposal_id,))
            prop = cursor.fetchone()
            if not prop:
                raise ValueError(f"Proposal '{proposal_id}' not found.")

            task_id = prop["task_id"]
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            if cursor.fetchone():
                task_id = self.generate_next_task_id(prop["project_id"])

            cursor.execute("""
            INSERT OR IGNORE INTO tasks (task_id, project_id, name, is_hidden, proposed_by_id)
            VALUES (?, ?, ?, 0, ?)
            """, (task_id, prop["project_id"], prop["task_name"], prop["proposed_by_id"]))

            cursor.execute("""
            UPDATE task_proposals 
            SET status = 'APPROVED', admin_id = ?, decided_at = ?, task_id = ?
            WHERE proposal_id = ?
            """, (admin_id, now_str, task_id, proposal_id))
            conn.commit()
        return {
            "proposal_id": proposal_id,
            "task_id": task_id,
            "project_id": prop["project_id"],
            "task_name": prop["task_name"],
            "proposed_by_id": prop["proposed_by_id"],
            "status": "APPROVED",
            "admin_id": admin_id,
            "decided_at": now_str
        }

    def reject_task_proposal(self, proposal_id: str, admin_id: str, reason: str) -> dict:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE task_proposals 
            SET status = 'REJECTED', admin_id = ?, rejection_reason = ?, decided_at = ?
            WHERE proposal_id = ?
            """, (admin_id, reason, now_str, proposal_id))
            conn.commit()
        return {
            "proposal_id": proposal_id,
            "status": "REJECTED",
            "admin_id": admin_id,
            "rejection_reason": reason,
            "decided_at": now_str
        }

    def get_task_proposals(self, project_id: str = None, proposed_by_id: str = None, status: str = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT tp.*, p.name AS project_name, u.full_name AS proposer_name,
                   adm.full_name AS admin_name
            FROM task_proposals tp
            LEFT JOIN projects p ON tp.project_id = p.project_id
            LEFT JOIN users u ON tp.proposed_by_id = u.user_id
            LEFT JOIN users adm ON tp.admin_id = adm.user_id
            WHERE 1=1
            """
            params = []
            if project_id:
                query += " AND tp.project_id = ?"
                params.append(project_id)
            if proposed_by_id:
                query += " AND tp.proposed_by_id = ?"
                params.append(proposed_by_id)
            if status:
                query += " AND tp.status = ?"
                params.append(status)
            query += " ORDER BY tp.created_at DESC"
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]



class ClientQueueDBManager:
    """Manages the local SQLite database for offline queuing on Head workstations."""
    def __init__(self, queue_db_path: Path = CLIENT_QUEUE_DB_PATH):
        self.db_path = queue_db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS offline_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()

    def add_to_queue(self, event_type: str, payload_json: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO offline_queue (event_type, payload_json) VALUES (?, ?)",
                (event_type, payload_json)
            )
            conn.commit()

    def get_all_queued(self) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM offline_queue ORDER BY queue_id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_queued(self, queue_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM offline_queue WHERE queue_id = ?", (queue_id,))
            conn.commit()

    def clear_queue(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM offline_queue")
            conn.commit()
