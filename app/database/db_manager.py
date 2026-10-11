import sqlite3
import hashlib
import secrets
import uuid
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
from app.core.config import (
    CENTRAL_DB_PATH, CLIENT_QUEUE_DB_PATH, BACKUPS_DIR, SEED_HEADS_PATH,
    ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN, ALL_ROLES,
    DEFAULT_DISCIPLINES
)
from app.core.auth import hash_password, verify_password, needs_rehash, generate_password

# Password policy for user-chosen passwords
PASSWORD_MIN_LENGTH = 8
# Accounts the old code seeded with password == user ID; rotated on first server start
LEGACY_DEFAULT_PRIVILEGED_IDS = ("superadmin", "admin", "coo")

logger = logging.getLogger(__name__)

class DBManager:
    verify_password = staticmethod(verify_password)

    def __init__(self, central_db_path: Path = CENTRAL_DB_PATH, standalone: bool = False):
        self.db_path = central_db_path
        self.standalone = standalone
        self.init_db(standalone=standalone)

    @contextmanager
    def get_connection(self):
        # timeout = busy wait (seconds) when another connection holds the write lock
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self, standalone: bool = False):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Disciplines table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS disciplines (
                discipline_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. Users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                full_name TEXT,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('HEAD', 'ADMIN', 'COO', 'SUPER_ADMIN')),
                must_change_password INTEGER DEFAULT 1,
                discipline_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(discipline_id) REFERENCES disciplines(discipline_id)
            );
            """)

            # Auto-Migration for users: full_name and discipline_id
            cursor.execute("PRAGMA table_info(users)")
            user_cols = [col["name"] for col in cursor.fetchall()]
            if "full_name" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            if "discipline_id" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN discipline_id TEXT")

            # 3. Projects table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 4. Tasks table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                is_hidden INTEGER DEFAULT 0,
                proposed_by_id TEXT,
                discipline_id TEXT,
                planned_start_date TEXT,
                planned_end_date TEXT,
                assigned_head_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(discipline_id) REFERENCES disciplines(discipline_id),
                FOREIGN KEY(assigned_head_id) REFERENCES users(user_id)
            );
            """)

            # Auto-Migration for tasks: proposed_by_id, discipline_id, planned dates, assigned_head_id
            cursor.execute("PRAGMA table_info(tasks)")
            task_cols = [col["name"] for col in cursor.fetchall()]
            if "proposed_by_id" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN proposed_by_id TEXT")
            if "discipline_id" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN discipline_id TEXT")
            if "planned_start_date" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN planned_start_date TEXT")
            if "planned_end_date" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN planned_end_date TEXT")
            if "assigned_head_id" not in task_cols:
                cursor.execute("ALTER TABLE tasks ADD COLUMN assigned_head_id TEXT")

            # 5. Employee Projects Assignment
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

            # 6. Progress Logs
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
                discipline_id TEXT,
                assigned_to TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status TEXT DEFAULT 'SYNCED',
                FOREIGN KEY(employee_id) REFERENCES users(user_id),
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id),
                FOREIGN KEY(discipline_id) REFERENCES disciplines(discipline_id)
            );
            """)

            # Auto-Migration for progress_logs
            cursor.execute("PRAGMA table_info(progress_logs)")
            log_cols = [col["name"] for col in cursor.fetchall()]
            if "entry_type" not in log_cols:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN entry_type TEXT DEFAULT 'NEW'")
            if "revision_number" not in log_cols:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN revision_number INTEGER DEFAULT 0")
            if "discipline_id" not in log_cols:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN discipline_id TEXT")
            if "assigned_to" not in log_cols:
                cursor.execute("ALTER TABLE progress_logs ADD COLUMN assigned_to TEXT")

            # 7. Priority Notifications
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

            # 8. Task Proposals
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_proposals (
                proposal_id TEXT PRIMARY KEY,
                task_id TEXT,
                project_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                proposed_by_id TEXT NOT NULL,
                discipline_id TEXT,
                planned_start_date TEXT,
                planned_end_date TEXT,
                status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
                admin_id TEXT,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decided_at TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(proposed_by_id) REFERENCES users(user_id)
            );
            """)

            cursor.execute("PRAGMA table_info(task_proposals)")
            prop_cols = [col["name"] for col in cursor.fetchall()]
            if "discipline_id" not in prop_cols:
                cursor.execute("ALTER TABLE task_proposals ADD COLUMN discipline_id TEXT")
            if "planned_start_date" not in prop_cols:
                cursor.execute("ALTER TABLE task_proposals ADD COLUMN planned_start_date TEXT")
            if "planned_end_date" not in prop_cols:
                cursor.execute("ALTER TABLE task_proposals ADD COLUMN planned_end_date TEXT")

            # 9. Task Date Change Requests
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_date_change_requests (
                request_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                requested_by_id TEXT NOT NULL,
                old_start_date TEXT,
                old_end_date TEXT,
                new_start_date TEXT,
                new_end_date TEXT,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
                admin_id TEXT,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decided_at TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id),
                FOREIGN KEY(requested_by_id) REFERENCES users(user_id)
            );
            """)

            # 10. Login sessions (only a SHA-256 of the token is stored)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """)

            conn.commit()

        # Seed initial data
        self.seed_disciplines()
        self.seed_defaults(standalone=standalone)
        self.seed_heads_from_file()
        # One-time credentials created at startup (Super Admin bootstrap / rotated legacy defaults)
        self.bootstrap_credentials = [] if standalone else self.bootstrap_privileged_accounts()

    def bootstrap_privileged_accounts(self) -> list[tuple[str, str]]:
        """
        Production bootstrap (replaces the old admin/admin, coo/coo, superadmin/superadmin seeds):
        - If no SUPER_ADMIN exists, create 'superadmin' with a random one-time password.
        - Legacy seeded accounts that still have password == user ID and were never used
          (must_change_password = 1) get a random one-time password instead.
        Returns [(user_id, one_time_password)] for the server to show on its console.
        Every returned account must change its password at first login.
        """
        issued = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS n FROM users WHERE role = ?", (ROLE_SUPER_ADMIN,))
            if cursor.fetchone()["n"] == 0:
                pwd = generate_password()
                pwd_hash, pwd_salt = hash_password(pwd)
                cursor.execute("SELECT 1 FROM users WHERE user_id = 'superadmin'")
                if cursor.fetchone():
                    cursor.execute("""UPDATE users SET role = ?, password_hash = ?, password_salt = ?,
                                      must_change_password = 1, discipline_id = NULL WHERE user_id = 'superadmin'""",
                                   (ROLE_SUPER_ADMIN, pwd_hash, pwd_salt))
                else:
                    cursor.execute("""INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password)
                                      VALUES ('superadmin', 'System Super Admin', ?, ?, ?, 1)""",
                                   (pwd_hash, pwd_salt, ROLE_SUPER_ADMIN))
                issued.append(("superadmin", pwd))

            placeholders = ",".join("?" * len(LEGACY_DEFAULT_PRIVILEGED_IDS))
            cursor.execute(f"""SELECT user_id, password_hash, password_salt FROM users
                               WHERE user_id IN ({placeholders}) AND role != 'HEAD' AND must_change_password = 1""",
                           LEGACY_DEFAULT_PRIVILEGED_IDS)
            for row in cursor.fetchall():
                if any(uid == row["user_id"] for uid, _ in issued):
                    continue
                if verify_password(row["user_id"], row["password_hash"], row["password_salt"]):
                    pwd = generate_password()
                    pwd_hash, pwd_salt = hash_password(pwd)
                    cursor.execute("UPDATE users SET password_hash = ?, password_salt = ? WHERE user_id = ?",
                                   (pwd_hash, pwd_salt, row["user_id"]))
                    issued.append((row["user_id"], pwd))
            conn.commit()
        return issued

    def seed_disciplines(self):
        """Idempotently seeds required disciplines."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for disc_id, name in DEFAULT_DISCIPLINES:
                cursor.execute("""
                INSERT OR IGNORE INTO disciplines (discipline_id, name, is_hidden)
                VALUES (?, ?, 0)
                """, (disc_id, name))
            conn.commit()

    def seed_defaults(self, standalone: bool = False):
        """Demo data for --standalone single-PC testing only (lives in a separate data_demo folder)."""
        if not standalone:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for uid, name, role in (("superadmin", "System Super Admin", ROLE_SUPER_ADMIN),
                                    ("admin", "Admin Manager", ROLE_ADMIN),
                                    ("coo", "Chief Operating Officer", ROLE_COO)):
                cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,))
                if not cursor.fetchone():
                    pwd_hash, pwd_salt = hash_password(uid)
                    cursor.execute(
                        "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password) VALUES (?, ?, ?, ?, ?, 1)",
                        (uid, name, pwd_hash, pwd_salt, role)
                    )

            # Demo Head 1001 and sample projects
            cursor.execute("SELECT * FROM users WHERE user_id = '1001'")
            if not cursor.fetchone():
                pwd_hash, pwd_salt = hash_password("1001")
                cursor.execute(
                    "INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password, discipline_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("1001", "Eng. Abdelrahman", pwd_hash, pwd_salt, ROLE_HEAD, 1, "AI")
                )

            # Sample projects if empty
            cursor.execute("SELECT * FROM projects")
            if not cursor.fetchall():
                p1_id = "PRJ-01"
                p2_id = "PRJ-02"
                cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                               (p1_id, "Project Alpha", "Main Core System Development"))
                cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                               (p2_id, "Project Beta", "Hardware LAN Setup & Wiring"))

                today_str = datetime.now().strftime("%Y-%m-%d")
                cursor.execute("""
                INSERT INTO tasks (task_id, project_id, name, description, discipline_id, planned_start_date, planned_end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("TSK-01", p1_id, "Database Schema & Migration", "Design SQLite schema", "STR", today_str, today_str))
                cursor.execute("""
                INSERT INTO tasks (task_id, project_id, name, description, discipline_id, planned_start_date, planned_end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("TSK-02", p1_id, "PySide6 GUI Layout", "Build Head workspace", "AI", today_str, today_str))
                cursor.execute("""
                INSERT INTO tasks (task_id, project_id, name, description, discipline_id, planned_start_date, planned_end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("TSK-03", p2_id, "Router & Switch Config", "Configure local LAN TCP/IP", "ELE", today_str, today_str))

                cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)", ("1001", p1_id))
                cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)", ("1001", p2_id))

            conn.commit()

    def seed_heads_from_file(self, json_path: Path = SEED_HEADS_PATH):
        """
        Seeds initial Heads from data/seed_heads.json.
        Skips any entry with placeholder, empty, or duplicate user_id. Never crashes.
        """
        if not json_path.exists():
            logger.info("seed_heads.json not found, skipping file head seed.")
            return

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                heads_list = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load seed_heads.json: {e}")
            return

        seen_ids = set()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for entry in heads_list:
                user_id = str(entry.get("user_id", "")).strip()
                full_name = str(entry.get("full_name", "")).strip()
                discipline_id = str(entry.get("discipline_id", "")).strip()

                # Skip placeholder, empty, or invalid user_id
                if not user_id or "<" in user_id or ">" in user_id or user_id.upper() == "FINGERPRINT_ID":
                    logger.warning(f"Skipping placeholder/invalid seed head: user_id='{user_id}', name='{full_name}'")
                    continue

                if user_id in seen_ids:
                    logger.warning(f"Skipping duplicate user_id in seed_heads.json: '{user_id}'")
                    continue
                seen_ids.add(user_id)

                # Check if user already exists in DB (idempotent, never overwrite)
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                if cursor.fetchone():
                    logger.info(f"Seed head '{user_id}' already exists in database; skipping overwrite.")
                    continue

                pwd_hash, pwd_salt = hash_password(user_id)
                cursor.execute("""
                INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password, discipline_id)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """, (user_id, full_name, pwd_hash, pwd_salt, ROLE_HEAD, discipline_id))

                # Auto-assign to all active projects
                cursor.execute("SELECT project_id FROM projects WHERE is_hidden = 0")
                projects = cursor.fetchall()
                for prj in projects:
                    cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)",
                                   (user_id, prj["project_id"]))

                logger.info(f"Successfully seeded Head: '{user_id}' ({full_name}) - Discipline: '{discipline_id}'")

            conn.commit()

    def backup_database(self, max_copies: int = 30):
        """Automatic daily backup of central_app.db using SQLite's backup API, keeping last 30 copies."""
        try:
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
            today_str = datetime.now().strftime("%Y%m%d")
            backup_file = BACKUPS_DIR / f"central_app_{today_str}.db"

            with self.get_connection() as src_conn:
                dest_conn = sqlite3.connect(backup_file)
                src_conn.backup(dest_conn)
                dest_conn.close()

            # Prune older backups
            backups = sorted(BACKUPS_DIR.glob("central_app_*.db"))
            if len(backups) > max_copies:
                for old in backups[:-max_copies]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            logger.info(f"Daily SQLite backup completed: {backup_file}")
            return str(backup_file)
        except Exception as e:
            logger.error(f"Failed to backup central database: {e}")
            return None

    # ------------------- DISCIPLINES API -------------------
    def get_disciplines(self, include_hidden: bool = False) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if include_hidden:
                cursor.execute("SELECT * FROM disciplines ORDER BY rowid ASC")
            else:
                cursor.execute("SELECT * FROM disciplines WHERE is_hidden = 0 ORDER BY rowid ASC")
            return [dict(r) for r in cursor.fetchall()]

    def add_discipline(self, discipline_id: str, name: str) -> dict:
        discipline_id = discipline_id.strip()
        name = name.strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM disciplines WHERE discipline_id = ?", (discipline_id,))
            if cursor.fetchone():
                raise ValueError(f"Discipline ID '{discipline_id}' already exists.")
            cursor.execute("INSERT INTO disciplines (discipline_id, name, is_hidden) VALUES (?, ?, 0)",
                           (discipline_id, name))
            conn.commit()
        return {"discipline_id": discipline_id, "name": name, "is_hidden": 0}

    def update_discipline(self, discipline_id: str, name: str, is_hidden: int = None) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if is_hidden is not None:
                cursor.execute("UPDATE disciplines SET name = ?, is_hidden = ? WHERE discipline_id = ?",
                               (name.strip(), is_hidden, discipline_id))
            else:
                cursor.execute("UPDATE disciplines SET name = ? WHERE discipline_id = ?",
                               (name.strip(), discipline_id))
            conn.commit()
        return {"discipline_id": discipline_id, "name": name, "is_hidden": is_hidden}

    def toggle_hide_discipline(self, discipline_id: str, current_hidden: int) -> dict:
        new_hidden = 0 if current_hidden else 1
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE disciplines SET is_hidden = ? WHERE discipline_id = ?",
                           (new_hidden, discipline_id))
            conn.commit()
        return {"discipline_id": discipline_id, "is_hidden": new_hidden}

    # ------------------- USERS & AUTH API -------------------
    def get_user(self, user_id: str) -> dict | None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT u.*, d.name AS discipline_name
            FROM users u
            LEFT JOIN disciplines d ON u.discipline_id = d.discipline_id
            WHERE u.user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_users(self, role: str = None, discipline_id: str = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT u.user_id, u.full_name, u.role, u.must_change_password,
                   u.discipline_id, d.name AS discipline_name, u.created_at
            FROM users u
            LEFT JOIN disciplines d ON u.discipline_id = d.discipline_id
            WHERE 1=1
            """
            params = []
            if role:
                query += " AND u.role = ?"
                params.append(role)
            if discipline_id:
                query += " AND u.discipline_id = ?"
                params.append(discipline_id)
            query += " ORDER BY u.created_at ASC"
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    def create_user(self, actor_role: str, user_id: str, full_name: str, role: str, discipline_id: str = None) -> dict:
        # Fail closed: only ADMIN (HEAD accounts) and SUPER_ADMIN (any role) may create users.
        if actor_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            raise PermissionError("You are not allowed to create user accounts.")
        if role not in ALL_ROLES:
            raise ValueError(f"Unknown role '{role}'.")
        if actor_role == ROLE_ADMIN and role != ROLE_HEAD:
            raise PermissionError("Admin can only create and manage HEAD accounts.")
        if role == ROLE_HEAD and not discipline_id:
            raise ValueError("Discipline is required for HEAD accounts.")

        user_id = (user_id or "").strip()
        full_name = (full_name or "").strip()
        if not user_id or not full_name:
            raise ValueError("User ID and Full Name are required.")
        if role != ROLE_HEAD:
            discipline_id = None
        pwd_hash, pwd_salt = hash_password(user_id) # initial password = user_id

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                raise ValueError(f"User ID '{user_id}' already exists.")

            cursor.execute("""
            INSERT INTO users (user_id, full_name, password_hash, password_salt, role, must_change_password, discipline_id)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (user_id, full_name, pwd_hash, pwd_salt, role, discipline_id))

            # Auto-assign Head to all active projects
            if role == ROLE_HEAD:
                cursor.execute("SELECT project_id FROM projects WHERE is_hidden = 0")
                projects = cursor.fetchall()
                for prj in projects:
                    cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)",
                                   (user_id, prj["project_id"]))

            conn.commit()

        return {"user_id": user_id, "full_name": full_name, "role": role, "discipline_id": discipline_id}

    def update_user(self, actor_role: str, user_id: str, full_name: str = None, discipline_id: str = None, role: str = None) -> dict:
        target = self.get_user(user_id)
        if not target:
            raise ValueError(f"User '{user_id}' not found.")

        if actor_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            raise PermissionError("You are not allowed to manage user accounts.")
        if actor_role == ROLE_ADMIN and target["role"] != ROLE_HEAD:
            raise PermissionError("Admin can only manage HEAD accounts.")
        if role is not None and role not in ALL_ROLES:
            raise ValueError(f"Unknown role '{role}'.")

        new_full_name = full_name.strip() if full_name is not None else target["full_name"]
        new_discipline_id = discipline_id if discipline_id is not None else target["discipline_id"]
        new_role = role if role is not None else target["role"]

        if actor_role == ROLE_ADMIN and new_role != ROLE_HEAD:
            raise PermissionError("Admin cannot promote accounts to Admin or COO.")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users SET full_name = ?, discipline_id = ?, role = ? WHERE user_id = ?
            """, (new_full_name, new_discipline_id, new_role, user_id))
            conn.commit()

        return {"user_id": user_id, "full_name": new_full_name, "discipline_id": new_discipline_id, "role": new_role}

    def reset_user_password(self, actor_role: str, user_id: str) -> dict:
        target = self.get_user(user_id)
        if not target:
            raise ValueError(f"User '{user_id}' not found.")
        if actor_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            raise PermissionError("You are not allowed to reset passwords.")
        if actor_role == ROLE_ADMIN and target["role"] != ROLE_HEAD:
            raise PermissionError("Admin can only reset passwords for HEAD accounts.")

        pwd_hash, pwd_salt = hash_password(user_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 1 WHERE user_id = ?
            """, (pwd_hash, pwd_salt, user_id))
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
        return {"user_id": user_id, "status": "RESET_SUCCESS"}

    def change_password(self, user_id: str, new_password: str, old_password: str = None, require_old: bool = True) -> bool:
        """
        Changes a user's password. The caller (server) decides whether the old password is
        required; it is only waived for the forced first-login change on an authenticated session.
        """
        user = self.get_user(user_id)
        if not user:
            raise ValueError(f"User '{user_id}' not found.")

        if require_old:
            if not old_password or not verify_password(old_password, user["password_hash"], user["password_salt"]):
                raise ValueError("Incorrect current password.")

        new_password = new_password or ""
        if len(new_password) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"New password must be at least {PASSWORD_MIN_LENGTH} characters.")
        if new_password == user_id:
            raise ValueError("New password cannot be the same as your User ID.")
        if verify_password(new_password, user["password_hash"], user["password_salt"]):
            raise ValueError("New password must be different from the current password.")

        pwd_hash, pwd_salt = hash_password(new_password)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 0 WHERE user_id = ?
            """, (pwd_hash, pwd_salt, user_id))
            conn.commit()
        return True

    # ------------------- SESSIONS -------------------
    SESSION_LIFETIME = timedelta(days=7)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        with self.get_connection() as conn:
            conn.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now.isoformat(),))
            conn.execute("INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (self._token_hash(token), user_id, now.isoformat(), (now + self.SESSION_LIFETIME).isoformat()))
            conn.commit()
        return token

    def resolve_session(self, token: str) -> dict | None:
        """Returns the user for a valid, unexpired session token and extends its lifetime."""
        if not token:
            return None
        now = datetime.now()
        with self.get_connection() as conn:
            row = conn.execute("SELECT user_id, expires_at FROM user_sessions WHERE token_hash = ?",
                               (self._token_hash(token),)).fetchone()
            if not row or row["expires_at"] < now.isoformat():
                return None
            conn.execute("UPDATE user_sessions SET expires_at = ? WHERE token_hash = ?",
                         ((now + self.SESSION_LIFETIME).isoformat(), self._token_hash(token)))
            conn.commit()
        return self.get_user(row["user_id"])

    def delete_session(self, token: str):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (self._token_hash(token or ""),))
            conn.commit()

    def delete_user_sessions(self, user_id: str, keep_token: str = None):
        with self.get_connection() as conn:
            if keep_token:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ? AND token_hash != ?",
                             (user_id, self._token_hash(keep_token)))
            else:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()

    def authenticate(self, user_id: str, password: str) -> dict | None:
        """Returns the user row when the credentials are valid; upgrades legacy hashes in place."""
        user = self.get_user((user_id or "").strip())
        if not user or not verify_password(password or "", user["password_hash"], user["password_salt"]):
            return None
        if needs_rehash(user["password_hash"]):
            pwd_hash, pwd_salt = hash_password(password)
            with self.get_connection() as conn:
                conn.execute("UPDATE users SET password_hash = ?, password_salt = ? WHERE user_id = ?",
                             (pwd_hash, pwd_salt, user["user_id"]))
                conn.commit()
        return user

    # ------------------- PROJECTS API -------------------
    def get_projects(self, include_hidden: bool = False) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if include_hidden:
                cursor.execute("SELECT * FROM projects ORDER BY project_id ASC")
            else:
                cursor.execute("SELECT * FROM projects WHERE is_hidden = 0 ORDER BY project_id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def add_project(self, project_id: str, name: str, description: str = "") -> dict:
        project_id = project_id.strip()
        name = name.strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
            if cursor.fetchone():
                raise ValueError(f"Project ID '{project_id}' already exists.")
            cursor.execute("INSERT INTO projects (project_id, name, description) VALUES (?, ?, ?)",
                           (project_id, name, description))
            
            # Auto-assign all active HEADs to project
            cursor.execute("SELECT user_id FROM users WHERE role = 'HEAD'")
            for h in cursor.fetchall():
                cursor.execute("INSERT OR IGNORE INTO employee_projects (employee_id, project_id) VALUES (?, ?)",
                               (h["user_id"], project_id))
            conn.commit()
        return {"project_id": project_id, "name": name, "description": description}

    def toggle_hide_project(self, project_id: str, current_hidden: int) -> dict:
        new_hidden = 0 if current_hidden else 1
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE projects SET is_hidden = ? WHERE project_id = ?", (new_hidden, project_id))
            conn.commit()
        return {"project_id": project_id, "is_hidden": new_hidden}

    # ------------------- TASKS API -------------------
    def get_tasks(self, project_id: str = None, discipline_id: str = None, assigned_head_id: str = None, include_hidden: bool = False) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT t.*, p.name AS project_name, u.full_name AS proposer_name,
                   d.name AS discipline_name,
                   uh.full_name AS assigned_head_name
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.project_id
            LEFT JOIN users u ON t.proposed_by_id = u.user_id
            LEFT JOIN disciplines d ON t.discipline_id = d.discipline_id
            LEFT JOIN users uh ON t.assigned_head_id = uh.user_id
            WHERE 1=1
            """
            params = []
            if not include_hidden:
                query += " AND t.is_hidden = 0"
            if project_id:
                query += " AND t.project_id = ?"
                params.append(project_id)
            if discipline_id:
                query += " AND t.discipline_id = ?"
                params.append(discipline_id)
            if assigned_head_id:
                query += " AND (t.assigned_head_id IS NULL OR t.assigned_head_id = ?)"
                params.append(assigned_head_id)
            query += " ORDER BY t.task_id ASC"
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    def add_task(self, project_id: str, task_id: str = None, name: str = "", discipline_id: str = None,
                 planned_start_date: str = "", planned_end_date: str = "", description: str = "",
                 proposed_by_id: str = None, assigned_head_id: str = None) -> dict:
        project_id = (project_id or "").strip()
        task_id = (task_id or "").strip()
        name = (name or "").strip()
        discipline_id = discipline_id.strip() if discipline_id else None
        assigned_head_id = assigned_head_id.strip() if assigned_head_id else None

        if not discipline_id:
            raise ValueError("Discipline is required when creating a task.")

        today_str = datetime.now().strftime("%Y-%m-%d")
        if not planned_start_date:
            planned_start_date = today_str
        if not planned_end_date:
            from datetime import timedelta
            planned_end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

        # If task_id is omitted or starts with MSG- (correlation ID artifact), auto-generate clean task_id
        if not task_id or task_id.lower() in ("none", "null", "undefined") or task_id.startswith("MSG-"):
            task_id = self.generate_next_task_id(project_id)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Prevent any duplicate task_id collision by auto-incrementing if ID exists
            while True:
                cursor.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,))
                if not cursor.fetchone():
                    break
                try:
                    num_part = int(task_id.split("-")[1])
                    task_id = f"TSK-{num_part + 1:02d}"
                except Exception:
                    task_id = self.generate_next_task_id(project_id)

            cursor.execute("""
            INSERT INTO tasks (
                task_id, project_id, name, description, is_hidden,
                proposed_by_id, discipline_id, planned_start_date,
                planned_end_date, assigned_head_id
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """, (task_id, project_id, name, description, proposed_by_id,
                  discipline_id, planned_start_date, planned_end_date, assigned_head_id))

            # Ensure assigned head has access to the project
            if assigned_head_id and project_id:
                cursor.execute("""
                INSERT OR IGNORE INTO employee_projects (employee_id, project_id)
                VALUES (?, ?)
                """, (assigned_head_id, project_id))

            conn.commit()

        return {
            "task_id": task_id, "project_id": project_id, "name": name,
            "discipline_id": discipline_id, "planned_start_date": planned_start_date,
            "planned_end_date": planned_end_date, "proposed_by_id": proposed_by_id,
            "assigned_head_id": assigned_head_id
        }

    def update_task(self, task_id: str, name: str = None, discipline_id: str = None,
                    assigned_head_id = ..., planned_start_date: str = None,
                    planned_end_date: str = None, description: str = None) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Task '{task_id}' not found.")

            new_name = name.strip() if name is not None else current["name"]
            new_disc = discipline_id.strip() if discipline_id is not None else current["discipline_id"]
            if assigned_head_id is not ...:
                new_head = assigned_head_id.strip() if (assigned_head_id and str(assigned_head_id).strip()) else None
            else:
                new_head = current["assigned_head_id"]
            new_start = planned_start_date if planned_start_date is not None else current["planned_start_date"]
            new_end = planned_end_date if planned_end_date is not None else current["planned_end_date"]
            new_desc = description if description is not None else current["description"]

            cursor.execute("""
            UPDATE tasks
            SET name = ?, discipline_id = ?, assigned_head_id = ?,
                planned_start_date = ?, planned_end_date = ?, description = ?
            WHERE task_id = ?
            """, (new_name, new_disc, new_head, new_start, new_end, new_desc, task_id))
            conn.commit()

        return {
            "task_id": task_id, "name": new_name, "discipline_id": new_disc,
            "assigned_head_id": new_head, "planned_start_date": new_start,
            "planned_end_date": new_end
        }

    def update_task_dates(self, task_id: str, planned_start_date: str, planned_end_date: str) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE tasks SET planned_start_date = ?, planned_end_date = ? WHERE task_id = ?
            """, (planned_start_date, planned_end_date, task_id))
            conn.commit()
        return {"task_id": task_id, "planned_start_date": planned_start_date, "planned_end_date": planned_end_date}

    def toggle_hide_task(self, task_id: str, current_hidden: int) -> dict:
        new_hidden = 0 if current_hidden else 1
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET is_hidden = ? WHERE task_id = ?", (new_hidden, task_id))
            conn.commit()
        return {"task_id": task_id, "is_hidden": new_hidden}

    def generate_next_task_id(self, project_id: str = None) -> str:
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

    # ------------------- TASK PROPOSALS API -------------------
    def create_task_proposal(self, project_id: str, task_name: str, proposed_by_id: str,
                             discipline_id: str = None, planned_start_date: str = None,
                             planned_end_date: str = None, proposal_id: str = None) -> dict:
        if not proposal_id:
            proposal_id = f"PROP-{uuid.uuid4().hex[:8].upper()}"
        task_id = self.generate_next_task_id(project_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # If discipline_id not passed, fetch from proposer user
        if not discipline_id:
            u = self.get_user(proposed_by_id)
            if u:
                discipline_id = u["discipline_id"]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Idempotency check
            cursor.execute("SELECT * FROM task_proposals WHERE proposal_id = ?", (proposal_id,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            cursor.execute("""
            INSERT INTO task_proposals (proposal_id, task_id, project_id, task_name, proposed_by_id, discipline_id, planned_start_date, planned_end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (proposal_id, task_id, project_id, task_name, proposed_by_id, discipline_id, planned_start_date, planned_end_date, now_str))
            conn.commit()

        return {
            "proposal_id": proposal_id, "task_id": task_id, "project_id": project_id,
            "task_name": task_name, "proposed_by_id": proposed_by_id, "discipline_id": discipline_id,
            "planned_start_date": planned_start_date, "planned_end_date": planned_end_date,
            "status": "PENDING", "created_at": now_str
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

            today_str = datetime.now().strftime("%Y-%m-%d")
            p_start = prop["planned_start_date"] or today_str
            p_end = prop["planned_end_date"] or today_str

            cursor.execute("""
            INSERT OR IGNORE INTO tasks (task_id, project_id, name, is_hidden, proposed_by_id, discipline_id, planned_start_date, planned_end_date)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?)
            """, (task_id, prop["project_id"], prop["task_name"], prop["proposed_by_id"], prop["discipline_id"], p_start, p_end))

            cursor.execute("""
            UPDATE task_proposals 
            SET status = 'APPROVED', admin_id = ?, decided_at = ?, task_id = ?
            WHERE proposal_id = ?
            """, (admin_id, now_str, task_id, proposal_id))
            conn.commit()

        return {
            "proposal_id": proposal_id, "task_id": task_id, "project_id": prop["project_id"],
            "task_name": prop["task_name"], "proposed_by_id": prop["proposed_by_id"],
            "discipline_id": prop["discipline_id"], "status": "APPROVED",
            "admin_id": admin_id, "decided_at": now_str
        }

    def reject_task_proposal(self, proposal_id: str, admin_id: str, reason: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is mandatory.")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE task_proposals 
            SET status = 'REJECTED', admin_id = ?, rejection_reason = ?, decided_at = ?
            WHERE proposal_id = ?
            """, (admin_id, reason.strip(), now_str, proposal_id))
            conn.commit()

        return {
            "proposal_id": proposal_id, "status": "REJECTED", "admin_id": admin_id,
            "rejection_reason": reason.strip(), "decided_at": now_str
        }

    def get_task_proposals(self, project_id: str = None, proposed_by_id: str = None, status: str = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT tp.*, p.name AS project_name, u.full_name AS proposer_name,
                   adm.full_name AS admin_name, d.name AS discipline_name
            FROM task_proposals tp
            LEFT JOIN projects p ON tp.project_id = p.project_id
            LEFT JOIN users u ON tp.proposed_by_id = u.user_id
            LEFT JOIN users adm ON tp.admin_id = adm.user_id
            LEFT JOIN disciplines d ON tp.discipline_id = d.discipline_id
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

    # ------------------- TASK DATE CHANGE REQUESTS API -------------------
    def create_task_date_change_request(self, task_id: str, requested_by_id: str,
                                        new_start_date: str, new_end_date: str,
                                        reason: str, request_id: str = None) -> dict:
        if not reason or not reason.strip():
            raise ValueError("Reason for date change is mandatory.")
        if not request_id:
            request_id = f"DCR-{uuid.uuid4().hex[:8].upper()}"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Idempotency check
            cursor.execute("SELECT * FROM task_date_change_requests WHERE request_id = ?", (request_id,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            cursor.execute("SELECT planned_start_date, planned_end_date FROM tasks WHERE task_id = ?", (task_id,))
            task_row = cursor.fetchone()
            old_start = task_row["planned_start_date"] if task_row else None
            old_end = task_row["planned_end_date"] if task_row else None

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT INTO task_date_change_requests (
                request_id, task_id, requested_by_id, old_start_date, old_end_date,
                new_start_date, new_end_date, reason, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (request_id, task_id, requested_by_id, old_start, old_end, new_start_date, new_end_date, reason.strip(), now_str))
            conn.commit()

        return {
            "request_id": request_id, "task_id": task_id, "requested_by_id": requested_by_id,
            "old_start_date": old_start, "old_end_date": old_end,
            "new_start_date": new_start_date, "new_end_date": new_end_date,
            "reason": reason.strip(), "status": "PENDING", "created_at": now_str
        }

    def approve_task_date_change_request(self, request_id: str, admin_id: str) -> dict:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_date_change_requests WHERE request_id = ?", (request_id,))
            req = cursor.fetchone()
            if not req:
                raise ValueError(f"Date change request '{request_id}' not found.")

            # Update task dates
            cursor.execute("""
            UPDATE tasks SET planned_start_date = ?, planned_end_date = ? WHERE task_id = ?
            """, (req["new_start_date"], req["new_end_date"], req["task_id"]))

            # Update request status
            cursor.execute("""
            UPDATE task_date_change_requests
            SET status = 'APPROVED', admin_id = ?, decided_at = ?
            WHERE request_id = ?
            """, (admin_id, now_str, request_id))
            conn.commit()

        return {
            "request_id": request_id, "task_id": req["task_id"], "status": "APPROVED",
            "admin_id": admin_id, "new_start_date": req["new_start_date"],
            "new_end_date": req["new_end_date"], "decided_at": now_str
        }

    def reject_task_date_change_request(self, request_id: str, admin_id: str, reason: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is mandatory.")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE task_date_change_requests
            SET status = 'REJECTED', admin_id = ?, rejection_reason = ?, decided_at = ?
            WHERE request_id = ?
            """, (admin_id, reason.strip(), now_str, request_id))
            conn.commit()

        return {
            "request_id": request_id, "status": "REJECTED", "admin_id": admin_id,
            "rejection_reason": reason.strip(), "decided_at": now_str
        }

    def get_task_date_change_requests(self, status: str = None, task_id: str = None, requested_by_id: str = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT dcr.*, t.name AS task_name, p.name AS project_name, p.project_id,
                   u.full_name AS requester_name, adm.full_name AS admin_name,
                   t.discipline_id, disc.name AS discipline_name
            FROM task_date_change_requests dcr
            LEFT JOIN tasks t ON dcr.task_id = t.task_id
            LEFT JOIN projects p ON t.project_id = p.project_id
            LEFT JOIN users u ON dcr.requested_by_id = u.user_id
            LEFT JOIN users adm ON dcr.admin_id = adm.user_id
            LEFT JOIN disciplines disc ON t.discipline_id = disc.discipline_id
            WHERE 1=1
            """
            params = []
            if status:
                query += " AND dcr.status = ?"
                params.append(status)
            if task_id:
                query += " AND dcr.task_id = ?"
                params.append(task_id)
            if requested_by_id:
                query += " AND dcr.requested_by_id = ?"
                params.append(requested_by_id)
            query += " ORDER BY dcr.created_at DESC"
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # ------------------- PROGRESS LOGS API -------------------
    def get_next_revision_number(self, employee_id: str, project_id: str, task_id: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_rev
            FROM progress_logs
            WHERE employee_id = ? AND project_id = ? AND task_id = ? AND entry_type = 'REVISION'
            """, (employee_id, project_id, task_id))
            row = cursor.fetchone()
            return row["next_rev"] if row else 1

    def submit_progress_log(self, payload: dict) -> dict:
        log_id = payload.get("log_id") or f"LOG-{uuid.uuid4().hex[:8].upper()}"
        employee_id = payload.get("employee_id")
        project_id = payload.get("project_id")
        task_id = payload.get("task_id")
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        progress_percentage = int(payload.get("progress_percentage", 0))
        progress_stage = payload.get("progress_stage", "")
        entry_type = payload.get("entry_type", "NEW")
        revision_number = int(payload.get("revision_number", 0))
        notes = payload.get("notes", "")
        assigned_to = (payload.get("assigned_to") or "").strip()[:100]

        # Verify discipline rules if employee is HEAD
        emp = self.get_user(employee_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT discipline_id, assigned_head_id FROM tasks WHERE task_id = ?", (task_id,))
            task_row = cursor.fetchone()
            task_discipline = task_row["discipline_id"] if task_row else None
            task_assigned_head = task_row["assigned_head_id"] if task_row else None

            if emp and emp["role"] == ROLE_HEAD:
                head_discipline = emp["discipline_id"]
                if not head_discipline:
                    raise PermissionError(f"Employee '{employee_id}' has no assigned discipline.")
                if task_discipline and task_discipline != head_discipline:
                    raise PermissionError(f"Discipline mismatch: Head belongs to '{head_discipline}' but task belongs to '{task_discipline}'.")
                if task_assigned_head and task_assigned_head != employee_id:
                    raise PermissionError(f"Task '{task_id}' is specifically assigned to Head '{task_assigned_head}'.")

            # Store employee's active discipline (or task's discipline)
            log_discipline = (emp["discipline_id"] if emp and emp.get("discipline_id") else task_discipline)

            # Idempotent write: ignore if log_id already exists
            cursor.execute("SELECT * FROM progress_logs WHERE log_id = ?", (log_id,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            cursor.execute("""
            INSERT INTO progress_logs (
                log_id, employee_id, project_id, task_id, start_date, end_date,
                progress_percentage, progress_stage, entry_type, revision_number,
                notes, discipline_id, assigned_to, submitted_at, sync_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'SYNCED')
            """, (log_id, employee_id, project_id, task_id, start_date, end_date,
                  progress_percentage, progress_stage, entry_type, revision_number,
                  notes, log_discipline, assigned_to))
            conn.commit()

        return {
            "log_id": log_id, "employee_id": employee_id, "project_id": project_id,
            "task_id": task_id, "start_date": start_date, "end_date": end_date,
            "progress_percentage": progress_percentage, "progress_stage": progress_stage,
            "entry_type": entry_type, "revision_number": revision_number,
            "notes": notes, "discipline_id": log_discipline, "assigned_to": assigned_to,
            "submitted_at": datetime.now().isoformat()
        }

    def get_progress_logs(self, project_id: str = None, discipline_id: str = None,
                          employee_id: str = None, start_date: str = None,
                          end_date: str = None, limit: int = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT l.*, p.name AS project_name, p.is_hidden AS project_hidden,
                   t.name AS task_name, t.is_hidden AS task_hidden,
                   t.discipline_id AS task_discipline_id,
                   dt.name AS task_discipline_name,
                   dh.name AS head_discipline_name,
                   u.full_name AS employee_name
            FROM progress_logs l
            LEFT JOIN projects p ON l.project_id = p.project_id
            LEFT JOIN tasks t ON l.task_id = t.task_id
            LEFT JOIN disciplines dt ON t.discipline_id = dt.discipline_id
            LEFT JOIN disciplines dh ON l.discipline_id = dh.discipline_id
            LEFT JOIN users u ON l.employee_id = u.user_id
            WHERE 1=1
            """
            params = []
            if project_id:
                query += " AND l.project_id = ?"
                params.append(project_id)
            if discipline_id:
                query += " AND (t.discipline_id = ? OR l.discipline_id = ?)"
                params.append(discipline_id)
                params.append(discipline_id)
            if employee_id:
                query += " AND l.employee_id = ?"
                params.append(employee_id)
            if start_date:
                query += " AND l.start_date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND l.end_date <= ?"
                params.append(end_date)

            query += " ORDER BY l.submitted_at DESC"
            if limit:
                query += " LIMIT ?"
                params.append(int(limit))
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # ------------------- PRIORITY NOTIFICATIONS API -------------------
    def create_priority_notification(self, coo_id: str, target_employee_id: str, message: str,
                                     notification_id: str = None) -> dict:
        message = (message or "").strip()
        if not message:
            raise ValueError("Alert message is required.")
        target = self.get_user(target_employee_id)
        if not target or target["role"] != ROLE_HEAD:
            raise ValueError(f"Target '{target_employee_id}' is not a Head account.")
        notif_id = notification_id or f"NOTIF-{uuid.uuid4().hex.upper()}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM priority_notifications WHERE notification_id = ?", (notif_id,))
            existing = cursor.fetchone()
            if existing:  # idempotent resend
                return dict(existing)
            cursor.execute("""
            INSERT INTO priority_notifications (notification_id, coo_id, target_employee_id, message, status, created_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            """, (notif_id, coo_id, target_employee_id, message, now_str))
            conn.commit()
        return {
            "notification_id": notif_id, "coo_id": coo_id,
            "target_employee_id": target_employee_id, "message": message,
            "status": "PENDING", "created_at": now_str
        }

    def respond_priority_notification(self, notification_id: str, employee_id: str, response_status: str) -> dict:
        if response_status not in ("ACCEPTED", "DENIED"):
            raise ValueError("Response must be ACCEPTED or DENIED.")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM priority_notifications WHERE notification_id = ?", (notification_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Alert '{notification_id}' not found.")
            if row["target_employee_id"] != employee_id:
                raise PermissionError("This alert was sent to a different Head.")
            if row["status"] != "PENDING":
                if row["status"] == response_status:  # idempotent resend from the offline queue
                    return dict(row)
                raise ValueError(f"Alert was already answered ({row['status']}).")
            cursor.execute("""
            UPDATE priority_notifications SET status = ?, responded_at = ? WHERE notification_id = ?
            """, (response_status, now_str, notification_id))
            conn.commit()
            result = dict(row)
        result.update({"status": response_status, "responded_at": now_str})
        return result

    def get_priority_notifications(self, employee_id: str = None, status: str = None, limit: int = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """SELECT n.*, u.full_name AS target_name FROM priority_notifications n
                       LEFT JOIN users u ON n.target_employee_id = u.user_id WHERE 1=1"""
            params = []
            if employee_id:
                query += " AND n.target_employee_id = ?"
                params.append(employee_id)
            if status:
                query += " AND n.status = ?"
                params.append(status)
            query += " ORDER BY n.created_at DESC"
            if limit:
                query += " LIMIT ?"
                params.append(int(limit))
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    # ------------------- ANALYTICS API -------------------
    def get_analytics_data(self) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM progress_logs")
            total_logs = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) AS count FROM progress_logs WHERE entry_type = 'REVISION'")
            total_revisions = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) AS count FROM projects WHERE is_hidden = 0")
            active_projects = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'HEAD'")
            active_employees = cursor.fetchone()["count"]

            cursor.execute("""
            SELECT u.user_id, u.full_name, u.discipline_id, d.name AS discipline_name,
                   COUNT(l.log_id) AS total_logs,
                   SUM(CASE WHEN l.entry_type = 'NEW' THEN 1 ELSE 0 END) AS new_logs,
                   SUM(CASE WHEN l.entry_type = 'CONTINUATION' THEN 1 ELSE 0 END) AS cont_logs,
                   SUM(CASE WHEN l.entry_type = 'REVISION' THEN 1 ELSE 0 END) AS rev_logs
            FROM users u
            LEFT JOIN progress_logs l ON u.user_id = l.employee_id
            LEFT JOIN disciplines d ON u.discipline_id = d.discipline_id
            WHERE u.role = 'HEAD'
            GROUP BY u.user_id, u.full_name
            ORDER BY rev_logs DESC, total_logs DESC
            """)
            emp_stats = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
            SELECT p.project_id, p.name AS project_name,
                   COUNT(DISTINCT t.task_id) AS total_tasks,
                   SUM(CASE WHEN l.entry_type = 'REVISION' THEN 1 ELSE 0 END) AS total_revisions,
                   SUM(CASE WHEN l.progress_stage = 'Done' THEN 1 ELSE 0 END) AS done_count,
                   SUM(CASE WHEN l.progress_stage = 'In Progress' THEN 1 ELSE 0 END) AS in_prog_count,
                   SUM(CASE WHEN l.progress_stage = 'Hold' THEN 1 ELSE 0 END) AS hold_count
            FROM projects p
            LEFT JOIN tasks t ON p.project_id = t.project_id
            LEFT JOIN progress_logs l ON p.project_id = l.project_id
            WHERE p.is_hidden = 0
            GROUP BY p.project_id, p.name
            """)
            prj_stats = [dict(r) for r in cursor.fetchall()]

        return {
            "total_logs": total_logs,
            "total_revisions": total_revisions,
            "active_projects": active_projects,
            "active_employees": active_employees,
            "employee_breakdown": emp_stats,
            "project_breakdown": prj_stats
        }

    def get_project_timeline_data(self, project_id: str, discipline_id: str = None, assigned_head_id: str = None) -> dict:
        """Returns progressive timeline analysis for project visualization."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
            prj = cursor.fetchone()
            if not prj:
                return {}

            tasks = self.get_tasks(project_id=project_id, discipline_id=discipline_id,
                                   assigned_head_id=assigned_head_id, include_hidden=False)

            task_timeline = []
            total_tasks = len(tasks)
            completed_tasks = 0
            in_progress_tasks = 0
            hold_tasks = 0
            revision_tasks = 0
            total_progress_sum = 0

            for t in tasks:
                cursor.execute("""
                SELECT progress_percentage, progress_stage, entry_type, revision_number, submitted_at, notes, assigned_to
                FROM progress_logs
                WHERE task_id = ?
                ORDER BY submitted_at DESC, log_id DESC
                LIMIT 1
                """, (t["task_id"],))
                latest_log = cursor.fetchone()

                cursor.execute("""
                SELECT COUNT(*) AS rev_count
                FROM progress_logs
                WHERE task_id = ? AND entry_type = 'REVISION'
                """, (t["task_id"],))
                rev_row = cursor.fetchone()
                rev_count = rev_row["rev_count"] if rev_row else 0

                cur_pct = latest_log["progress_percentage"] if latest_log else 0
                cur_stage = latest_log["progress_stage"] if latest_log else "Not Started"

                if cur_stage == "Done" or cur_pct >= 100:
                    completed_tasks += 1
                elif cur_stage == "Revision":
                    revision_tasks += 1
                elif cur_stage == "Hold":
                    hold_tasks += 1
                elif cur_stage == "In Progress":
                    in_progress_tasks += 1

                total_progress_sum += cur_pct

                task_timeline.append({
                    "task_id": t["task_id"],
                    "name": t["name"],
                    "discipline_id": t.get("discipline_id"),
                    "discipline_name": t.get("discipline_name") or t.get("discipline_id") or "Unassigned",
                    "assigned_head_id": t.get("assigned_head_id"),
                    "assigned_head_name": t.get("assigned_head_name"),
                    "planned_start_date": t.get("planned_start_date"),
                    "planned_end_date": t.get("planned_end_date"),
                    "progress_percentage": cur_pct,
                    "progress_stage": cur_stage,
                    "revision_count": rev_count,
                    "latest_assigned_to": latest_log["assigned_to"] if latest_log else ""
                })

            overall_progress = round(total_progress_sum / total_tasks) if total_tasks > 0 else 0

            task_timeline.sort(key=lambda x: (x["planned_start_date"] or "9999", x["task_id"]))

            return {
                "project_id": prj["project_id"],
                "project_name": prj["name"],
                "description": prj["description"],
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "in_progress_tasks": in_progress_tasks,
                "revision_tasks": revision_tasks,
                "hold_tasks": hold_tasks,
                "overall_progress_percentage": overall_progress,
                "tasks": task_timeline
            }


class ClientQueueDBManager:
    """
    Local SQLite outbox on each workstation. Items are written here before they are sent,
    and removed only after the Central Server confirms the write.
    status: PENDING (will be sent / retried) or FAILED (server rejected it; needs user action).
    """
    def __init__(self, queue_db_path: Path = CLIENT_QUEUE_DB_PATH):
        self.db_path = queue_db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

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
            cursor.execute("PRAGMA table_info(offline_queue)")
            cols = [c["name"] for c in cursor.fetchall()]
            if "user_id" not in cols:
                cursor.execute("ALTER TABLE offline_queue ADD COLUMN user_id TEXT")
            if "item_id" not in cols:
                cursor.execute("ALTER TABLE offline_queue ADD COLUMN item_id TEXT")
            if "status" not in cols:
                cursor.execute("ALTER TABLE offline_queue ADD COLUMN status TEXT DEFAULT 'PENDING'")
            if "last_error" not in cols:
                cursor.execute("ALTER TABLE offline_queue ADD COLUMN last_error TEXT")
            if "attempts" not in cols:
                cursor.execute("ALTER TABLE offline_queue ADD COLUMN attempts INTEGER DEFAULT 0")
            # Backfill item_id / user_id for rows written by older versions
            cursor.execute("SELECT queue_id, payload_json FROM offline_queue WHERE item_id IS NULL")
            for r in cursor.fetchall():
                try:
                    data = json.loads(r["payload_json"])
                except Exception:
                    data = {}
                item_id = next((data.get(f) for f in ("log_id", "request_id", "proposal_id", "notification_id") if data.get(f)), None)
                owner = data.get("employee_id") or data.get("proposed_by_id") or data.get("requested_by_id")
                cursor.execute("UPDATE offline_queue SET item_id = ?, user_id = COALESCE(user_id, ?) WHERE queue_id = ?",
                               (item_id or f"LEGACY-{r['queue_id']}", owner, r["queue_id"]))
            conn.commit()

    def enqueue(self, user_id: str, event_type: str, item_id: str, payload: dict) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO offline_queue (event_type, payload_json, user_id, item_id, status)
                              VALUES (?, ?, ?, ?, 'PENDING')""",
                           (event_type, json.dumps(payload), user_id, item_id))
            conn.commit()
            return cursor.lastrowid

    def get_items(self, user_id: str, status: str = None) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM offline_queue WHERE user_id = ?"
            params = [user_id]
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY queue_id ASC"
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def count(self, user_id: str, status: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM offline_queue WHERE user_id = ? AND status = ?",
                               (user_id, status)).fetchone()
            return row["n"]

    def delete_item(self, queue_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM offline_queue WHERE queue_id = ?", (queue_id,))
            conn.commit()

    def mark_attempt(self, queue_id: int):
        with self.get_connection() as conn:
            conn.execute("UPDATE offline_queue SET attempts = attempts + 1 WHERE queue_id = ?", (queue_id,))
            conn.commit()

    def mark_failed(self, queue_id: int, error: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE offline_queue SET status = 'FAILED', last_error = ? WHERE queue_id = ?",
                         (error, queue_id))
            conn.commit()

    def retry_item(self, queue_id: int):
        with self.get_connection() as conn:
            conn.execute("UPDATE offline_queue SET status = 'PENDING', last_error = NULL WHERE queue_id = ?",
                         (queue_id,))
            conn.commit()

    # Kept for older callers/tests
    def add_to_queue(self, event_type: str, payload_json: str):
        data = json.loads(payload_json)
        item_id = next((data.get(f) for f in ("log_id", "request_id", "proposal_id", "notification_id") if data.get(f)), None)
        owner = data.get("employee_id") or data.get("proposed_by_id") or data.get("requested_by_id")
        self.enqueue(owner, event_type, item_id or uuid.uuid4().hex, data)

    def get_all_queued(self) -> list[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM offline_queue ORDER BY queue_id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_queued_by_payload_id(self, event_type: str, item_id: str):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM offline_queue WHERE event_type = ? AND item_id = ?", (event_type, item_id))
            conn.commit()

    def clear_queue(self):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM offline_queue")
            conn.commit()
