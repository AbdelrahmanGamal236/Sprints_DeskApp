"""Shared helpers for protocol-level tests: a real server on a random port and raw/real clients."""
import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import websockets

from app.core.config import ROLE_HEAD, ROLE_ADMIN, ROLE_COO, ROLE_SUPER_ADMIN
from app.network import protocol as P
from app.network.server import CentralWebSocketServer

PASSWORD = "Str0ngPass!"

# user_id -> (role, discipline)
USERS = {
    "sa": (ROLE_SUPER_ADMIN, None),
    "adm": (ROLE_ADMIN, None),
    "coo1": (ROLE_COO, None),
    "h_urb": (ROLE_HEAD, "URB"),
    "h_urb2": (ROLE_HEAD, "URB"),
    "h_str": (ROLE_HEAD, "STR"),
    "h_new": (ROLE_HEAD, "STR"),  # keeps must_change_password = 1
}


async def start_server(**kwargs) -> CentralWebSocketServer:
    tmp = Path(tempfile.mkdtemp(prefix="deskapp_srv_"))
    server = CentralWebSocketServer(host="127.0.0.1", port=0, db_path=tmp / "central.db", **kwargs)
    db = server.db
    for uid, (role, disc) in USERS.items():
        db.create_user(ROLE_SUPER_ADMIN, uid, f"User {uid}", role, disc)
        if uid != "h_new":
            db.change_password(uid, PASSWORD, require_old=False)
    db.add_project("P1", "Project One")
    db.add_project("P2", "Project Two")
    db.add_task("P1", "T-URB", "Urban task", "URB")
    db.add_task("P1", "T-STR", "Structure task", "STR")
    db.add_task("P2", "T-URB2", "Urban task 2", "URB")
    await server.start_background()
    return server


class RawClient:
    """Minimal protocol client used to probe the server exactly like a hostile LAN host could."""
    def __init__(self, port: int):
        self.port = port
        self.ws = None
        self.events = []

    async def connect(self):
        self.ws = await websockets.connect(f"ws://127.0.0.1:{self.port}", max_size=P.MAX_FRAME_BYTES)
        return self

    async def send_raw(self, text: str):
        await self.ws.send(text)

    async def req(self, action: str, payload=None, timeout: float = 10.0) -> dict:
        msg_id = uuid.uuid4().hex
        await self.ws.send(json.dumps({"action": action, "payload": payload if payload is not None else {}, "msg_id": msg_id}))
        return await self.wait_for(lambda d: d.get("msg_id") == msg_id, timeout)

    async def wait_for(self, predicate, timeout: float = 10.0) -> dict:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            left = end - loop.time()
            if left <= 0:
                raise TimeoutError("no matching message")
            try:
                data = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=left))
            except asyncio.TimeoutError:  # distinct from builtin TimeoutError on Python 3.10
                raise TimeoutError("no matching message")
            if predicate(data):
                return data
            self.events.append(data)

    async def login(self, user_id: str, password: str = PASSWORD) -> dict:
        return await self.req("LOGIN", {"user_id": user_id, "password": password, "protocol": P.PROTOCOL_VERSION})

    async def close(self):
        if self.ws:
            await self.ws.close()


async def raw_login(port: int, user_id: str, password: str = PASSWORD) -> RawClient:
    c = await RawClient(port).connect()
    r = await c.login(user_id, password)
    assert r["ok"], r
    return c


class CuttableProxy:
    """TCP proxy between client and server whose link can be cut and restored (simulates a LAN outage)."""
    def __init__(self, target_port: int):
        self.target_port = target_port
        self.port = None
        self._server = None
        self._conns = set()
        self.up = True

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def _handle(self, reader, writer):
        if not self.up:
            writer.close()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self.target_port)
        except OSError:
            writer.close()
            return
        pair = (writer, up_writer)
        self._conns.add(pair)

        async def pipe(r, w):
            try:
                while True:
                    data = await r.read(65536)
                    if not data:
                        break
                    w.write(data)
                    await w.drain()
            except Exception:
                pass
            finally:
                try:
                    w.close()
                except Exception:
                    pass

        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
        self._conns.discard(pair)

    def cut(self):
        self.up = False
        for a, b in list(self._conns):
            for w in (a, b):
                try:
                    w.transport.abort()
                except Exception:
                    pass
        self._conns.clear()

    def restore(self):
        self.up = True

    async def stop(self):
        self.cut()
        self._server.close()
        await self._server.wait_closed()


async def wait_until(predicate, timeout: float = 15.0, interval: float = 0.05):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()
