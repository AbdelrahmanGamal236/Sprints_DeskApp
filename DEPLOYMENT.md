# DeskApp Deployment Guide

This guide is for the IT person who installs DeskApp. You don't need to know programming.

DeskApp has two parts:

| Part | Runs on | Program |
|---|---|---|
| **Central Server** | One PC that stays on during working hours | `DeskAppServer.exe` (or `Launch_Server_Daemon.bat`) |
| **Client** | Every PC where someone logs work or manages | `DeskApp.exe` (or `Launch_DeskApp.bat`) |

Both programs are in the same folder: `DeskApp`. No PC needs internet access, and no PC needs Python installed. All PCs only need to be on the same local network (LAN).

> **Upgrading from an older DeskApp?** Install the new version on the server **and on every client at the same time**. An old client can't connect to a new server; it shows a "version does not match" message.

---

## 1. Prepare the Central Server PC

1. Choose a PC that is switched on whenever people use DeskApp. A desktop that is never put to sleep is best.
2. Copy the whole `DeskApp` folder to a fixed place, for example `C:\DeskApp`.
   - Do **not** put it under `C:\Program Files` (Windows protects that folder). If you do, DeskApp stores its data in `C:\ProgramData\DeskApp\data` instead.
3. Turn off sleep: **Settings > System > Power > Screen and sleep > When plugged in, put my device to sleep: Never**.

### 1.1 Fill in the list of Heads (optional, first start only)

DeskApp can create the Head accounts automatically from a file.

1. In `C:\DeskApp`, create a folder named `data` if it doesn't exist yet.
2. Copy `seed_heads.example.json` into `C:\DeskApp\data\` and rename it to **`seed_heads.json`**.
3. Open it with Notepad. Write one line per Head:

```json
[
  {"user_id": "4003", "full_name": "Islam Aki", "discipline_id": "URB"},
  {"user_id": "4007", "full_name": "Karim Ashraf", "discipline_id": "STR"}
]
```

- `user_id` is the person's fingerprint ID. It is their login, and also their first password.
- `discipline_id` must be one of these codes: `URB` (Urban), `STR` (Structure), `INT` (Interior), `ARC` (Architectural), `BIM`, `MEC` (Mechanical), `ELE` (Electrical), `AI`, `QC`, `Infrastructure`.
- Keep the commas and quotes exactly as shown. A line with an unknown discipline, a duplicate ID or a placeholder such as `<ID>` is skipped and written to the log.
- Running the server again never changes or deletes existing accounts, so it is safe to add more lines later.

Heads can also be created later in the app by the Admin.

### 1.2 Start the server for the first time

Double-click **`Launch_Server_Daemon.bat`** in `C:\DeskApp`. A black console window opens and shows something like:

```
======================================================================
 ONE-TIME LOGIN CREDENTIALS (write these down now)
======================================================================
   User ID: superadmin    Temporary password: Xy7pQ2mK9wRt4s
```

- **Write this password down.** It is shown only on the first start.
- A copy is saved in `C:\DeskApp\data\FIRST_RUN_CREDENTIALS.txt`. **Delete that file** once the Super Admin has logged in and chosen a new password.
- Keep the console window open (you can minimize it). Closing it stops the server.

If the window says **"Port 8765 is already in use"**, the server is already running (maybe in another window), or another program uses that port.

### 1.3 Start the server automatically when Windows starts (recommended)

1. Press **Win + R**, type `taskschd.msc` and press Enter.
2. Click **Create Task...** and set:
   - **General**: name `DeskApp Central Server`. Select **Run only when user is logged on**, so the console window stays visible.
   - **Triggers**: **New... > At log on** (of the user who stays logged in on this PC).
   - **Actions**: **New... > Start a program**. Program: `C:\DeskApp\DeskAppServer.exe`. Start in: `C:\DeskApp`.
   - **Settings**: untick "Stop the task if it runs longer than...".
3. Click OK, then log off and on again to check that the console window appears.

---

## 2. Find the server's IP address

On the server PC:

1. Press **Win + R**, type `cmd` and press Enter.
2. Type `ipconfig` and press Enter.
3. Under your network adapter (Ethernet or Wi-Fi), find **IPv4 Address**, for example `192.168.1.50`.

Give this address to everyone. They type it in the login window once, and DeskApp remembers it.

> Ask your network admin to give the server a **fixed (reserved) IP address**. If it changes, every client has to type the new address.

---

## 3. Allow port 8765 through the Windows Firewall (server PC)

Clients connect to the server on **TCP port 8765**. On the **server PC**:

**Option A (easier):** open **Command Prompt as Administrator** (Start, type `cmd`, right-click, **Run as administrator**) and paste:

```
netsh advfirewall firewall add rule name="DeskApp Central Server" dir=in action=allow protocol=TCP localport=8765 profile=domain,private
```

**Option B:** **Windows Defender Firewall > Advanced settings > Inbound Rules > New Rule... > Port > TCP, 8765 > Allow the connection > tick Domain and Private > name it "DeskApp Central Server"**.

The first time `DeskAppServer.exe` runs, Windows may also ask whether to allow it on networks. Allow **Private networks**.

---

## 4. Install the clients

On each user PC:

1. Copy the whole `DeskApp` folder to, for example, `C:\DeskApp`. The same folder works for both clients and the server.
2. Create a desktop shortcut: right-click `C:\DeskApp\DeskApp.exe` > **Send to > Desktop (create shortcut)**.
3. Double-click the shortcut. The login window opens.

Clients don't need a firewall rule; they only make outgoing connections.

---

## 5. First login (every user)

1. Enter:
   - **User Name / ID**: for a Head, the fingerprint ID. For the first Super Admin: `superadmin`.
   - **Password**: for a new Head, the same as the ID. For the first Super Admin: the temporary password from step 1.2.
   - **Central Server LAN IP**: the address from step 2. It is remembered for next time.
2. DeskApp asks for a **new password**. It must have at least 8 characters (the Super Admin can change this minimum) and must not be the same as the ID.
3. The user's workspace opens.

**Suggested order:**

1. **Super Admin** logs in, sets a new password, and creates the **Admin** and **COO** accounts (tab "Master Accounts & Roles"). Their first password is their user ID.
2. **Admin** creates projects and tasks, and any Heads that weren't in `seed_heads.json`.
3. **Heads** log in and start logging work.

**Forgotten password:** the Admin (for Heads) or the Super Admin (for anyone) clicks **Reset Pass**. The password becomes the user ID again, and the user must choose a new one at their next login.

---

## 6. Backups and restore

### Automatic backups

While the server runs, it makes a backup of the database:

- when it starts, if there is no backup for today yet, and
- every day at the **daily backup time** (default `02:00`).

Backups are saved in `C:\DeskApp\data\backups\` as `central_app_YYYYMMDD_HHMMSS.db`. Every copy is checked after it is made. Only the newest **30** are kept.

The Super Admin can change the backup time and the number of copies in **System Settings**. That tab also shows the latest backup.

**Strongly recommended:** once a week, copy the `data\backups` folder to a USB drive or a second PC, so you still have the data if the server's disk fails.

### Restore a backup

1. **Stop the server**: close the server console window and make sure no `DeskAppServer.exe` is left running in Task Manager.
2. Open **Command Prompt** in `C:\DeskApp`. In File Explorer, click the address bar, type `cmd` and press Enter.
3. Run (choose the backup file you want):

```
DeskAppServer.exe --restore data\backups\central_app_20261012_020000.db
```

4. Type `YES` when asked.
   - Before replacing anything, the current database is saved as `data\backups\central_app_pre_restore_<date>.db`, so a restore can be undone.
   - A damaged backup file is refused.
   - The restore is refused while the server is running.
5. Start the server again with `Launch_Server_Daemon.bat`.

### What to back up when moving the server to a new PC

Stop the server and copy the whole `C:\DeskApp\data` folder to the new PC (into `C:\DeskApp\data`). Then follow steps 1, 3 and 2 on the new PC, and give everyone the new IP address.

---

## 7. Where things are

| What | Where (server PC) |
|---|---|
| Central database | `C:\DeskApp\data\central_app.db` (plus `-wal`/`-shm` files while running; never delete them while the server runs) |
| Backups | `C:\DeskApp\data\backups\` |
| Server log | `C:\DeskApp\data\logs\server.log` (older logs: `server.log.1`...`.5`) |
| Head list for first start | `C:\DeskApp\data\seed_heads.json` |
| One-time password | `C:\DeskApp\data\FIRST_RUN_CREDENTIALS.txt` (delete after first login) |

| What | Where (client PC) |
|---|---|
| Unsent work (offline queue) | `C:\DeskApp\data\client_queue.db` (never delete it while it has unsent items) |
| Client log | `C:\DeskApp\data\logs\client.log` |

To use another data folder, start either program with `--data-dir D:\DeskAppData`.

---

## 8. Troubleshooting

**"Cannot reach Central Server at ..." on login**
1. Is the server console window open on the server PC? If not, start `Launch_Server_Daemon.bat`.
2. Is the IP address right? Check `ipconfig` on the server (step 2). The address may have changed.
3. On the client PC, open Command Prompt and run `ping 192.168.1.50` (use your server's address). If that fails, it's a network problem: cable, Wi-Fi, or a different network.
4. Check the firewall rule on the server (step 3). Test from the client in PowerShell: `Test-NetConnection 192.168.1.50 -Port 8765` should show `TcpTestSucceeded : True`.

**Red bar "Not connected to the Central Server - reconnecting automatically"**
The network or the server went away while someone was working. Heads can keep logging: their work is saved on their PC and sent automatically when the connection returns. The top-right badge shows how many items are waiting. Admin/COO changes can't be saved until the connection is back.

**A Head's items stay "queued" and never send**
- Check that the red bar has gone (connection is back). Items are retried automatically every 30 seconds.
- If the Head logged out, the items are sent the next time **that same Head** logs in on that PC.
- Look in `data\logs\client.log` on that PC for lines containing `Sync paused`.

**"Rejected Items (n)" button on a Head's screen**
The server refused those items, for example because the task was deleted or hidden, or the dates were invalid. Click the button to see the reason, then **Retry** (after the Admin fixes the cause) or **Discard**.

**"This DeskApp version does not match the Central Server"**
The client and server are different versions. Copy the same `DeskApp` folder to both.

**"Too many failed attempts. Try again in N seconds."**
Five wrong passwords lock that user ID for one minute. Wait, or ask the Admin to reset the password.

**"Your session was ended by an administrator"**
The user's password was reset. They log in with their user ID as the password and choose a new one.

**The server window closed by itself**
Open `data\logs\server.log` and look at the last lines. Restart with `Launch_Server_Daemon.bat`. If it keeps failing, restore the latest backup (section 6).

**Lost the Super Admin password and there is no other Super Admin**
1. Stop the server (close its console window).
2. Open Command Prompt in `C:\DeskApp` and run `DeskAppServer.exe --reset-superadmin`.
3. It prints a new one-time password for `superadmin`. Start the server again and log in with it.

When asking for help, send `data\logs\server.log` (from the server) and `data\logs\client.log` (from the affected PC).
