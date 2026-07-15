# ChromePad

Turn your phone into a **mouse + keyboard** for your **KDE Plasma / Wayland** PC —
**no app to install**. The phone just opens a web page served by the PC, in its
browser, on the same Wi-Fi.

a text field on the PC.

> Built for **KDE Plasma 6 on Wayland** (developed and tested on Arch Linux).
> Other desktops and X11 sessions are out of scope — see [Limitations](#limitations).

## Who it's for

- **KDE Plasma users on Wayland** who want to drive their PC from a phone on the
  same Wi-Fi — from the couch, bed, or across the room. Think media PC / HTPC, a
  screen wired to the TV, reading, casual browsing, or advancing slides.
- **Any phone** works — Android or iOS — because it's just a web page in the
  browser. Nothing to install on the phone.
- **Requirements:** KDE Plasma on Wayland, Python 3, and access to `/dev/uinput`.
  See [Requirements](#requirements).

Not aimed at: pixel-precise work (gaming, design) — it's a remote pointer over
Wi-Fi — or non-KDE desktops.

## Features

- **Pointer** — joystick that appears under your finger (tilt = cursor velocity)
  or a **trackpad** mode (direct movement). Switchable in Settings.
- **Clicks** — one-finger tap = left, two-finger tap = right, double-tap-and-hold
  = drag.
- **Scroll** strip (right) and **Volume** strip (left, tap the speaker to mute) —
  volume uses media keys, so KDE shows its native OSD.
- **Keyboard** — when an editable field gains focus on the PC (via AT-SPI) the
  phone's native keyboard opens. Manual keyboard button as fallback.
- **Send to PC** — push text/links from the phone to the PC clipboard (and
  optionally paste).
- **Token in the QR** — the WebSocket only accepts the device that scanned the
  code, so a stray phone on the LAN can't grab your mouse. New token per run.
- **Live latency** readout, auto-reconnect, enlarged cursor while connected,
  persisted sensitivity, haptics on click.

## Requirements

- KDE Plasma on Wayland, Python 3.
- Access to `/dev/uinput` (virtual mouse/keyboard) — see the udev rule below.
- `wl-clipboard` for typing text.
- Optional: `python-gobject` + `at-spi2-core` for the automatic keyboard popup.
  Without them ChromePad still runs; use the keyboard button instead.

On Arch:

```bash
# /dev/uinput without root (uaccess = ACL for the logged-in user, no re-login)
sudo cp udev/99-chromepad-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

sudo pacman -S wl-clipboard
sudo pacman -S python-gobject at-spi2-core   # optional, auto keyboard
```

## Run

```bash
./run.sh                 # creates the venv, installs deps, starts on port 8000
```

A QR code and URL appear in the terminal — scan it from your phone's browser
(same Wi-Fi). The URL contains the access token, so **scan it rather than typing
the IP by hand**. Options: `--port <n>`, `--host <ip>` (useful if IP detection
picks a VPN interface). `Ctrl+C` restores the cursor and quits.

**On a VPN?** ChromePad already skips VPN interfaces when detecting the LAN IP. If
the phone still can't reach the PC, allow the local subnet in your VPN (e.g.
NordVPN: `nordvpn allowlist add subnet 192.168.1.0/24`) so LAN replies leave the
tunnel.

## Usage

| Gesture / control                     | Action                     |
|---------------------------------------|----------------------------|
| Finger drag on the pad                | Move the cursor            |
| One-finger tap                        | Left click                 |
| Two-finger tap                        | Right click                |
| Double-tap then hold + move           | Drag                       |
| Right strip                           | Scroll                     |
| Left strip drag / tap speaker         | Volume / mute              |
| Top bar buttons                       | Keyboard · Send to PC · Settings |

## Autostart (optional)

```bash
mkdir -p ~/.config/systemd/user
sed "s|@DIR@|$PWD|g" systemd/chromepad.service > ~/.config/systemd/user/chromepad.service
systemctl --user daemon-reload
systemctl --user enable --now chromepad.service
journalctl --user -u chromepad -n 40      # read the current QR / token
```

## Architecture

```
server/  app.py (aiohttp HTTP+WebSocket, token) · mouse.py (uinput)
         keyboard.py (clipboard + Ctrl+V) · cursor.py · atspi_watch.py · netinfo.py
web/     index.html · style.css · app.js   (vanilla, no framework)
udev/ · systemd/                            uinput rule · optional unit
```

WebSocket messages are compact JSON (`m` move, `c` click, `w` wheel, `kt` text,
`vol`/`mute`, `clip`, `ping`, …).

## Limitations

- **KDE Wayland only.** KWin doesn't implement the `virtual_keyboard` protocol
  that `wtype` needs, so text is typed via clipboard + Ctrl+V (layout- and
  accent-safe; the clipboard is saved and restored). In a terminal, paste is
  Ctrl+Shift+V, so typing may not land there. X11 and other desktops are not
  supported.
- **AT-SPI** doesn't cover every app; use the manual keyboard button then.
- **The token is not encryption.** Traffic is plain HTTP on your LAN — fine for a
  home network, not for a shared or public one.

## License

MIT
