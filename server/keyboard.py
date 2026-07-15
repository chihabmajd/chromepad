"""
Keyboard / media injection for KDE Plasma on Wayland.

KWin does not implement the virtual-keyboard protocol, so text is typed by
putting it on the clipboard (wl-copy) and sending Ctrl+V through a uinput
device — layout- and accent-safe. The clipboard is restored once typing stops.
Keys (backspace/enter/volume/mute) go straight through uinput.
Everything runs on a worker thread (non-blocking, serialized).
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from typing import Optional

from evdev import UInput, ecodes as e

_UNSET = object()

_CAPS = {e.EV_KEY: [e.KEY_LEFTCTRL, e.KEY_V, e.KEY_BACKSPACE,
                    e.KEY_ENTER, e.KEY_TAB,
                    e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN, e.KEY_MUTE]}


class KeyboardInjector:
    def __init__(self) -> None:
        self.can_type = False          # clipboard + Ctrl+V usable
        self._ui: Optional[UInput] = None
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._saved = _UNSET

        try:
            self._ui = UInput(_CAPS, name="ChromePad Virtual Keyboard", version=1)
        except Exception as exc:
            print(f"[keyboard] uinput device unavailable: {exc}")
        self.can_type = bool(self._ui is not None and shutil.which("wl-copy"))

        if self.available:
            threading.Thread(target=self._worker, daemon=True).start()

    @property
    def available(self) -> bool:
        return self._ui is not None

    @property
    def label(self) -> str:
        if self.can_type:
            return "clipboard"
        return "keys only" if self._ui is not None else "unavailable"

    def install_hint(self) -> str:
        return "install wl-clipboard"

    # public, non-blocking
    def type_text(self, text: str) -> None:
        if text and self.can_type:
            self._q.put(("text", text))

    def backspace(self) -> None:
        self._put("bs")

    def enter(self) -> None:
        self._put("enter")

    def volume_up(self) -> None:
        self._put("volup")

    def volume_down(self) -> None:
        self._put("voldown")

    def mute(self) -> None:
        self._put("mute")

    def set_clipboard(self, text: str) -> None:
        if text and self.can_type:
            self._q.put(("clip", text))

    def paste_clipboard(self, text: str) -> None:
        if text and self.can_type:
            self._q.put(("clippaste", text))

    def _put(self, kind: str) -> None:
        if self.available:
            self._q.put((kind, None))

    def _worker(self) -> None:
        while True:
            try:
                kind, payload = self._q.get(timeout=1.0)
            except queue.Empty:
                self._restore_clip()      # idle: give the clipboard back
                continue
            try:
                if kind == "text":
                    self._do_text(payload)
                elif kind == "bs":
                    self._tap(e.KEY_BACKSPACE)
                elif kind == "enter":
                    self._tap(e.KEY_ENTER)
                elif kind == "volup":
                    self._tap(e.KEY_VOLUMEUP)
                elif kind == "voldown":
                    self._tap(e.KEY_VOLUMEDOWN)
                elif kind == "mute":
                    self._tap(e.KEY_MUTE)
                elif kind == "clip":
                    self._do_clip(payload, paste=False)
                elif kind == "clippaste":
                    self._do_clip(payload, paste=True)
            except Exception as exc:
                print(f"[keyboard] injection error: {exc}")

    def _do_text(self, text: str) -> None:
        if self._saved is _UNSET:                 # save once per burst
            self._saved = self._clip_get()
        self._clip_set(text)
        time.sleep(0.015)
        self._tap(e.KEY_V, mods=[e.KEY_LEFTCTRL])
        time.sleep(0.010)

    def _do_clip(self, text: str, paste: bool) -> None:
        self._saved = _UNSET                      # deliberate: keep this content
        self._clip_set(text)
        if paste:
            time.sleep(0.015)
            self._tap(e.KEY_V, mods=[e.KEY_LEFTCTRL])

    def _clip_get(self) -> Optional[str]:
        try:
            r = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=1)
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", "replace")
        except Exception:
            pass
        return None

    def _clip_set(self, text: str) -> None:
        subprocess.run(["wl-copy"], input=text.encode("utf-8"), timeout=1)

    def _restore_clip(self) -> None:
        if self._saved is _UNSET:
            return
        try:
            if self._saved is None:
                subprocess.run(["wl-copy", "--clear"], timeout=1)
            else:
                self._clip_set(self._saved)
        except Exception:
            pass
        self._saved = _UNSET

    def _tap(self, key: int, mods: Optional[list[int]] = None) -> None:
        if self._ui is None:
            return
        mods = mods or []
        for m in mods:
            self._ui.write(e.EV_KEY, m, 1)
        self._ui.write(e.EV_KEY, key, 1)
        self._ui.syn()
        self._ui.write(e.EV_KEY, key, 0)
        for m in reversed(mods):
            self._ui.write(e.EV_KEY, m, 0)
        self._ui.syn()

    def close(self) -> None:
        self._restore_clip()
        if self._ui is not None:
            try:
                self._ui.close()
            except Exception:
                pass
