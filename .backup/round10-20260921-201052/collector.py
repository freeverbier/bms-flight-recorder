"""
Protocol collector — Round 9 : BACnet scan robuste multi-interface.

Améliorations vs Round initial :
- Auto-détection de l'IP source qui matche le subnet du target (via routing table)
- Support broadcast dirigé : si target=255.255.255.255, calcul du bon broadcast
  de l'interface choisie (192.168.0.255 par exemple)
- Bind sur port 47808 en priorité (comme Yabe), fallback port éphémère
- Retry configurable du WhoIs (défaut 2 envois à 1 s)
- Timeout écoute configurable (défaut 10 s)
- Log verbose pour debug (BACNET_SCAN_DEBUG=1)
- Override manuel via env : BACNET_BIND_IP, BACNET_BROADCAST

Env vars :
  BACNET_BIND_IP        : force l'IP source (ex. 192.168.0.42)
  BACNET_BROADCAST      : force l'adresse broadcast (ex. 192.168.0.255)
  BACNET_SCAN_TIMEOUT   : durée d'écoute en secondes (défaut 10)
  BACNET_SCAN_RETRIES   : nombre de WhoIs envoyés (défaut 2)
  BACNET_SCAN_DEBUG     : 1 = log verbose des paquets
"""

import asyncio
import ipaddress
import json
import os
import socket
import subprocess
import time

import httpx

API = os.getenv("API_URL", "http://127.0.0.1:8080/api")
HEADERS = {"X-Internal-Token": os.getenv("INTERNAL_TOKEN", "")}
BACNET_BIND_IP = os.getenv("BACNET_BIND_IP", "").strip()
BACNET_BROADCAST = os.getenv("BACNET_BROADCAST", "").strip()
BACNET_SCAN_TIMEOUT = float(os.getenv("BACNET_SCAN_TIMEOUT", "10"))
BACNET_SCAN_RETRIES = int(os.getenv("BACNET_SCAN_RETRIES", "2"))
BACNET_SCAN_DEBUG = os.getenv("BACNET_SCAN_DEBUG", "0") == "1"


def dbg(msg):
    if BACNET_SCAN_DEBUG:
        print(f"[bacnet-scan] {msg}", flush=True)


def config_of(item):
    raw = item.get("config") or {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw


async def set_status(client, source_id, status, error=None):
    try:
        await client.patch(
            f"{API}/sources/{source_id}/status", headers=HEADERS,
            data={"status": status, "error": error or ""},
        )
    except Exception:
        pass


async def bacnet_source(source):
    """Keep a passive BACnet/IP listener alive; Who-Is is opt-in."""
    async with httpx.AsyncClient(timeout=10) as client:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", int(source["port"])))
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        await set_status(client, source["id"], "online")
        next_discovery = 0.0
        while True:
            if source["mode"] == "discovery" and time.monotonic() >= next_discovery:
                packet = bytes.fromhex("810b000c0120ffff00ff1008")
                await loop.sock_sendto(sock, packet, (source["host"], int(source["port"])))
                next_discovery = time.monotonic() + int(config_of(source).get("discovery_seconds", 300))
            try:
                await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), timeout=5)
                await set_status(client, source["id"], "online")
            except TimeoutError:
                pass


# ---------------------------------------------------------------------------
# BACnet — network helpers Round 9
# ---------------------------------------------------------------------------

def list_interfaces():
    """
    Retourne une liste de dicts {name, ip, prefix, broadcast, network} pour
    toutes les interfaces IPv4 up.
    """
    try:
        out = subprocess.check_output(["ip", "-j", "addr", "show"], text=True)
        data = json.loads(out)
    except Exception as exc:
        dbg(f"list_interfaces failed: {exc}")
        return []
    result = []
    for iface in data:
        name = iface.get("ifname", "?")
        if iface.get("operstate") not in ("UP", "UNKNOWN"):
            continue
        for addr in iface.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            ip = addr.get("local")
            prefix = addr.get("prefixlen", 24)
            if not ip or ip.startswith("127."):
                continue
            try:
                net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
                result.append({
                    "name": name, "ip": ip, "prefix": prefix,
                    "broadcast": str(net.broadcast_address),
                    "network": net,
                })
            except Exception:
                continue
    return result


def pick_interface_for_target(target):
    """Choisit la meilleure interface pour joindre `target`."""
    ifaces = list_interfaces()
    if not ifaces:
        return None
    if BACNET_BIND_IP:
        for i in ifaces:
            if i["ip"] == BACNET_BIND_IP:
                dbg(f"pick: forcé par BACNET_BIND_IP → {i['name']} ({i['ip']})")
                return i
        dbg(f"pick: BACNET_BIND_IP={BACNET_BIND_IP} pas trouvé, fallback auto")
    if target and target != "255.255.255.255":
        try:
            t = ipaddress.IPv4Address(target)
            for i in ifaces:
                if t in i["network"]:
                    dbg(f"pick: subnet-match → {i['name']} ({i['ip']}) pour {target}")
                    return i
        except Exception:
            pass
    # Fallback : première interface RFC1918
    for i in ifaces:
        try:
            if ipaddress.IPv4Address(i["ip"]).is_private:
                dbg(f"pick: fallback RFC1918 → {i['name']} ({i['ip']})")
                return i
        except Exception:
            continue
    if ifaces:
        dbg(f"pick: fallback première interface → {ifaces[0]['name']} ({ifaces[0]['ip']})")
        return ifaces[0]
    return None


def resolve_broadcast(target, iface):
    """Détermine l'adresse broadcast effective."""
    if BACNET_BROADCAST:
        return BACNET_BROADCAST
    if target and target != "255.255.255.255":
        return target
    if iface:
        return iface["broadcast"]
    return "255.255.255.255"


def bacnet_device_id(data):
    marker = data.find(b"\x10\x00\xc4")
    if marker < 0 or len(data) < marker + 7:
        return None
    object_id = int.from_bytes(data[marker + 3:marker + 7], "big")
    return object_id & 0x3FFFFF


async def scan_bacnet(job, client):
    target = job.get("target") or "255.255.255.255"
    port = int(job.get("port") or 47808)

    iface = pick_interface_for_target(target)
    bind_ip = iface["ip"] if iface else "0.0.0.0"
    effective_target = resolve_broadcast(target, iface)

    dbg(f"scan job {job['id']}: bind_ip={bind_ip} target={target} → effective={effective_target}:{port}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind port 47808 en priorité (comme Yabe), fallback éphémère
    bound_port = 0
    for port_try in (port, 0):
        try:
            sock.bind((bind_ip, port_try))
            bound_port = sock.getsockname()[1]
            dbg(f"bind → {bind_ip}:{bound_port}")
            break
        except OSError as exc:
            dbg(f"bind {bind_ip}:{port_try} failed: {exc}, retry")
    else:
        sock.bind(("", 0))
        bound_port = sock.getsockname()[1]

    sock.setblocking(False)
    loop = asyncio.get_running_loop()

    # BVLC Original-Broadcast-NPDU + NPDU + unconfirmed Who-Is
    packet = bytes.fromhex("810b000c0120ffff00ff1008")

    async def send_whois():
        for i in range(BACNET_SCAN_RETRIES):
            try:
                await loop.sock_sendto(sock, packet, (effective_target, port))
                dbg(f"WhoIs #{i+1} envoyé vers {effective_target}:{port}")
            except Exception as exc:
                dbg(f"WhoIs #{i+1} sendto failed: {exc}")
            if i < BACNET_SCAN_RETRIES - 1:
                await asyncio.sleep(1.0)

    send_task = asyncio.create_task(send_whois())

    deadline = loop.time() + BACNET_SCAN_TIMEOUT
    seen = set()
    n_received = 0
    while loop.time() < deadline:
        try:
            data, peer = await asyncio.wait_for(
                loop.sock_recvfrom(sock, 4096),
                deadline - loop.time(),
            )
        except (TimeoutError, asyncio.TimeoutError):
            break
        n_received += 1
        # Ignorer notre propre WhoIs qui rebondit
        if len(data) >= 12 and data[:12] == packet[:12] and peer[0] == bind_ip:
            dbg(f"skip echo local from {peer}")
            continue
        device_id = bacnet_device_id(data)
        key = f"{peer[0]}:{peer[1]}"
        dbg(f"reçu de {key} device_id={device_id} data={data.hex()[:60]}")
        if key in seen:
            continue
        seen.add(key)
        await client.post(
            f"{API}/collector/scans/{job['id']}/devices",
            headers=HEADERS,
            data={
                "protocol": "bacnet",
                "address": key,
                "name": f"BACnet Device {device_id}" if device_id is not None else "Équipement BACnet",
                "metadata": json.dumps({
                    "device_id": device_id,
                    "transport": "BACnet/IP",
                    "discovered_via": effective_target,
                    "scanner_iface": iface["name"] if iface else "?",
                    "scanner_ip": bind_ip,
                }),
            },
        )

    await send_task
    sock.close()
    dbg(f"scan terminé : {len(seen)} devices trouvés sur {n_received} paquets reçus")


# ---------------------------------------------------------------------------
# Modbus retiré de ce round (pymodbus non installé dans requirements.txt)
# ---------------------------------------------------------------------------


async def run_source(source):
    while True:
        try:
            if source["protocol"] == "bacnet":
                await bacnet_source(source)
            else:
                # Autres protocoles non gérés dans ce collector (Modbus retiré)
                await asyncio.sleep(3600)
        except Exception as exc:
            print(f"Source {source['id']}: {exc}", flush=True)
            await asyncio.sleep(15)


async def scan_worker():
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(
                    f"{API}/collector/scans/next",
                    params={"protocol": "bacnet"},
                    headers=HEADERS,
                )
                if response.status_code == 204:
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                job = response.json()
                try:
                    await scan_bacnet(job, client)
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}",
                        headers=HEADERS,
                        data={"status": "completed"},
                    )
                except Exception as exc:
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}",
                        headers=HEADERS,
                        data={"status": "failed", "error": str(exc)[:200]},
                    )
            except Exception as exc:
                print(f"BACnet scan: {exc}", flush=True)
                await asyncio.sleep(5)


async def sync_sources():
    tasks = {}
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(f"{API}/sources", headers=HEADERS)
                response.raise_for_status()
                sources = response.json()
                active = {s["id"] for s in sources if s.get("enabled")}
                for sid in list(tasks):
                    if sid not in active:
                        tasks.pop(sid).cancel()
                for source in sources:
                    if source.get("enabled") and source["id"] not in tasks:
                        tasks[source["id"]] = asyncio.create_task(run_source(source))
            except Exception as exc:
                print(f"Sync sources: {exc}", flush=True)
            await asyncio.sleep(20)


async def main():
    ifaces = list_interfaces()
    print(f"[bacnet-scan] Round 9 démarré — {len(ifaces)} interface(s) IPv4 détectée(s) :", flush=True)
    for i in ifaces:
        print(f"  {i['name']:20} {i['ip']}/{i['prefix']:2}  broadcast={i['broadcast']}", flush=True)
    print(f"[bacnet-scan] Config : BIND_IP={BACNET_BIND_IP or 'auto'}  "
          f"BROADCAST={BACNET_BROADCAST or 'auto'}  "
          f"TIMEOUT={BACNET_SCAN_TIMEOUT}s  RETRIES={BACNET_SCAN_RETRIES}  "
          f"DEBUG={BACNET_SCAN_DEBUG}", flush=True)
    await asyncio.gather(sync_sources(), scan_worker())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
