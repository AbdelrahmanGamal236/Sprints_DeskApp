import sys
import os
import argparse
import asyncio
import logging
import socket

DEFAULT_WS_PORT = 8765  # duplicated from app.core.config so arguments can be parsed before app modules load


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Offline Progress Logging & Task Management System")
    parser.add_argument("--server-only", action="store_true", help="Run dedicated Central Server headless daemon mode")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Folder for the database, backups and logs (default: 'data' next to the program)")
    parser.add_argument("--restore", type=str, metavar="BACKUP_FILE", default=None,
                        help="Replace the central database with a backup file (stop the server first)")
    parser.add_argument("--reset-superadmin", action="store_true",
                        help="Recovery: give the 'superadmin' account a new one-time password (stop the server first)")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation (with --restore)")
    parser.add_argument("--version", action="store_true", help="Print the DeskApp version and exit")
    parser.add_argument("--standalone", action="store_true",
                        help="Demo: embedded server + client in one process, using a separate data_demo folder")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address for Central Server")
    parser.add_argument("--port", type=int, default=DEFAULT_WS_PORT, help="Port for Central Server")
    parser.add_argument("--server-ip", type=str, default="127.0.0.1", help="Central Server LAN IP")
    return parser.parse_args(argv)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def announce_bootstrap_credentials(server):
    """Print one-time passwords for the Super Admin bootstrap (shown only on the first start)."""
    creds = getattr(server.db, "bootstrap_credentials", [])
    if not creds:
        return
    from app.core.config import DATA_DIR
    lines = ["", "=" * 70, " ONE-TIME LOGIN CREDENTIALS (write these down now)", "=" * 70]
    for uid, pwd in creds:
        lines.append(f"   User ID: {uid:<12}  Temporary password: {pwd}")
    lines += ["", " These accounts must choose a new password at first login.",
              f" A copy was saved to: {DATA_DIR / 'FIRST_RUN_CREDENTIALS.txt'}",
              " Delete that file after you have logged in.", "=" * 70, ""]
    text = "\n".join(lines)
    print(text, flush=True)
    try:
        with open(DATA_DIR / "FIRST_RUN_CREDENTIALS.txt", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as e:
        logging.error("Could not write FIRST_RUN_CREDENTIALS.txt: %s", e)


def run_restore(args) -> int:
    """--restore: put a backup back in place of the central database (server must be stopped)."""
    from pathlib import Path
    from app.core.config import CENTRAL_DB_PATH, BACKUPS_DIR
    from app.services.maintenance import restore_database
    if is_port_in_use(args.port, "127.0.0.1"):
        print(f"\n[ERROR] The Central Server is running (port {args.port} is in use). Stop it first, then restore.\n")
        return 1
    backup = Path(args.restore)
    print(f"\nThis will REPLACE the central database:\n   {CENTRAL_DB_PATH}\nwith the backup:\n   {backup}\n"
          f"The current database is kept as a safety copy in {BACKUPS_DIR}.")
    if not args.yes:
        try:
            answer = input("Type YES to continue: ")
        except EOFError:
            answer = ""
        if answer.strip() != "YES":
            print("Restore cancelled.")
            return 1
    try:
        safety = restore_database(backup, CENTRAL_DB_PATH, BACKUPS_DIR)
    except (OSError, ValueError) as e:
        print(f"\n[ERROR] {e}\n")
        return 1
    logging.info("Database restored from %s (previous database saved as %s)", backup, safety)
    print(f"\nRestore complete. Previous database saved as:\n   {safety}\nYou can start the server again.\n")
    return 0


def run_reset_superadmin(args) -> int:
    if is_port_in_use(args.port, "127.0.0.1"):
        print(f"\n[ERROR] The Central Server is running (port {args.port} is in use). Stop it first.\n")
        return 1
    from app.core.config import CENTRAL_DB_PATH
    from app.database.db_manager import DBManager
    pwd = DBManager(central_db_path=CENTRAL_DB_PATH).emergency_reset_superadmin()
    logging.warning("Super Admin password was reset from the command line")
    print(f"\nUser ID: superadmin   One-time password: {pwd}\n"
          "Log in with it and choose a new password. Start the server again first.\n")
    return 0


def run_server_only(args):
    from app.core.config import APP_VERSION, LOGS_DIR, DATA_DIR
    from app.services.maintenance import setup_logging
    log_file = setup_logging(LOGS_DIR, "server")
    from app.network.server import CentralWebSocketServer
    logging.info("DeskApp %s - starting Central Server on port %d (data folder: %s, log: %s)",
                 APP_VERSION, args.port, DATA_DIR, log_file)
    if is_port_in_use(args.port, "127.0.0.1"):
        logging.error("Port %d is already in use by another process (is the server already running?).", args.port)
        sys.exit(1)

    async def serve():
        server = CentralWebSocketServer(host=args.host, port=args.port, standalone=False)
        announce_bootstrap_credentials(server)
        await server.start()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logging.info("Central Server stopped.")
    except OSError as e:
        logging.error("Could not start Central Server: %s", e)
        sys.exit(1)


class AppController:
    """Drives the GUI: login window -> role workspace -> back to login on logout / expired session."""
    def __init__(self, app, args):
        self.app = app
        self.args = args
        # The controller decides when to exit; windows close and reopen while switching login <-> workspace
        app.setQuitOnLastWindowClosed(False)
        self.login_dialog = None
        self.workspace = None
        self.net_client = None
        self.sync_service = None

    def show_login(self, notice: str = ""):
        from app.ui.login_dialog import LoginDialog
        self.login_dialog = LoginDialog(default_server_ip=self.args.server_ip, port=self.args.port, notice=notice)
        self.login_dialog.logged_in.connect(self.open_workspace)
        self.login_dialog.rejected.connect(self.quit)
        self.login_dialog.show()

    def open_workspace(self, net_client):
        from app.core.config import ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
        from app.services.sync_service import SyncService
        from app.ui.head_workspace import HeadWorkspace
        from app.ui.admin_workspace import AdminWorkspace
        from app.ui.coo_workspace import CooWorkspace
        from app.ui.superadmin_workspace import SuperAdminWorkspace

        try:
            self.login_dialog.rejected.disconnect(self.quit)
        except (RuntimeError, TypeError):
            pass
        self.net_client = net_client
        user = net_client.user
        role = user["role"]
        if role == ROLE_HEAD:
            self.sync_service = SyncService(net_client, user["user_id"])
            ws = HeadWorkspace(user, net_client, self.sync_service)
        elif role == ROLE_ADMIN:
            ws = AdminWorkspace(user, net_client)
        elif role == ROLE_COO:
            ws = CooWorkspace(user, net_client)
        elif role == ROLE_SUPER_ADMIN:
            ws = SuperAdminWorkspace(user, net_client)
        else:
            logging.error("Unknown role '%s'", role)
            self.quit()
            return

        net_client.session_expired.connect(self.on_session_expired)
        orig_close = ws.closeEvent

        def close_event(event):
            orig_close(event)
            if event.isAccepted():
                self.on_workspace_closed()
        ws.closeEvent = close_event
        self.workspace = ws
        ws.show()
        if self.sync_service is not None:
            self.sync_service.schedule_flush()

    def on_session_expired(self, message: str):
        from PySide6.QtWidgets import QMessageBox
        if self.workspace is None:
            return
        QMessageBox.warning(self.workspace, "Session Ended", message)
        self.workspace.logout_requested = True
        self.workspace.close()

    def on_workspace_closed(self):
        from app.network.client import run_async
        ws, self.workspace = self.workspace, None
        if self.sync_service is not None:
            self.sync_service.stop()
            self.sync_service = None
        net, self.net_client = self.net_client, None
        logout = getattr(ws, "logout_requested", False)
        if net is not None:
            run_async(net.logout(), lambda _: None if logout else self.quit(), lambda _: None if logout else self.quit())
        elif not logout:
            self.quit()
        if logout:
            self.show_login()

    def quit(self):
        asyncio.get_event_loop().stop()


def run_gui(args):
    from app.core.config import LOGS_DIR, APP_VERSION
    from app.services.maintenance import setup_logging
    setup_logging(LOGS_DIR, "client")
    logging.info("DeskApp %s client starting", APP_VERSION)
    from PySide6.QtWidgets import QApplication
    from qasync import QEventLoop
    from app.ui.styles import DARK_THEME_QSS

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)
    from app.ui.components import install_smooth_scrolling
    install_smooth_scrolling(app)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    if args.standalone:
        from app.network.server import CentralWebSocketServer
        if not is_port_in_use(args.port, "127.0.0.1"):
            logging.info("Starting embedded demo server on port %d (data_demo folder)...", args.port)
            server = CentralWebSocketServer(host="127.0.0.1", port=args.port, standalone=True)
            loop.run_until_complete(server.start_background())

    controller = AppController(app, args)
    loop.call_soon(controller.show_login)
    with loop:
        loop.run_forever()


def main(argv=None):
    args = parse_args(argv)
    if args.data_dir:
        os.environ["DESKAPP_DATA_DIR"] = os.path.abspath(args.data_dir)
    if args.standalone and not os.environ.get("DESKAPP_DATA_DIR"):
        os.environ["DESKAPP_DEMO"] = "1"
    if args.version:
        from app.core.config import APP_VERSION
        print(f"DeskApp {APP_VERSION}")
        return
    if args.reset_superadmin:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        sys.exit(run_reset_superadmin(args))
    if args.restore:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        sys.exit(run_restore(args))
    if args.server_only:
        run_server_only(args)
    else:
        run_gui(args)


if __name__ == "__main__":
    main()
