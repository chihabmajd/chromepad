"""
Cursor size on KDE Plasma: enlarge on first client, restore on last / on exit.
Reads the current value first, so an unset size goes back to the theme default.
No-op if the Plasma tools are missing.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

_TOOLS = ("kreadconfig6", "kwriteconfig6", "plasma-apply-cursortheme")


class CursorManager:
    def __init__(self, big_size: int = 48) -> None:
        self.big_size = big_size
        self.available = all(shutil.which(t) for t in _TOOLS)
        self._saved: Optional[str] = None
        self._theme = "breeze_cursors"
        self._enlarged = False

    def enlarge(self) -> None:
        if not self.available or self._enlarged:
            return
        self._saved = self._read("cursorSize")
        self._theme = self._read("cursorTheme") or "breeze_cursors"
        self._write(str(self.big_size))
        self._apply(self.big_size)
        self._enlarged = True
        print(f"[cursor] enlarged to {self.big_size} (was: {self._saved or 'default'})")

    def restore(self) -> None:
        if not self.available or not self._enlarged:
            return
        if self._saved is None:
            self._write(None)               # delete key -> theme default
            self._apply(None)
        else:
            self._write(self._saved)
            self._apply(int(self._saved))
        self._enlarged = False
        print("[cursor] size restored")

    def _read(self, key: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["kreadconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", key],
                capture_output=True, text=True, timeout=2).stdout.strip()
            return out or None
        except Exception:
            return None

    def _write(self, size: Optional[str]) -> None:
        args = ["kwriteconfig6", "--file", "kcminputrc", "--group", "Mouse", "--key", "cursorSize"]
        args += ["--delete"] if size is None else [size]
        subprocess.run(args, timeout=2)

    def _apply(self, size: Optional[int]) -> None:
        args = ["plasma-apply-cursortheme", self._theme]
        if size is not None:
            args += ["--size", str(size)]
        subprocess.run(args, capture_output=True, timeout=5)
