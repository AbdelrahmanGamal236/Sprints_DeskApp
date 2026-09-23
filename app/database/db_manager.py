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
                    "INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?)",
                    ("superadmin", pwd_hash, pwd_salt, ROLE_SUPER_ADMIN, 0)
                )

            # Check default admin
            cursor.execute("SELECT * FROM users WHERE user_id = 'admin'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("admin")
                cursor.execute(
                    "INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?)",
                    ("admin", pwd_hash, pwd_salt, ROLE_ADMIN, 0)
                )

            # Check default coo
            cursor.execute("SELECT * FROM users WHERE user_id = 'coo'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("coo")
                cursor.execute(
                    "INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?)",
                    ("coo", pwd_hash, pwd_salt, ROLE_COO, 0)
                )

            # Check default sample employee (Head 1001)
            cursor.execute("SELECT * FROM users WHERE user_id = '1001'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("1001")
                cursor.execute(
                    "INSERT INTO users (user_id, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?)",
                    ("1001", pwd_hash, pwd_salt, ROLE_HEAD, 1)
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
