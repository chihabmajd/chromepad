# ChromePad

Turn a phone into a mouse and keyboard for a KDE Plasma / Wayland PC. Nothing to install
on the phone: it opens a web page served by the PC, over the local Wi-Fi.

Developed and tested on Arch Linux with KDE Plasma 6 on Wayland. X11 and other desktops
are out of scope, see [Limitations](#limitations).

## Features

- Pointer: a joystick that appears under your finger (tilt sets cursor velocity), or a
  trackpad mode with direct movement.
- Clicks: one-finger tap for left, two-finger tap for right, double-tap-and-hold to drag.
- Scroll strip on the right, volume strip on the left. Volume uses media keys, so KDE
  shows its native OSD.
- Keyboard: when an editable field gains focus on the PC, detected via AT-SPI, the
  phone's keyboard opens. A manual button is the fallback.
- Send to PC: push text or links from the phone to the PC clipboard.
- The access token is embedded in the QR code, so only the device that scanned it can
  connect. It is kept across runs (`~/.config/chromepad/token`, mode 600) so a
  home-screen bookmark keeps working; `--new-token` rotates it.
- Live latency readout, auto-reconnect, persisted sensitivity, haptics on click
  (including iPhone, through Safari's native switch control on iOS 18+).
- Trackpad mode has pointer acceleration: slow movements are precise, flicks go far.
- Smooth over flaky Wi-Fi: when the socket backs up, moves are merged instead of
  queued, so a stall does not replay as a lurch. The QR prefers the PC's wired address,
  since Wi-Fi power saving on the PC batches incoming packets.

## Requirements

KDE Plasma on Wayland, Python 3, access to `/dev/uinput`, and `wl-clipboard` for typing
text. `python-gobject` and `at-spi2-core` are optional and enable the automatic keyboard
popup; without them the keyboard button still works.

On Arch:

```bash
sudo cp udev/99-chromepad-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo pacman -S wl-clipboard
sudo pacman -S python-gobject at-spi2-core   # optional
```

The udev rule grants `/dev/uinput` to the logged-in user through `uaccess`, so no
re-login is needed.

## Run

```bash
./run.sh        # creates the venv, installs deps, listens on port 8000
```

A QR code and a URL appear in the terminal. Scan the code from the phone's browser on the
same Wi-Fi rather than typing the IP, since the URL carries the access token. Options:
`--port <n>`, `--host <ip>`, `--new-token`. `Ctrl+C` restores the cursor and quits.

On iPhone, add the page to the Home Screen (Share → Add to Home Screen): it opens full
screen, without Safari's bars or its back-swipe from the left edge.

### On Ethernet

When the PC is wired and its Wi-Fi card is idle, ChromePad turns the card into a
private hotspot (`ChromePad`, WPA2, subnet `10.42.0.0/24`) and prints a second QR code
that the phone camera uses to join it. The phone then reaches the PC directly, whatever
the building network allows, and the hotspot is torn down on exit. The phone is alone on
the PC's own network, and ChromePad listens only on that address, so nothing on the
building network can reach it. The NetworkManager profile exists only while ChromePad
runs; the WPA2 (CCMP) password is generated once and kept in
`~/.config/chromepad/hotspot-password` (mode 600), so the phone rejoins on its own. Force or disable it with
`--hotspot on|off`. With NordVPN connected, allow that subnet once:
`nordvpn allowlist add subnet 10.42.0.0/24`.

Networks that hand out public addresses (campus, enterprise) are detected too; private
addresses are preferred.

ChromePad skips VPN interfaces when detecting the LAN IP. If the phone still cannot reach
the PC, allow the local subnet in the VPN, for example
`nordvpn allowlist add subnet 192.168.1.0/24`.

## Controls

| Gesture | Action |
|---|---|
| Finger drag on the pad | Move the cursor |
| One-finger tap | Left click |
| Two-finger tap | Right click |
| Double-tap then hold and move | Drag |
| Right strip | Scroll |
| Left strip drag, tap speaker | Volume, mute |
| Top bar | Keyboard, Send to PC, Settings |

## Autostart

```bash
mkdir -p ~/.config/systemd/user
sed "s|@DIR@|$PWD|g" systemd/chromepad.service > ~/.config/systemd/user/chromepad.service
systemctl --user daemon-reload
systemctl --user enable --now chromepad.service
journalctl --user -u chromepad -n 40      # current QR and token
```

## Layout

```
server/  app.py (aiohttp HTTP + WebSocket, token), mouse.py (uinput),
         keyboard.py (clipboard + Ctrl+V), cursor.py, atspi_watch.py, netinfo.py
web/     index.html, style.css, app.js   (vanilla, no framework)
udev/, systemd/
```

WebSocket messages are compact JSON: `m` move, `c` click, `w` wheel, `kt` text, `vol`,
`mute`, `clip`, `ping`.

## Limitations

- KDE Wayland only. KWin does not implement the `virtual_keyboard` protocol that `wtype`
  needs, so text is typed through the clipboard and Ctrl+V, which is layout- and
  accent-safe and restores the previous clipboard. Terminals use Ctrl+Shift+V to paste,
  so typing may not land there.
- AT-SPI does not cover every application; use the manual keyboard button in that case.
- The token is not encryption. Traffic is plain HTTP on the LAN, which is fine at home
  and not on a shared network.
- Not suited to pixel-precise work such as gaming or design.

## License

MIT
