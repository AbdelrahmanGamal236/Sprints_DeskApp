-- Schema of a production database created by the code before the stabilization work (user_version 0).
-- Captured from data/central_app.db on 2026-10-12. Used by tests/test_migrations.py.

CREATE TABLE disciplines (
                discipline_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE users (
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

CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                is_hidden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE tasks (
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

CREATE TABLE employee_projects (
                employee_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(employee_id, project_id),
                FOREIGN KEY(employee_id) REFERENCES users(user_id),
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

CREATE TABLE progress_logs (
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

CREATE TABLE priority_notifications (
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

CREATE TABLE task_proposals (
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

CREATE TABLE task_date_change_requests (
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
