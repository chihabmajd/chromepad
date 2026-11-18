"""LAN IP detection, skipping VPN and virtual interfaces, plus an ASCII QR code."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from typing import Optional

import qrcode

# "nordlynx" is named explicitly: NordVPN's WireGuard interface skips the wg
# prefix. Other vendors may need --host <ip> instead.
_SKIP_PREFIXES = ("lo", "nordlynx", "tun", "tap", "wg", "docker", "veth", "br-", "virbr")


def _candidate_addresses() -> list[tuple[str, str, bool]]:
    try:
        out = subprocess.run(
            ["ip", "-json", "-4", "addr"], capture_output=True, text=True, timeout=2
        ).stdout
        data = json.loads(out)
    except Exception:
        return []

    found: list[tuple[str, str, bool]] = []
    for link in data:
        name = link.get("ifname", "")
        if name.startswith(_SKIP_PREFIXES):
            continue
        for addr in link.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            ip = addr.get("local")
            if not ip:
                continue
            try:
                obj = ipaddress.ip_address(ip)
            except ValueError:
                continue
            # Campus/enterprise networks often hand out public addresses (e.g. a
            # university /16), so those count too, ranked after private ones.
            if not obj.is_loopback and not obj.is_link_local:
                found.append((name, ip, obj.is_private))
    return found


def _score(iface: str) -> int:
    if iface.startswith(("wl", "wlan", "wlp")):
        return 0
    if iface.startswith(("en", "eth", "eno", "enp")):
        return 1
    return 2


def detect_local_ip() -> Optional[str]:
    candidates = _candidate_addresses()
    if candidates:
        candidates.sort(key=lambda c: (not c[2], _score(c[0])))
        return candidates[0][1]
    try:                                       # fallback (may return VPN IP)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def print_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print(f"\n  ->  {url}\n")
