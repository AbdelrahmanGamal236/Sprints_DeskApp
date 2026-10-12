# DeskApp

An internal desktop app for an engineering company's offline local network. Department **Heads** log daily progress on project tasks. **Admin**, **COO** and **Super Admin** manage projects and people, approve requests, watch progress live and export Excel reports.

- Works on a fully **air-gapped LAN**. No PC needs internet, and target PCs don't need Python.
- **One Central Server PC** holds the database. Every other PC runs the client and connects to `ws://<server-ip>:8765`.
- Heads can keep working through network drops. Their entries are queued on their PC and sent automatically, with no loss and no duplicates.

## Documents

| File | For |
|---|---|
| [INSTALL_GUIDE.txt](INSTALL_GUIDE.txt) | Anyone: short plain-text guide to which PC gets what and how the server IP works |
| [DEPLOYMENT.md](DEPLOYMENT.md) | IT: installing the server and clients, firewall, first login, backups and restore, troubleshooting |
| [APPLICATION_WORKFLOW_SUMMARY.txt](APPLICATION_WORKFLOW_SUMMARY.txt) | How every workflow works, the server actions and permissions, and a directory of modules and functions |
| [CLAUDE.md](CLAUDE.md) | Developers: architecture, rules, commands |
| [CHANGELOG.md](CHANGELOG.md) | What changed, by milestone |
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | The audit that started the stabilization work, plus its final status |

## Quick start (developer PC)

```bash
pip install -r requirements-dev.txt
python -m pytest -q                 # full test suite
python main.py --server-only        # Central Server; prints the first-run Super Admin password
python main.py                      # client; enter the server IP in the login window
python main.py --standalone         # single-PC demo with sample data (separate data_demo/ folder)
python -m PyInstaller DeskApp.spec --noconfirm   # builds dist/DeskApp/
```

The build folder `dist/DeskApp/` contains:
- `DeskApp.exe`: the client
- `DeskAppServer.exe`: the server, with a console window
- both launch scripts, `INSTALL_GUIDE.txt`, `DEPLOYMENT.md`, and `seed_heads.example.json`

Copy that whole folder to each PC.

## Stack

Python 3.10, PySide6 (Qt), qasync, websockets, SQLite (WAL), openpyxl, pytest, PyInstaller. Versions are pinned in `requirements.txt`.

---
All Rights Reserved to Eng. Abdelrahman Gamal & Eng. Tolimy
