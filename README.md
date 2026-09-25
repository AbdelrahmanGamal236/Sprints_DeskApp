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

- **Analysis & Revision Insights Panel**:
  - Real-time metrics overview: Total Progress Logs, Total Revisions/Rework, Active Projects, Active Head Employees.
  - Per-Employee Rework Breakdown: Tracks New Tasks, Continuations, and Revisions (Rework) per employee.
  - Per-Project Status Breakdown: Monitors task progress stages (Done, In Progress, Hold) and total Rework Cycles per project.

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

## Deployment & Setup Guide (LAN Network Deployment)

### 🖥️ 1. Central Server Setup (إعداد جهاز السيرفر الرئيسي)

The Central Server runs in **Headless Daemon Mode** (`--server-only`) to manage real-time WebSocket messaging and central database synchronization.

#### Method A: Using Standalone Executable (Recommended for Non-Developers)
1. Copy the compiled `dist/DeskApp/` directory to the Central Server PC.
2. Double-click **`Launch_Server_Daemon.bat`** (or run `DeskApp.exe --server-only` in CMD).
3. **Firewall Note**: Ensure port **`8765`** is allowed through Windows Firewall for Inbound TCP connections on the Local Network (LAN).
4. Note down the Central Server's IPv4 address:
   - Open Command Prompt (`cmd`) on the Server PC.
   - Run `ipconfig` and copy the **IPv4 Address** (e.g., `192.168.1.50`).

#### Method B: Running from Source
```bash
python main.py --server-only --port 8765
```

---

### 💻 2. Client Workstation Setup (إعداد أجهزة الموظفين والإدارة)

Each employee, admin, COO, or superadmin PC runs the `DeskApp` GUI client connected to the Central Server IP.

1. Copy the `dist/DeskApp/` directory to the Client PC.
2. Double-click **`DeskApp.exe`** (or `Launch_DeskApp.bat`).
3. On the **Login Screen**:
   - Enter your **Username / User ID** and **Password**.
   - Enter the **Central Server LAN IP** (e.g., `192.168.1.50`).
4. Click **Login**.

> **Note (Offline Mode)**: If the Central Server PC is temporarily offline or unreachable, DeskApp will automatically save all submitted progress logs into the local queue (`client_queue.db`) and display `Disconnected / Offline`. Once the Server comes back online, DeskApp automatically syncs all queued logs without data loss!

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

## Credentials for Testing

You can use the following default demo credentials on the Login screen:

| Username / ID | Password | Role |
| :--- | :--- | :--- |
| **`1001`** | `1234` | Employee |
| **`admin`** | `admin` | Admin |
| **`coo`** | `coo` | COO |
| **`superadmin`** | `superadmin` | Super Admin |

---

## Development Setup (Running from Source)

### Prerequisites
- Python 3.10 or higher.

### 1. Clone & Set Up
```bash
git clone https://github.com/AbdelrahmanGamal236/Sprints_DeskApp.git
cd Sprints_DeskApp

python -m venv venv
venv\Scripts\activate
pip install PySide6 qasync websockets openpyxl pytest
```

### 2. Run GUI Client
```bash
python main.py
```

### 3. Build Executable
```bash
pyinstaller DeskApp.spec --noconfirm
```

### 4. Run Automated Test Suite
```bash
python -m pytest
```

---

## Credits

Developed by **Eng. Abdelrahman Gamal & Eng. Tolimy**.
