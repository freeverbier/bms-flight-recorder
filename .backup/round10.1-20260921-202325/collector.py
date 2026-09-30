"""
Protocol collector — Round 10 : sniffer BACnet/IP passif + scan actif.

Round 9 (fix multi-interface pour le WhoIs) est conservé pour le scan actif.
Round 10 ajoute :
- bacnet_source() écoute UDP 47808 en permanence
- Chaque paquet reçu est décodé via bacnet_parse.decode_frame()
- Le résultat est poussé vers l'API interne (endpoint /bacnet/collector/frame)
- L'API relaie vers ClickHouse (bms.frames avec protocol='bacnet') et le bus SSE
- L'auto-discovery des devices et objets se fait au fil des IAm et RP/RPM ACK
  (côté API, la table bacnet_devices est peuplée sur détection)

Env vars :
  BACNET_BIND_IP        : IP source pour scan actif (auto sinon)
  BACNET_BROADCAST      : broadcast destination pour scan actif (auto sinon)
  BACNET_SCAN_TIMEOUT   : durée d'écoute du scan actif (défaut 10 s)
  BACNET_SCAN_RETRIES   : nombre de WhoIs envoyés (défaut 2)
  BACNET_SCAN_DEBUG     : 1 = log verbose paquets scan
  BACNET_SNIFF_ENABLE   : 1 = active le sniffer passif (défaut 1)
  BACNET_SNIFF_PORT     : port UDP du sniffer (défaut 47808)
  BACNET_SNIFF_DEBUG    : 1 = log chaque paquet capturé
"""

import asyncio
import ipaddress
import json
import os
import socket
import subprocess
import time

import httpx

from bacnet_parse import decode_frame

API = os.getenv("API_URL", "http://127.0.0.1:8080/api")
HEADERS = {"X-Internal-Token": os.getenv("INTERNAL_TOKEN", "")}

# Scan actif (Round 9)
BACNET_BIND_IP = os.getenv("BACNET_BIND_IP", "").strip()
BACNET_BROADCAST = os.getenv("BACNET_BROADCAST", "").strip()
BACNET_SCAN_TIMEOUT = float(os.getenv("BACNET_SCAN_TIMEOUT", "10"))
BACNET_SCAN_RETRIES = int(os.getenv("BACNET_SCAN_RETRIES", "2"))
BACNET_SCAN_DEBUG = os.getenv("BACNET_SCAN_DEBUG", "0") == "1"

# Sniffer passif (Round 10)
BACNET_SNIFF_ENABLE = os.getenv("BACNET_SNIFF_ENABLE", "1") == "1"
BACNET_SNIFF_PORT = int(os.getenv("BACNET_SNIFF_PORT", "47808"))
BACNET_SNIFF_DEBUG = os.getenv("BACNET_SNIFF_DEBUG", "0") == "1"

GATEWAY_ID = os.getenv("BACNET_GATEWAY_ID", "protocol-collector-bacnet")


def dbg_scan(msg):
    if BACNET_SCAN_DEBUG:
        print(f"[bacnet-scan] {msg}", flush=True)


def dbg_sniff(msg):
    if BACNET_SNIFF_DEBUG:
        print(f"[bacnet-sniff] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Network helpers (Round 9)
# ---------------------------------------------------------------------------

def list_interfaces():
    try:
        out = subprocess.check_output(["ip", "-j", "addr", "show"], text=True)
        data = json.loads(out)
    except Exception:
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
    ifaces = list_interfaces()
    if not ifaces:
        return None
    if BACNET_BIND_IP:
        for i in ifaces:
            if i["ip"] == BACNET_BIND_IP:
                return i
    if target and target != "255.255.255.255":
        try:
            t = ipaddress.IPv4Address(target)
            for i in ifaces:
                if t in i["network"]:
                    return i
        except Exception:
            pass
    for i in ifaces:
        try:
            if ipaddress.IPv4Address(i["ip"]).is_private:
                return i
        except Exception:
            continue
    return ifaces[0] if ifaces else None


def resolve_broadcast(target, iface):
    if BACNET_BROADCAST:
        return BACNET_BROADCAST
    if target and target != "255.255.255.255":
        return target
    if iface:
        return iface["broadcast"]
    return "255.255.255.255"


def bacnet_device_id(data):
    """Récupère l'instance depuis un I-Am (pour le scan actif). Retourne None si pas trouvé."""
    marker = data.find(b"\x10\x00\xc4")
    if marker < 0 or len(data) < marker + 7:
        return None
    object_id = int.from_bytes(data[marker + 3:marker + 7], "big")
    return object_id & 0x3FFFFF


# ---------------------------------------------------------------------------
# API push : envoie une frame décodée vers l'API
# ---------------------------------------------------------------------------

async def push_frame(client: httpx.AsyncClient, src_ip: str, src_port: int,
                      dst_ip: str, dst_port: int, decoded: dict) -> None:
    """Poste une frame BACnet décodée vers l'API interne."""
    try:
        extra_json = json.dumps(decoded.get("extra", {}), default=str)
    except Exception:
        extra_json = "{}"
    payload = {
        "gateway_id": GATEWAY_ID,
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "bvlc_function": decoded.get("bvlc_function") or "",
        "apdu_type": decoded.get("apdu_type") or "",
        "service": decoded.get("service") or "",
        "invoke_id": str(decoded.get("invoke_id") or ""),
        "object_ref": decoded.get("object_ref") or "",
        "property": decoded.get("property") or "",
        "value": decoded.get("value") or "",
        "value_num": str(decoded.get("value_num")) if decoded.get("value_num") is not None else "",
        "unit": decoded.get("unit") or "",
        "operation_detail": decoded.get("operation_detail") or "",
        "raw_hex": decoded.get("raw_hex") or "",
        "extra_json": extra_json,
    }
    try:
        r = await client.post(
            f"{API}/bacnet/collector/frame",
            headers=HEADERS,
            data=payload,
            timeout=5,
        )
        if r.status_code >= 400:
            dbg_sniff(f"push_frame HTTP {r.status_code}: {r.text[:200]}")
    except Exception as exc:
        dbg_sniff(f"push_frame failed: {exc}")


# ---------------------------------------------------------------------------
# Sniffer passif (Round 10)
# ---------------------------------------------------------------------------

async def bacnet_sniffer():
    """
    Écoute permanente sur UDP 47808. Chaque paquet reçu est décodé et poussé
    vers l'API interne. Détecte automatiquement l'interface LAN.
    """
    if not BACNET_SNIFF_ENABLE:
        print("[bacnet-sniff] désactivé (BACNET_SNIFF_ENABLE=0)", flush=True)
        return

    iface = pick_interface_for_target("255.255.255.255")
    bind_ip = iface["ip"] if iface else ""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Bind INADDR_ANY pour capter à la fois unicast et broadcast
    try:
        sock.bind(("", BACNET_SNIFF_PORT))
    except OSError as exc:
        print(f"[bacnet-sniff] bind {BACNET_SNIFF_PORT} failed: {exc}", flush=True)
        return
    sock.setblocking(False)
    loop = asyncio.get_running_loop()

    print(f"[bacnet-sniff] démarré sur 0.0.0.0:{BACNET_SNIFF_PORT} "
          f"(interface LAN détectée = {bind_ip or 'aucune'})", flush=True)

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                data, peer = await loop.sock_recvfrom(sock, 4096)
            except Exception as exc:
                print(f"[bacnet-sniff] recv failed: {exc}", flush=True)
                await asyncio.sleep(1)
                continue
            src_ip, src_port = peer[0], peer[1]

            # On ne peut pas connaître la vraie destination sans SO_TIMESTAMPING
            # ou pktinfo. On indique "local" pour le trafic reçu.
            dst_ip = bind_ip or "local"
            dst_port = BACNET_SNIFF_PORT

            try:
                decoded = decode_frame(data, src_ip=src_ip, src_port=src_port)
            except Exception as exc:
                dbg_sniff(f"decode failed {src_ip}: {exc}")
                continue

            dbg_sniff(f"{src_ip}:{src_port} → {decoded.get('operation_detail')}")

            # Ne pas pousser nos propres WhoIs qui ré-entrent (bind_ip = source)
            if src_ip == bind_ip and decoded.get("service") == "whoIs":
                dbg_sniff("skip local echo of our own WhoIs")
                continue

            await push_frame(client, src_ip, src_port, dst_ip, dst_port, decoded)


# ---------------------------------------------------------------------------
# Scan actif (Round 9 conservé)
# ---------------------------------------------------------------------------

async def scan_bacnet(job, client):
    target = job.get("target") or "255.255.255.255"
    port = int(job.get("port") or 47808)

    iface = pick_interface_for_target(target)
    bind_ip = iface["ip"] if iface else "0.0.0.0"
    effective_target = resolve_broadcast(target, iface)

    dbg_scan(f"scan job {job['id']}: bind_ip={bind_ip} target={target} → effective={effective_target}:{port}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Pour le scan, on ne bind PAS 47808 (déjà pris par le sniffer).
    # On utilise un port éphémère. Le sniffer verra les I-Am (broadcast).
    try:
        sock.bind((bind_ip, 0))
        bound_port = sock.getsockname()[1]
        dbg_scan(f"scan bind → {bind_ip}:{bound_port}")
    except OSError as exc:
        dbg_scan(f"scan bind {bind_ip} failed: {exc}")
        sock.bind(("", 0))

    sock.setblocking(False)
    loop = asyncio.get_running_loop()
    packet = bytes.fromhex("810b000c0120ffff00ff1008")

    async def send_whois():
        for i in range(BACNET_SCAN_RETRIES):
            try:
                await loop.sock_sendto(sock, packet, (effective_target, port))
                dbg_scan(f"WhoIs #{i+1} → {effective_target}:{port}")
            except Exception as exc:
                dbg_scan(f"WhoIs sendto failed: {exc}")
            if i < BACNET_SCAN_RETRIES - 1:
                await asyncio.sleep(1.0)

    send_task = asyncio.create_task(send_whois())

    deadline = loop.time() + BACNET_SCAN_TIMEOUT
    seen = set()
    while loop.time() < deadline:
        try:
            data, peer = await asyncio.wait_for(
                loop.sock_recvfrom(sock, 4096),
                deadline - loop.time(),
            )
        except (TimeoutError, asyncio.TimeoutError):
            break
        if len(data) >= 12 and data[:12] == packet[:12] and peer[0] == bind_ip:
            continue
        device_id = bacnet_device_id(data)
        key = f"{peer[0]}:{peer[1]}"
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
                    "device_id": device_id, "transport": "BACnet/IP",
                    "discovered_via": effective_target,
                    "scanner_iface": iface["name"] if iface else "?",
                }),
            },
        )

    await send_task
    sock.close()
    dbg_scan(f"scan terminé : {len(seen)} devices trouvés")


async def scan_worker():
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(
                    f"{API}/collector/scans/next",
                    params={"protocol": "bacnet"}, headers=HEADERS,
                )
                if response.status_code == 204:
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                job = response.json()
                try:
                    await scan_bacnet(job, client)
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}", headers=HEADERS,
                        data={"status": "completed"},
                    )
                except Exception as exc:
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}", headers=HEADERS,
                        data={"status": "failed", "error": str(exc)[:200]},
                    )
            except Exception as exc:
                print(f"BACnet scan: {exc}", flush=True)
                await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Sources (unchanged)
# ---------------------------------------------------------------------------

async def bacnet_source(source):
    """Passive listener status keeper (le vrai sniffer tourne dans bacnet_sniffer)."""
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await set_status(client, source["id"], "online")
            await asyncio.sleep(60)


async def set_status(client, source_id, status, error=None):
    try:
        await client.patch(
            f"{API}/sources/{source_id}/status", headers=HEADERS,
            data={"status": status, "error": error or ""},
        )
    except Exception:
        pass


async def run_source(source):
    while True:
        try:
            if source["protocol"] == "bacnet":
                await bacnet_source(source)
            else:
                await asyncio.sleep(3600)
        except Exception as exc:
            print(f"Source {source['id']}: {exc}", flush=True)
            await asyncio.sleep(15)


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
    print(f"[protocol-collector] Round 10 démarré — {len(ifaces)} interface(s) IPv4 :", flush=True)
    for i in ifaces:
        print(f"  {i['name']:20} {i['ip']}/{i['prefix']:2}  broadcast={i['broadcast']}", flush=True)
    print(f"[protocol-collector] Sniffer BACnet : {'ON' if BACNET_SNIFF_ENABLE else 'OFF'} "
          f"port={BACNET_SNIFF_PORT}", flush=True)
    print(f"[protocol-collector] Scan actif : BIND_IP={BACNET_BIND_IP or 'auto'} "
          f"BROADCAST={BACNET_BROADCAST or 'auto'} TIMEOUT={BACNET_SCAN_TIMEOUT}s", flush=True)

    await asyncio.gather(
        bacnet_sniffer(),
        sync_sources(),
        scan_worker(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
