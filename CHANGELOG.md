# Changelog

Finding IDs (F-xx) refer to `AUDIT_REPORT.md`.

## M3: Workflows

### All roles
- **Targeted change events** replace "reload everything". The server now says which kinds of data changed: projects, tasks, disciplines, users, proposals, date changes or settings. Each screen reloads only that.
  - These events go only to the roles that need them. For example, a decision on a proposal reaches the managers and the Head who proposed it, not every Head.
  - Clients merge a burst of events into a single reload.
- When an Admin changes a task, the Heads' task lists update immediately, with no refresh needed.

### Head
- The **project selector is at the top**, with the discipline tab and its tasks below it. The selected project drives both the logging form and the project timeline. (F-22)

### Admin / COO / Super Admin
- The Admin and COO tools are now **reusable panels**. The Super Admin console embeds the real panels instead of borrowing the inside of hidden windows, and all role windows share one header/Logout/footer frame. (F-17)
- New **System Settings tab** for the Super Admin, stored on the server:
  - number of daily backups to keep (used when old backups are pruned)
  - daily backup time
  - minimum password length (applies immediately and is sent to clients at login)
  - login lifetime
  - It also shows **Central Server status**: port, database file, schema version, record counts, backup folder, latest backup and who is connected now.
- The Super Admin can **edit any account** (name, role, discipline). The last Super Admin account cannot be given another role.
- Splitter layouts for Admin and COO are saved **per user**. (F-26)
- Admin analytics refresh live as new logs arrive.

### Tests
- System settings, live password policy, targeted events (who receives what), the last-Super-Admin guard, and a live task update reaching a Head's screen without a refresh.

## M2: Data model, integrity and migrations

### Database
- **WAL mode** is on, so reads such as exports don't block writes. **Foreign keys are now enforced.** Writes that read and then update run in a single transaction that locks the database first. (F-14)
- **Versioned migrations** use `PRAGMA user_version`, and each step runs only once and is safe to repeat:
  - v2 adds soft-delete columns and indexes.
  - v3 converts old log timestamps from UTC to local time. (F-25)
- Old rows that point to missing users, projects or tasks are kept and reported in the server log, never deleted.
- A seed Head with an unknown discipline code is skipped with a warning instead of stopping the server.

### Workflow rules (enforced on the server)
- **Revision numbers (R1, R2...)** are now assigned by the server, counted per task, at the moment the log is saved. The number the client sends is ignored, so logs submitted offline or at the same time still get unique, sequential numbers. (F-12)
- **Task proposals and date-change requests** can only be decided while pending:
  - Approving twice does nothing the second time and never creates a duplicate task.
  - A rejected request can't be approved, and an approved one can't be rejected. (F-13)
- Task IDs are assigned when the task is created, not reserved when a proposal is submitted. (F-14)
- **Soft delete for projects and tasks:** a deleted item disappears from every screen. Its row and all its logs stay in the database and are flagged for reports, and its ID can't be reused. (F-16)
- **Hidden or deleted tasks no longer accept new logs**, and a task must belong to the project the log names.
- **The server validates everything a client sends:** dates (`YYYY-MM-DD`, start before end), progress stage, entry type, percentage 0-100, text lengths, and that disciplines and assigned Heads exist and match. (F-24)

### UI
- Heads enter a **progress percentage** (0-100). Choosing the "Done" stage sets it to 100. (F-22)
- Admins get a **Delete** button with a confirmation dialog for projects and tasks. (F-16)

### Tests
- `tests/test_migrations.py` migrates the schema from the very first version and from the version just before this work. It also migrates copies of the real `data/central_app.db` and the oldest backup when they exist. Each migration runs twice to prove the second run changes nothing.
- `tests/test_data_integrity.py` covers:
  - revision numbers, including 12 concurrent writers
  - approval rules
  - task IDs created concurrently
  - soft delete
  - validation
  - local timestamps

## M1: Core architecture correctness

**Upgrade note:** the network protocol changed (version 2). Upgrade the server and **all** client PCs together. An old client trying to connect gets a clear "version does not match" message.

### Security
- Each socket gets a session from LOGIN/RESUME, with identity loaded from the database. `IDENTIFY` is removed. (F-01)
- Every server action declares which roles may call it, and the server rejects everything else. The acting user always comes from the session, never from the payload. (F-03, F-04)
- A password change needs a logged-in session, plus the old password except for the forced first-login change. New passwords need at least 8 characters and must differ from the user ID. (F-02, F-08)
- The forced first-login password change is now enforced by the server, not only by the UI. (F-08)
- The `admin/admin`, `coo/coo` and `superadmin/superadmin` accounts are no longer created. On first start the server creates `superadmin` with a random one-time password. It prints the password on the server console and saves it to `data/FIRST_RUN_CREDENTIALS.txt`. Legacy default accounts that were never used get the same treatment. (F-07)
- Passwords use PBKDF2-SHA256 with 600k iterations and are compared in constant time. Older hashes are upgraded on the next login. (F-27)
- After 5 wrong passwords, that user ID is locked out for 60 seconds.
- When an admin resets a password, that user's open sessions are closed.

### Reliability
- Database work runs on a dedicated worker thread, and Excel exports on their own thread. Exports are streamed in chunks, so large exports no longer disconnect other users or exceed the WebSocket frame limit. (F-05, F-06)
- Every request gets a reply, and errors are shown to the user. A bad request no longer drops the connection. (F-09)
- Each reply goes only to the screen that made the request. For example, the Super Admin no longer gets two Save dialogs, and user lists no longer overwrite each other. (F-17)
- The offline outbox now:
  - uses full UUIDs (F-11)
  - is kept per user, so a different user on the same PC never sends someone else's items
  - removes an item only after the server confirms it
  - keeps items the server rejects as "Rejected Items" that the Head can retry or discard, instead of retrying them forever
  - retries automatically after reconnecting and every 30 seconds (F-10)
- Login happens on the persistent connection without freezing the window. After a network drop the client reconnects and resumes the session automatically. (F-20)
- COO alerts are not created twice when a request is resent, and only the Head an alert was sent to can answer it.

### Workflows / UI
- Head toasts reflect what actually happened: "saved on the Central Server", "queued offline" or "rejected: reason". (F-10)
- A COO alert opens one modal, even across refreshes and reconnects. (F-21)
- The COO's response tracker loads earlier alerts from the server and updates rows in place. (F-21)
- The Head's splitter layout is saved per user, and the duplicate method definitions were removed. (F-26, partial)
- The Admin timeline project dropdown no longer gains duplicate entries on every refresh.
- `--standalone` demo mode uses a separate `data_demo` folder.

### Tests
- `tests/test_protocol.py`: every attack from the audit is replayed and rejected, and every action is checked against every role on a live server.
- `tests/test_sync_integration.py`: a server and two clients, with a network link that is cut and restored. Checks offline queueing, reconnect, no loss, no duplicates and rejected-item handling.
- `tests/test_gui_smoke.py`: a headless run through all four roles.
- Tests never touch the real `data/` folder or the Windows registry.

## M0: Baseline
- Committed the codebase as found.
- Tests use a temporary data folder. Previously, running the tests wrote into `data/backups/`. (F-29)
- Added pinned `requirements.txt` and `requirements-dev.txt`, plus `.gitattributes`. (F-30, F-36)
