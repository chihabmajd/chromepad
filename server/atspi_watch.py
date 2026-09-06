"""AT-SPI focus watcher: editable-widget focus opens the phone keyboard.

python-gobject and at-spi2-core may be absent, so the import is guarded and the
watcher stays off, falling back to the manual keyboard button. AT-SPI does not
cover every app. Callbacks run on a GLib thread and must be thread-safe.
"""

from __future__ import annotations

import threading
from typing import Callable

try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    _IMPORT_ERROR = None
except Exception as exc:                    # missing python-gobject / typelib
    Atspi = None
    _IMPORT_ERROR = exc

_EDITABLE_ROLES = frozenset()
if Atspi is not None:
    _EDITABLE_ROLES = frozenset({
        Atspi.Role.ENTRY,
        Atspi.Role.TEXT,
        Atspi.Role.PASSWORD_TEXT,
        Atspi.Role.DOCUMENT_TEXT,
        Atspi.Role.DOCUMENT_FRAME,
        Atspi.Role.TERMINAL,
        Atspi.Role.PARAGRAPH,
        Atspi.Role.SPIN_BUTTON,
    })


def _is_editable(source) -> bool:
    try:
        role = source.get_role()
    except Exception:
        return False
    if role in _EDITABLE_ROLES:
        return True
    try:
        return source.get_state_set().contains(Atspi.StateType.EDITABLE)
    except Exception:
        return False


class AtspiFocusWatcher:
    def __init__(self, on_focus_change: Callable[[bool], None]) -> None:
        self._cb = on_focus_change
        self._thread: threading.Thread | None = None
        self._listener = None
        self._last_state = False
        self._started = False

    def _on_event(self, event) -> None:
        try:
            editable = event.detail1 == 1 and _is_editable(event.source)
        except Exception:
            editable = False
        if editable != self._last_state:
            self._last_state = editable
            self._cb(editable)

    def start(self) -> bool:
        if Atspi is None:
            print(f"[at-spi] unavailable ({_IMPORT_ERROR}) — auto keyboard off, "
                  "use the keyboard button (install python-gobject + at-spi2-core)")
            return False
        try:
            if Atspi.init() > 1:
                print("[at-spi] accessibility bus unavailable — auto keyboard off")
                return False
            self._listener = Atspi.EventListener.new(self._on_event)
            self._listener.register("object:state-changed:focused")
        except Exception as exc:
            print(f"[at-spi] init failed: {exc} — auto keyboard off")
            return False
        self._thread = threading.Thread(target=Atspi.event_main, daemon=True)
        self._thread.start()
        self._started = True
        print("[at-spi] focus watcher active")
        return True

    def stop(self) -> None:
        if not self._started:
            return
        try:
            if self._listener is not None:
                self._listener.deregister("object:state-changed:focused")
            Atspi.event_quit()
        except Exception:
            pass
        self._started = False
