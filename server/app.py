#!/usr/bin/env python3
"""
ChromePad server (KDE Plasma / Wayland): serves the web page, receives phone
events over WebSocket and injects them on the PC via uinput.

The QR URL carries a random token (?k=...) that the WebSocket checks, so a
stray device on the LAN cannot take over the mouse. A new token per run.

Phone -> PC (compact JSON):
    {"t":"m","dx":..,"dy":..}  relative move        {"t":"c","b":"l"|"r"}  click
    {"t":"dn"} / {"t":"up"}    left button hold      {"t":"w","d":n}        wheel
    {"t":"kt","v":".."}        type text             {"t":"kb"} / {"t":"ke"} bksp/enter
    {"t":"vol","d":n}          volume +/-            {"t":"mute"}           mute
    {"t":"clip","v":".."}      set PC clipboard      {"t":"clippaste","v":".."} + paste
    {"t":"ping","id":n}        latency ping
PC -> phone:
    {"event":"text_focus","state":bool}  {"event":"welcome","keyboard":bool}
    {"event":"pong","id":n}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import socket
from typing import Optional, Set

from aiohttp import WSMsgType, web

from .atspi_watch import AtspiFocusWatcher
from .cursor import CursorManager
from .keyboard import KeyboardInjector
from .mouse import VirtualMouse
from .netinfo import detect_local_ip, print_qr

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))


@web.middleware
async def no_cache(request: web.Request, handler):
    """Without this the phone can keep a stale app.js and an outdated token scheme."""
    resp = await handler(request)
    if not resp.prepared:                       # skip the live WebSocket
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def check_environment() -> None:
    if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
        print("[warn] not a Wayland session — ChromePad targets KDE Plasma on Wayland")
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        print("[warn] KDE Plasma not detected — cursor resizing may not work")


class ChromePadServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(9)
        self.mouse: Optional[VirtualMouse] = None
        self.keyboard = KeyboardInjector()
        self.cursor = CursorManager(big_size=48)
        self.atspi: Optional[AtspiFocusWatcher] = None
        self.clients: Set[web.WebSocketResponse] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown = asyncio.Event()

    def init_devices(self) -> None:
        try:
            self.mouse = VirtualMouse()
        except PermissionError:
            raise SystemExit(
                "\n[error] Permission denied on /dev/uinput.\n"
                "  Add yourself to the input group and install the udev rule:\n"
                "      sudo usermod -aG input $USER\n"
                "      sudo cp udev/99-chromepad-uinput.rules /etc/udev/rules.d/\n"
                "      sudo udevadm control --reload-rules && sudo udevadm trigger\n"
                "  (then re-login for the group to apply)\n"
            )
        except FileNotFoundError:
            raise SystemExit(
                "\n[error] /dev/uinput not found. Load the module:\n"
                "      sudo modprobe uinput\n"
            )

    async def broadcast(self, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":"))
        dead = []
        for ws in self.clients:
            try:
                await ws.send_str(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def on_focus_change_threadsafe(self, editable: bool) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                self.broadcast({"event": "text_focus", "state": editable})
            )
        )

    async def ws_handler(self, request: web.Request) -> web.StreamResponse:
        if not secrets.compare_digest(request.query.get("k", ""), self.token):
            print("[ws] rejected: bad or missing token (rescan the QR code)")
            return web.Response(status=403, text="forbidden")

        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        # Low latency: disable Nagle so each small move is sent immediately.
        sock = request.transport.get_extra_info("socket") if request.transport else None
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

        first_client = len(self.clients) == 0
        self.clients.add(ws)
        print(f"[ws] client connected ({len(self.clients)} total)")
        if first_client:
            self.cursor.enlarge()

        await ws.send_str(json.dumps(
            {"event": "welcome", "keyboard": self.keyboard.available},
            separators=(",", ":"),
        ))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    if '"ping"' in msg.data:
                        try:
                            pm = json.loads(msg.data)
                        except ValueError:
                            pm = None
                        if pm and pm.get("t") == "ping":
                            await ws.send_str(json.dumps(
                                {"event": "pong", "id": pm.get("id")},
                                separators=(",", ":")))
                            continue
                    self.handle_message(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
            print(f"[ws] client disconnected ({len(self.clients)} left)")
            if not self.clients:
                if self.mouse:
                    self.mouse.left_up()   # release a dangling drag
                self.cursor.restore()
        return ws

    def handle_message(self, raw: str) -> None:
        try:
            m = json.loads(raw)
        except (ValueError, TypeError):
            return
        if self.mouse is None:
            return
        t = m.get("t")
        if t == "m":
            self.mouse.move(m.get("dx", 0), m.get("dy", 0))
        elif t == "c":
            self.mouse.right_click() if m.get("b") == "r" else self.mouse.left_click()
        elif t == "dn":
            self.mouse.left_down()
        elif t == "up":
            self.mouse.left_up()
        elif t == "w":
            self.mouse.scroll(m.get("d", 0))
        elif t == "kt":
            self.keyboard.type_text(m.get("v", ""))
        elif t == "kb":
            self.keyboard.backspace()
        elif t == "ke":
            self.keyboard.enter()
        elif t == "vol":
            self.keyboard.volume_up() if m.get("d", 0) > 0 else self.keyboard.volume_down()
        elif t == "mute":
            self.keyboard.mute()
        elif t == "clip":
            self.keyboard.set_clipboard(m.get("v", ""))
        elif t == "clippaste":
            self.keyboard.paste_clipboard(m.get("v", ""))

    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"))

    def build_app(self) -> web.Application:
        app = web.Application(middlewares=[no_cache])
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_static("/", WEB_DIR, show_index=False)
        return app

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        check_environment()
        self.init_devices()
        self.atspi = AtspiFocusWatcher(self.on_focus_change_threadsafe)
        self.atspi.start()

        runner = web.AppRunner(self.build_app(), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        try:
            await site.start()
        except OSError as exc:
            self.cleanup()
            raise SystemExit(
                f"\n[error] Cannot listen on {self.host}:{self.port} — {exc}\n"
                f"  The port may be in use. Retry with --port <other>.\n"
            )

        self._print_banner()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, self._shutdown.set)
        await self._shutdown.wait()

        print("\n[server] shutting down…")
        await runner.cleanup()
        self.cleanup()

    def _print_banner(self) -> None:
        ip = self.host if self.host not in ("0.0.0.0", "") else detect_local_ip()
        url = f"http://{ip}:{self.port}/?k={self.token}"
        kb = (f"{self.keyboard.label} (ok)" if self.keyboard.can_type
              else f"{self.keyboard.label} -> {self.keyboard.install_hint()}")
        print("\n" + "=" * 52)
        print("  ChromePad — phone -> mouse/keyboard")
        print("=" * 52)
        print(f"  Keyboard  : {kb}")
        print("=" * 52)
        print("  Scan this QR code from Chrome on your phone:\n")
        if ip:
            print_qr(url)
        else:
            print("  [!] Local IP not found — restart with --host <your_lan_ip>")
            print(f"      then open  http://<your_lan_ip>:{self.port}/?k={self.token}\n")
        print("  Ctrl+C to quit.\n", flush=True)   # stdout is block-buffered off a tty

    def cleanup(self) -> None:
        if self.atspi:
            self.atspi.stop()
        self.cursor.restore()
        self.keyboard.close()
        if self.mouse:
            self.mouse.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ChromePad — phone as mouse/keyboard")
    parser.add_argument("--host", default="0.0.0.0", help="listen address")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    args = parser.parse_args()

    server = ChromePadServer(args.host, args.port)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        server.cleanup()


if __name__ == "__main__":
    main()
