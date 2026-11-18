"""Private Wi-Fi hotspot for when the PC is on Ethernet.

On a wired connection the Wi-Fi card is idle, and the phone usually cannot reach
the PC through the building's network (client isolation, separate subnets, VPN
policy routing). So the PC's own Wi-Fi card becomes an access point that only
the phone joins: PC and phone then share a private subnet (10.42.0.0/24, the
NetworkManager "shared" default) and nothing in between can block them.

The NetworkManager profile only exists while ChromePad runs (created on start,
deleted on stop), so nothing shows up in the network list otherwise. The password
is generated once and kept in ~/.config/chromepad (mode 600), so the phone, which
remembers the network, rejoins by itself next time.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Optional

CON_NAME = "ChromePad-Hotspot"
SSID = "ChromePad"
SUBNET = "10.42.0.0/24"
PSK_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "chromepad" / "hotspot-password"


def _nmcli(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)


def _devices() -> list[tuple[str, str, str]]:
    """(device, type, state) for every device NetworkManager knows."""
    out = _nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device").stdout
    return [tuple(line.split(":")[:3]) for line in out.splitlines() if line.count(":") >= 2]


def _wifi_device() -> Optional[str]:
    return next((d for d, t, _ in _devices() if t == "wifi"), None)


def wired_and_wifi_idle() -> bool:
    """True when Ethernet is up and the Wi-Fi card is free to become a hotspot."""
    devs = _devices()
    wired = any(t == "ethernet" and s == "connected" for _, t, s in devs)
    wifi_free = any(t == "wifi" and s in ("disconnected", "unavailable") for _, t, s in devs)
    return wired and wifi_free


def _password() -> str:
    try:
        psk = PSK_FILE.read_text().strip()
        if len(psk) >= 8:
            return psk
    except OSError:
        pass
    psk = secrets.token_urlsafe(12)          # ~96 bits, WPA2 needs >= 8 chars
    PSK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(PSK_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(psk + "\n")
    return psk


def _create_profile(ifname: str, psk: str) -> None:
    _nmcli("connection", "delete", CON_NAME)          # stale one from a crash
    res = _nmcli(
        "connection", "add", "type", "wifi", "ifname", ifname, "con-name", CON_NAME,
        "autoconnect", "no", "ssid", SSID,
        "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
        "ipv4.method", "shared", "ipv6.method", "disabled",
        "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk,
        "wifi-sec.proto", "rsn", "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
        # only the logged-in user can see or use the profile
        "connection.permissions", f"user:{os.environ.get('USER', '')}",
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "nmcli connection add failed")


def start() -> tuple[str, str]:
    """Bring the hotspot up; returns (ssid, password)."""
    if not shutil.which("nmcli"):
        raise RuntimeError("nmcli not found (NetworkManager is required)")
    ifname = _wifi_device()
    if not ifname:
        raise RuntimeError("no Wi-Fi device found")
    psk = _password()
    _create_profile(ifname, psk)
    res = _nmcli("connection", "up", CON_NAME, timeout=40)
    if res.returncode != 0:
        stop()
        raise RuntimeError(res.stderr.strip() or "could not start the hotspot")
    return SSID, psk


def address() -> Optional[str]:
    """The PC's address on the hotspot (10.42.0.1 by NetworkManager default)."""
    ifname = _wifi_device()
    out = _nmcli("-g", "IP4.ADDRESS", "device", "show", ifname or "").stdout
    first = out.strip().split("|")[0].strip()
    return first.split("/")[0] if first else None


def stop() -> None:
    """Take the hotspot down and remove the profile entirely."""
    try:
        _nmcli("connection", "delete", CON_NAME)
    except Exception:
        pass


def wifi_qr_payload(ssid: str, password: str) -> str:
    """Standard Wi-Fi QR format: phone cameras offer to join directly."""
    esc = lambda s: "".join("\\" + c if c in '\\;,:"' else c for c in s)  # noqa: E731
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def vpn_blocks_subnet() -> Optional[str]:
    """If NordVPN is connected and the hotspot subnet is not allowlisted, replies to
    the phone would be routed into the tunnel. Returns the fix command, else None."""
    if not shutil.which("nordvpn"):
        return None
    try:
        status = subprocess.run(["nordvpn", "status"], capture_output=True, text=True,
                                timeout=5).stdout
        if "Connected" not in status:
            return None
        settings = subprocess.run(["nordvpn", "settings"], capture_output=True, text=True,
                                  timeout=5).stdout
    except Exception:
        return None
    if SUBNET in settings or "10.0.0.0/8" in settings:
        return None
    return f"nordvpn allowlist add subnet {SUBNET}"


def route_dev(ip: str) -> Optional[str]:
    try:
        out = subprocess.run(["ip", "-j", "route", "get", ip], capture_output=True,
                             text=True, timeout=2).stdout
        return json.loads(out)[0].get("dev")
    except Exception:
        return None
