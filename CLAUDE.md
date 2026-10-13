# CLAUDE.md

Guidance for working on DeskApp. Read this before changing code.

## What DeskApp is

An internal desktop app for an engineering company. Department **Heads** log daily progress on project tasks. **Admin**, **COO** and **Super Admin** manage projects, tasks and users, oversee the work, approve requests and export Excel reports. Spec and history: `AUDIT_REPORT.md` (audit + plan), `CHANGELOG.md` (what changed, by milestone), `APPLICATION_WORKFLOW_SUMMARY.txt` (workflows and function directory), `DEPLOYMENT.md` (installation guide for IT).

## Hard constraint: air-gapped LAN

- No PC ever has internet. Nothing may need internet at runtime: no cloud services, CDNs, license checks, update checks or pip installs on target PCs.
- Target PCs have no Python. They get the PyInstaller folder `dist/DeskApp/`.
- A new dependency needs a real reason, must work offline, and must be bundled by PyInstaller (check the build). Pin it in `requirements.txt`.

## Architecture

```
Central Server PC                          Workstation PCs
DeskAppServer.exe (main.py --server-only)  DeskApp.exe (main.py)
  CentralWebSocketServer  <== ws://IP:8765 ==>  NetworkClient (+ SyncService outbox for Heads)
  DBManager -> data/central_app.db (WAL)        data/client_queue.db (offline outbox)
  BackupScheduler -> data/backups/              QSettings (server IP, layouts)
```

- **Only the server process opens `central_app.db`.** Clients never touch it; they get everything through WebSocket actions.
- **Protocol** (`app/network/protocol.py`, `PROTOCOL_VERSION = 2`): requests are `{action, payload, msg_id}`. Every request gets exactly one reply `{type, msg_id, ok, error?, code?, ...}`. Server-pushed events have no `msg_id`: `DATA_CHANGED {scopes}`, `NEW_LOG_EVENT`, `COO_PRIORITY_ALERT`, `NOTIFICATION_RESPONSE_EVENT`, `*_PROPOSAL_*_EVENT`, `TASK_DATE_CHANGE_EVENT`. Excel exports arrive as `EXPORT_EXCEL_CHUNK` frames followed by the reply. Bump `PROTOCOL_VERSION` when old and new can no longer talk; all PCs must then be upgraded together.
- **Sessions:** `LOGIN` (or `RESUME` with the session token after a reconnect) binds the user, role and discipline **from the DB** to the socket. Only a SHA-256 of the token is stored (`user_sessions`).
- **Authorization lives on the server.** Each handler is registered with `@action(name, roles=...)` in `app/network/server.py`. The acting user always comes from the `Session`, never from the payload. Heads are additionally scoped to their discipline (and to tasks pinned to them). `tests/test_protocol.py::EXPECTED_ROLES` is the permission table; changing a permission means editing that table on purpose.
- **Server concurrency:** all DB calls go through `await self.db_call(...)`, which uses a single worker thread. Excel generation has its own thread. Never call the DB or do slow work directly on the event loop.
- **Writes** that read, check and then update use `DBManager.transaction()` (`BEGIN IMMEDIATE`). Foreign keys are enforced on every connection.
- **Offline outbox (Heads):** `SyncService.submit()` writes to `client_queue.db` first, sends when connected, and deletes only after the server confirms. Permanent rejections (`FORBIDDEN`/`VALIDATION`) become `FAILED` items the Head can retry or discard. Every queued action must be **idempotent** on the server, keyed by a client UUID (`log_id`, `proposal_id`, `request_id`, `notification_id`).
- **Qt + asyncio:** qasync runs one loop. UI code must not run inside an asyncio task, because a modal `exec()` there freezes networking. Use `net_client.call(action, payload, on_ok, on_err)` or `run_async(coro, on_ok, on_err)`: callbacks and signals are delivered via `loop.call_soon`. Don't write `async def` UI handlers that open dialogs.
- **UI structure:** `RoleWindow` (header, Logout, connection banner, footer) wraps `AdminPanel` / `CooPanel` / `SuperAdminPanel`; the Super Admin console embeds the Admin and COO panels. `HeadWorkspace` is its own window. Panels reload only the scopes named in `DATA_CHANGED` (through `ChangeDebouncer`). Notifications go through `ToastNotifier`, which shows in the window's single bottom `ToastOverlay`.

## Data model notes

- Schema migrations: `DBManager._migrate()`, tracked with `PRAGMA user_version` (currently `SCHEMA_VERSION = 6`). Add a new numbered step; each step must be idempotent and run in a transaction. Test it against the fixtures in `tests/fixtures/` and against real DB copies (`tests/test_migrations.py`). **Never delete or rewrite user data in a migration**; report dangling rows instead.
- **Soft delete:** `projects.is_deleted` / `tasks.is_deleted`. Deleted rows disappear from every list but keep their logs; Excel labels them "(Deleted)". **Hide** (`is_hidden`) is a separate, reversible flag.
- **Revision numbers** (R1, R2...) are assigned by the server per task, inside the insert transaction. **Task IDs** (`TSK-NN`) are assigned when the task is created, never reserved earlier.
- Timestamps are local time, `YYYY-MM-DD HH:MM:SS`. Dates are `YYYY-MM-DD`. Use `now_local()`, `parse_date()` and `check_date_order()` from `db_manager.py`.
- Passwords are stored as a PBKDF2 hash (used for login) **and**, by the owner's decision, as a readable copy `users.password_plain` shown only to the Super Admin (`GET_USERS` adds it for that role only). Every place that sets a password must call `_remember_password()`; `authenticate()` fills it in for accounts set before v5. Never send it to other roles or write it to logs.
- Accounts: the first start creates `superadmin` with a random one-time password, printed on the server console and saved to `data/FIRST_RUN_CREDENTIALS.txt`. New accounts start with password = user ID and must change it. The password minimum length is a system setting (`system_settings` table).
- Disciplines: `URB, STR, INT, ARC, BIM, MEC, ELE, AI, QC, Infrastructure` (`config.DEFAULT_DISCIPLINES`). Heads are seeded idempotently from `data/seed_heads.json`.

## Commands

```bash
pip install -r requirements-dev.txt          # on a build/dev PC (the only place that needs pip)
python -m pytest -q                          # full suite, about 2-5 minutes; never touches data/ or the registry
python main.py --server-only                 # Central Server (data in ./data)
python main.py                               # client (asks for the server IP)
python main.py --standalone                  # demo: embedded server + client, separate ./data_demo folder
python main.py --server-only --data-dir D:/x # any data folder
python main.py --restore data/backups/central_app_YYYYMMDD_HHMMSS.db   # server stopped
python main.py --reset-superadmin            # recovery, server stopped
python -m PyInstaller DeskApp.spec --noconfirm   # -> dist/DeskApp/{DeskApp.exe, DeskAppServer.exe}
```

To run several clients on one PC, give each its own `DESKAPP_DATA_DIR` (offline queue) and `DESKAPP_SETTINGS_DIR` (UI settings as INI files instead of the registry).

## Conventions

- Match the surrounding code: type hints on new functions, short docstrings that say *why*, no emojis in UI text, Zinc/Purple colors only (`tests/test_ui_static.py` enforces both). "&" in tab or button labels must be written "&&".
- Every server change gets a protocol-level test (`tests/helpers.py` has `start_server()`, `RawClient` and `CuttableProxy`). UI wiring is covered by the headless `tests/test_gui_smoke.py`.
- User-facing errors come from the server message (`describe_error()`). Never show a success message before the server confirms.
- Keep commits small, one milestone or concern each. Work on `main`; use a short-lived branch for large changes and merge it when approved.
