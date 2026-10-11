-- Schema created by the very first DeskApp version (commit 5b3b15a). Used by tests/test_migrations.py.

CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    full_name TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('HEAD', 'ADMIN', 'COO', 'SUPER_ADMIN')),
    must_change_password INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(project_id)
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
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'SYNCED',
    FOREIGN KEY(employee_id) REFERENCES users(user_id),
    FOREIGN KEY(project_id) REFERENCES projects(project_id),
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
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
