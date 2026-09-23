# Sprints DeskApp - Workstation & Progress Tracking System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![PySide6](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-7C3AED.svg)
![Architecture](https://img.shields.io/badge/Architecture-Offline--First%20%2F%20LAN-green.svg)
![License](https://img.shields.io/badge/License-MIT-brightgreen.svg)

**DeskApp** is a modern, high-performance desktop application built for offline-first LAN task logging, progress management, and project tracking. Designed with **PySide6**, **SQLite**, and **`qasync` WebSockets**, DeskApp enables seamless collaboration across local networks without requiring external cloud connectivity.

---

## Key Features

- **Modern Split-Screen UI Design**:
  - Dark Mode theme featuring Matte Zinc (`#141417`) and Vibrant Purple (`#7C3AED`) accents.
  - Custom styled input fields, scroll bars, status indicators, and clean typography.
  - Zero emojis for a clean enterprise interface.

- **Multi-Role Workstation Views**:
  - **Employee Workstation**: Daily Progress Logging Form with Project & Task selection, start/end dates, task logging context, status selection, and detailed work notes.
  - **Admin / COO / SuperAdmin Workstations**: Executive dashboards, project monitoring, task assignment, and analytics.

- **Advanced Revision & Rework Tracking**:
  - Tracks task context: `New Task`, `Continuation`, and `Revision / Rework`.
  - Automatic incremental tracking for rework iterations (**R1, R2, R3...**) per employee and per project to provide insights into rework frequency and code/design quality.

- **Offline-First LAN Network Architecture**:
  - Built-in asynchronous WebSocket Server (`qasync` + `websockets`).
  - Automatic fallback to local offline SQLite database (`client_queue.db`) when central server LAN connection is unavailable.
  - Auto-reconnect and sync engine when connection is restored.

- **User Session & Header Management**:
  - Top navigation bar dynamically displays current employee name and user ID (e.g., `Employee: Eng. Abdelrahman (1001)`).
  - Built-in **Logout** dialog allowing clean session termination and instant return to the Login screen.

---

## Tech Stack

| Component | Technology |
| :--- | :--- |
| **Language** | Python 3.10+ |
| **GUI Framework** | PySide6 (Qt 6 for Python) |
| **Async Integration** | `qasync` (Asyncio event loop for PySide6) |
| **Database Engine** | SQLite 3 (WAL mode enabled) |
| **Networking** | `websockets` (Asynchronous LAN Server/Client) |
| **Packaging** | PyInstaller |

---

## Project Directory Structure

```
DeskApp/
├── app/
│   ├── core/           # Configuration parameters and application constants
│   ├── database/       # Database Manager, migrations, and schema models
│   ├── network/        # Async WebSocket Server & Client sync daemons
│   └── ui/             # PySide6 Windows, Dialogs, Styles (QSS), and UI components
├── data/               # Local SQLite database storage
├── tests/              # PyTest test suite for core logic and network sync
├── DeskApp.spec        # PyInstaller build specification
├── Launch_DeskApp.bat  # Quick launch script for DeskApp GUI
├── main.py             # Main application entry point
├── README.md           # Documentation
└── .gitignore          # Git exclusion rules
```

---

## Installation & Setup

### Prerequisites
- Python 3.10 or higher installed on your system.

### 1. Clone the Repository
```bash
git clone https://github.com/AbdelrahmanGamal236/Sprints_DeskApp.git
cd Sprints_DeskApp
```

### 2. Set Up Virtual Environment (Recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install PySide6 qasync websockets openpyxl pytest
```

---

## Running the Application

### Option A: Run via Python
To start the application directly from source:
```bash
python main.py
```

### Option B: Run via Batch Launcher
Double-click `Launch_DeskApp.bat` or run in terminal:
```bash
Launch_DeskApp.bat
```

---

## Credentials for Testing

You can use the following default demo credentials on the Login screen:

| Username / ID | Password | Role |
| :--- | :--- | :--- |
| **`1001`** | `1234` | Employee |
| **`admin`** | `admin` | Admin |
| **`coo`** | `coo` | COO |
| **`superadmin`** | `superadmin` | Super Admin |

*Default Central Server LAN IP:* `127.0.0.1`

---

## Building Standalone Executable (.exe)

To generate a single-folder standalone Windows executable:

```bash
pyinstaller DeskApp.spec --noconfirm
```
The compiled output will be generated inside the `dist/DeskApp/` directory.

---

## Running Unit Tests

Run the automated test suite with `pytest`:

```bash
pytest tests/
```

---

## Credits

Developed by **Eng. Abdelrahman Gamal & Eng. Tolimy**.
