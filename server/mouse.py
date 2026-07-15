"""Virtual mouse injected through /dev/uinput (evdev)."""

from __future__ import annotations

from evdev import UInput, ecodes as e


class VirtualMouse:
    _CAP = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
    }

    def __init__(self) -> None:
        self.ui = UInput(self._CAP, name="ChromePad Virtual Mouse", version=0x1)

    def move(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        if dx:
            self.ui.write(e.EV_REL, e.REL_X, int(dx))
        if dy:
            self.ui.write(e.EV_REL, e.REL_Y, int(dy))
        self.ui.syn()

    def scroll(self, amount: int) -> None:
        if amount == 0:
            return
        self.ui.write(e.EV_REL, e.REL_WHEEL, int(amount))
        self.ui.syn()

    def button(self, code: int, pressed: bool) -> None:
        self.ui.write(e.EV_KEY, code, 1 if pressed else 0)
        self.ui.syn()

    def click(self, code: int) -> None:
        self.button(code, True)
        self.button(code, False)

    def left_click(self) -> None:
        self.click(e.BTN_LEFT)

    def right_click(self) -> None:
        self.click(e.BTN_RIGHT)

    def left_down(self) -> None:
        self.button(e.BTN_LEFT, True)

    def left_up(self) -> None:
        self.button(e.BTN_LEFT, False)

    def close(self) -> None:
        try:
            self.ui.write(e.EV_KEY, e.BTN_LEFT, 0)  # release a dangling drag
            self.ui.syn()
        except Exception:
            pass
        try:
            self.ui.close()
        except Exception:
            pass
