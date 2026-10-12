# Changelog

Finding IDs (F-xx) refer to `AUDIT_REPORT.md`.

## Unreleased

- **Super Admin can see passwords.** The accounts table has a new Password column showing each user's current password. The server sends it to the Super Admin only, never to Admin or COO. A database upgrade (schema version 5) adds the readable copy. Accounts still on their first password (the user ID) show it right away. Others show "Unknown (log in once)" until that user logs in again. Changing or resetting a password keeps the column current. The passwords are also readable in the database file and its backups, so those must be kept private (see DEPLOYMENT.md).
- **Smoother, easier scrollbars.** The bars are wider (14 px) and easier to see and grab. They turn purple while hovered or dragged, and clicking the track jumps a page. Lists and tables now scroll smoothly pixel by pixel instead of jumping a row at a time, everywhere in the app.
- **INSTALL_GUIDE.txt:** a short plain-text guide to which PC gets which program and how the server IP works. It is included in the build folder.
- **Fixed: three Admin buttons did nothing.** "+ Add New Task Directly", Edit on a task and Edit on a Head crashed silently because a Qt import was missing. This affected the Super Admin console too. A new test drives the Add Task dialog end to end, and a static check (pyflakes) now fails the suite on any undefined name.
- **Daily log dates are locked to the task.** When a Head selects a task, its planned Start and End dates are shown read-only. These come from the Head's approved request, or from a later approved date change. Logging never changes the task's dates. The server stamps each log with the task's current dates and ignores dates sent by a PC, so logs queued offline are correct too. Earlier logs keep the dates that applied when they were submitted.
- **Progress % removed.** Heads report only the stage. On the project timeline a task counts as 100% when its latest stage is Done, otherwise 0%, and the project's overall % is the average. Older logs keep their stored % in the database.
- **Excel export rebuilt for daily status reporting.** Each row starts with Submitted Date and Submitted Time, followed by the Head, project, task, the task's start and end dates, Status, Entry Type, Revision Tag, Assigned To and Notes. Log ID is now the last column, and the Progress % column is gone.
- **The export date filter now uses the submission day.** "From / To" selects logs submitted on those days, both ends inclusive. It no longer filters on overlapping work periods.

## M6: Hardening, backups, logging, packaging, deployment

### Backups and recovery
- **Daily backups while the server runs.** One is made at startup if none exists for today, then one every day at the Super Admin's backup time (default 02:00). Copies use SQLite's online backup API, so they are safe while people work. Each copy is integrity-checked, and a bad copy is discarded. Each backup is a single file named `central_app_YYYYMMDD_HHMMSS.db`, and the newest N are kept (setting). Older-style backup files are never deleted. (F-18)
- **`--restore <file>`** puts a backup back in place:
  - It refuses while the server is running and refuses damaged files.
  - It asks you to type YES (`--yes` skips that).
  - It first saves the current database as `central_app_pre_restore_*.db`.
- **`--reset-superadmin`** is a recovery command used while the server is stopped. It gives `superadmin` a new one-time password.
- Each database keeps its backups in a `backups` folder next to itself.

### Logging
- Rotating log files (5 x 5 MB): `data/logs/server.log` and `data/logs/client.log`. Unhandled errors are written to them. The noisy websockets library logs only warnings. (F-33)

### Packaging
- `DeskApp.spec` builds two programs in one folder:
  - **`DeskApp.exe`**: the client, with no console window
  - **`DeskAppServer.exe`**: the server, with a console window that shows status and the first-run password (F-19)
- The server program doesn't load Qt.
- numpy and other unused libraries are excluded, shrinking the build from 240 MB to 122 MB. (F-30)
- The build folder also contains `Launch_DeskApp.bat`, `Launch_Server_Daemon.bat`, `DEPLOYMENT.md` and `seed_heads.example.json`.
- Both launchers use absolute paths (`%~dp0`), so they work wherever the folder is copied, and also on PCs where Windows doesn't run programs from the current folder.
- **Data folder:** `data` next to the program. `--data-dir` overrides it. If that folder isn't writable (for example under Program Files), `%PROGRAMDATA%\DeskApp\data` is used.
- The version (2.0.0) appears in the login window title, the server log and System Settings. `--version` prints it.

### Removed
- `rebuild_db.py`. It deleted the live database and filled it with demo data. Use `--standalone` for a demo. (F-32)

### Documentation
- New: `DEPLOYMENT.md` (for IT), `CLAUDE.md` (for developers).
- Rewritten: `README.md` and `APPLICATION_WORKFLOW_SUMMARY.txt`, to match the code.
- `AUDIT_REPORT.md` Section 8 lists the status of every finding. (F-35)

### Verified on the frozen build, from a clean copy of `dist/DeskApp`
- `Launch_Server_Daemon.bat`: the console shows the one-time password, the Heads are seeded, migrations and a backup run, the log file is written, and the Super Admin logs in.
- `Launch_DeskApp.bat`: the client starts and writes its log.
- `--restore`, cancelling the restore, `--reset-superadmin` and `--version` all work.

### Tests
- `tests/test_maintenance.py` covers:
  - the backup schedule, using a simulated clock
  - integrity checks and retention
  - restore, including refusing while the server runs
  - the emergency reset
  - the log file

## M5: UI/UX polish

### Notifications
- **One notification bar per window, at the bottom centre.** It floats above the content, takes no layout space and lets clicks pass through to the buttons underneath. Green means success, amber means queued or warning, red means error, and errors stay on screen a little longer. Panels embedded in the Super Admin console share their window's bar. (F-22)
- **Connection banner:** a red bar under the header in every role's window while the Central Server can't be reached. The Head's version explains that logs are kept on the PC and sent automatically. The Head's sync badge now actually turns red when offline; before, it stayed green.

### Consistency
- **No emojis or arrow symbols anywhere in the UI.** Arrows became "to", the person icons were removed, and the KPI cards use short text badges. A test now blocks emojis from coming back. (F-26)
- **Zinc/Purple palette only.** Leftover slate, blue, indigo and cyan colors in the alert modal, footer, KPI cards, timeline and focus borders were replaced. A test checks this as well.
- "&" in tab and button labels now shows correctly. Before, Qt read it as a keyboard-shortcut marker and showed "Manage Heads _Users".
- Labels no longer draw dark boxes inside cards. Number fields match the other inputs. KPI cards no longer cut off their numbers, and their badge colors are correct (Qt reads 8-digit hex colors as ARGB, not RGBA).
- **Head screen:** the header reads "Head: name (ID) - discipline name". The leftover step numbers ("3. Start Date"...) were removed. The discipline tab shows the full discipline name.
- **COO live feed:** entry types read New / Continuation / Revision (R1), as in the Excel report.

### Preventing double clicks
- Admin, COO and Super Admin buttons that change data stay disabled until the server answers.
- The Head's Submit button pauses for 1.5 seconds after each submission.

### Tests
- `tests/test_ui_static.py` checks for emojis and off-palette colors.
- The GUI test checks that the notification bar sits at the bottom of the window and that the connection banner appears when offline and hides again on reconnect.

## M4: Excel and analytics

### Excel export
- **Date-range filter** in both the Admin and COO exports. A log is included when its start-end work period overlaps the selected dates at all, so logs that run across the edge of the range are no longer dropped. (F-23)
- **The COO export now has the same filters as the Admin export:** project, discipline, Head and date range. It opens in a dialog. (F-23)
- **New column layout:**
  - Head ID, Head Name and Head Discipline
  - Project, Task ID, Task and Discipline
  - Assigned To
  - Entry Type and Revision Tag (R1, R2...) as separate columns
  - Start/End dates, Status, **Progress %**, Notes and Submitted At
- **"(Hidden)" and "(Deleted)" labels** on projects, tasks and disciplines. Those rows are shown in grey and are never dropped from the report.
- A new **"Report Info" sheet** records the filters used, the date rule, the row count, when the report was generated and by whom. The copyright line moved there, out of the data sheets.
- Sheet names are made safe for Excel: characters Excel forbids are replaced, names are cut to 31 characters, and duplicates are numbered.
- **Faster:** the workbook is written in streaming mode, and only header and grey rows are styled. 15,000 logs now take about 9 seconds instead of about 50, and 20,000 logs about 14 seconds. Exports still run on their own server thread.

### Analytics and timeline
- **The project numbers were wrong and are now correct.** Each total is counted on its own, so totals are no longer multiplied by the number of tasks in a project. (F-15)
- Project breakdown: task status now means the stage of each task's most recent log (Done / In Progress / Hold / Revision / Not Started). Deleted and hidden items don't count.
- **Project timeline:** two database queries instead of two per task. Progress uses the latest log's percentage, and "Done" counts as 100%. (F-28)

### Tests
- `tests/test_reports.py` checks:
  - export sheets, headers, labels, revision tags, percentages and the info sheet
  - every filter, including the date-overlap edges and invalid dates
  - analytics numbers against hand-counted examples, and the timeline
  - a timed export of 20,000 logs
- The headless GUI test now runs an export through the real Admin export panel.

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
