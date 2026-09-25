import sys
import argparse
import asyncio
import logging
import socket
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from app.core.config import DEFAULT_WS_PORT, ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
from app.database.db_manager import DBManager
from app.network.server import CentralWebSocketServer
from app.network.client import NetworkClient
from app.services.sync_service import SyncService
from app.ui.styles import DARK_THEME_QSS
from app.ui.login_dialog import LoginDialog
from app.ui.head_workspace import HeadWorkspace
from app.ui.admin_workspace import AdminWorkspace
from app.ui.coo_workspace import CooWorkspace
from app.ui.superadmin_workspace import SuperAdminWorkspace

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

async def run_server_task(host: str = "0.0.0.0", port: int = DEFAULT_WS_PORT):
    server = CentralWebSocketServer(host=host, port=port)
    await server.start()

async def async_main(app, db_manager, args):
    # Automatically start embedded server if local server port is free
    if not is_port_in_use(args.port, "127.0.0.1"):
        logging.info("Starting embedded Central Server task on port %d...", args.port)
        asyncio.create_task(run_server_task("0.0.0.0", args.port))
        await asyncio.sleep(0.1)

    while True:
        # Open Login Dialog
        login_dialog = LoginDialog(db_manager, default_server_ip=args.server_ip)
        if login_dialog.exec() != LoginDialog.Accepted:
            break

        user = login_dialog.authenticated_user
        user_id = user["user_id"]
        role = user["role"]
        server_ip = login_dialog.selected_server_ip

        # Initialize Network Client & Sync Service
        net_client = NetworkClient(user_id=user_id, role=role, server_ip=server_ip, port=args.port)
        sync_service = SyncService(net_client)

        # Start network client background loop in qasync
        net_task = asyncio.create_task(net_client.start())

        # Open workspace based on role
        if role == ROLE_HEAD:
            workspace = HeadWorkspace(user, db_manager, net_client, sync_service)
        elif role == ROLE_ADMIN:
            workspace = AdminWorkspace(user, db_manager, net_client)
        elif role == ROLE_COO:
            workspace = CooWorkspace(user, db_manager, net_client)
        elif role == ROLE_SUPER_ADMIN:
            workspace = SuperAdminWorkspace(user, db_manager, net_client)
        else:
            logging.error(f"Unknown role '{role}'")
            break

        closed_event = asyncio.Event()
        orig_close_event = workspace.closeEvent

        def custom_close_event(event):
            if orig_close_event:
                orig_close_event(event)
            closed_event.set()

        workspace.closeEvent = custom_close_event
        workspace.show()

        # Cleanly wait for workspace window to close without interrupting event loop
        await closed_event.wait()

        net_task.cancel()
        try:
            await net_task
        except asyncio.CancelledError:
            pass

        # If user did NOT click Logout (e.g. closed window), exit app
        if not getattr(workspace, "logout_requested", False):
            break

def main():
    parser = argparse.ArgumentParser(description="Offline Progress Logging & Task Management System")
    parser.add_argument("--server-only", action="store_true", help="Run dedicated Central Server headless mode")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address for Central Server")
    parser.add_argument("--port", type=int, default=DEFAULT_WS_PORT, help="Port for Central Server")
    parser.add_argument("--server-ip", type=str, default="127.0.0.1", help="Central Server LAN IP")
    args = parser.parse_args()

    if args.server_only:
        logging.info("Starting Central Server Headless Daemon on port %d...", args.port)
        if is_port_in_use(args.port, "127.0.0.1"):
            logging.error(f"Port {args.port} is already in use!")
            print(f"\n[ERROR] Port {args.port} is already in use by another running process (or another DeskApp instance).")
            print("Please close any running DeskApp instances before starting the server daemon.\n")
            input("Press Enter to exit...")
            sys.exit(1)
        try:
            asyncio.run(run_server_task(args.host, args.port))
        except KeyboardInterrupt:
            logging.info("Central Server stopped.")
        except OSError as e:
            logging.error(f"Failed to start Central Server: {e}")
            print(f"\n[ERROR] Could not start server: {e}\n")
            input("Press Enter to exit...")
            sys.exit(1)
        sys.exit(0)

    # Launch Desktop Application GUI
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)

    event_loop = QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    db_manager = DBManager()

    try:
        with event_loop:
            event_loop.run_until_complete(async_main(app, db_manager, args))
    except (RuntimeError, SystemExit, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    main()
