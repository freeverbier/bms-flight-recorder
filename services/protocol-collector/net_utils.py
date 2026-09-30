"""Utilitaires réseau : liste des interfaces IPv4 + choix de l'interface pour une IP cible."""
from __future__ import annotations
import ipaddress
import json
import subprocess


def list_interfaces() -> list[dict]:
    """Retourne les interfaces IPv4 non-loopback : [{'name', 'ip', 'prefix', 'broadcast'}]."""
    try:
        r = subprocess.run(
            ["ip", "-j", "-4", "addr", "show"],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[net_utils] ip addr échoué: {exc}", flush=True)
        return []

    out: list[dict] = []
    for iface in json.loads(r.stdout):
        name = iface.get("ifname", "?")
        if name == "lo":
            continue
        for addr in iface.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            ip = addr.get("local")
            prefix = int(addr.get("prefixlen", 24))
            if not ip:
                continue
            try:
                net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
                broadcast = str(net.broadcast_address)
            except Exception:
                broadcast = ""
            out.append({"name": name, "ip": ip, "prefix": prefix, "broadcast": broadcast})
    return out


def pick_interface_for_target(target_ip: str) -> dict | None:
    """Retourne l'interface dont le subnet couvre target_ip.
    Pour 255.255.255.255 / broadcast, retourne la première interface non-Docker.
    """
    ifaces = list_interfaces()
    if not ifaces:
        return None

    # Broadcast global → première non-Docker
    if target_ip in ("255.255.255.255", "0.0.0.0"):
        for iface in ifaces:
            if not iface["name"].startswith(("docker", "br-", "veth")):
                return iface
        return ifaces[0]

    # Sinon : subnet qui matche
    try:
        target = ipaddress.IPv4Address(target_ip)
    except ValueError:
        return None

    for iface in ifaces:
        try:
            net = ipaddress.IPv4Network(f"{iface['ip']}/{iface['prefix']}", strict=False)
            if target in net or str(target) == iface["broadcast"]:
                return iface
        except Exception:
            continue

    # Fallback : première non-Docker
    for iface in ifaces:
        if not iface["name"].startswith(("docker", "br-", "veth")):
            return iface
    return ifaces[0] if ifaces else None
