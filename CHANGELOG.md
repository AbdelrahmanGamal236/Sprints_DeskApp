# Changelog

Finding IDs (F-xx) refer to `AUDIT_REPORT.md`.

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
