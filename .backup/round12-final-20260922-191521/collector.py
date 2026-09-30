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
# Round 12.3 : queue partagée sniffer → worker discovery
_bacnet_discovery_queue = None


_sniffer_stop_event = asyncio.Event()

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
            # Round 12.8 : si un discovery veut le port, fermer et attendre
            if _sniffer_stop_event.is_set():
                print(f"[bacnet-sniff] pause pour discovery (fermeture socket)", flush=True)
                try:
                    sock.close()
                except Exception:
                    pass
                while _sniffer_stop_event.is_set():
                    await asyncio.sleep(0.3)
                print(f"[bacnet-sniff] reprise (réouverture socket)", flush=True)
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                try:
                    sock.bind(("", BACNET_SNIFF_PORT))
                except OSError as exc:
                    print(f"[bacnet-sniff] réouverture échouée: {exc}", flush=True)
                    await asyncio.sleep(1)
                    continue
                sock.setblocking(False)
                continue
            try:
                # Timeout court pour rechecker _sniffer_stop_event régulièrement
                try:
                    data, peer = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 4096), timeout=0.5,
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    continue
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
    """
    Round 10.1 : envoie le WhoIs et laisse le sniffer capter les I-Am.
    Après le timeout, lit /bacnet/devices pour récupérer les devices vus
    pendant la fenêtre, et les remonte via /collector/scans/{id}/devices.
    """
    from datetime import datetime, timezone
    target = job.get("target") or "255.255.255.255"
    port = int(job.get("port") or 47808)

    iface = pick_interface_for_target(target)
    bind_ip = iface["ip"] if iface else "0.0.0.0"
    effective_target = resolve_broadcast(target, iface)

    dbg_scan(f"scan job {job['id']}: target={effective_target}:{port} bind_ip={bind_ip}")

    # Socket SEULEMENT pour envoi (port éphémère, port 47808 pris par le sniffer)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind_ip, 0))
    except OSError:
        sock.bind(("", 0))
    sock.setblocking(False)
    loop = asyncio.get_running_loop()
    packet = bytes.fromhex("810b000c0120ffff00ff1008")

    scan_start = datetime.now(timezone.utc)

    # Émission des WhoIs
    for i in range(BACNET_SCAN_RETRIES):
        try:
            await loop.sock_sendto(sock, packet, (effective_target, port))
            dbg_scan(f"WhoIs #{i+1} → {effective_target}:{port}")
        except Exception as exc:
            dbg_scan(f"WhoIs sendto failed: {exc}")
        if i < BACNET_SCAN_RETRIES - 1:
            await asyncio.sleep(1.0)
    sock.close()

    # Attendre que le sniffer capte les I-Am
    await asyncio.sleep(BACNET_SCAN_TIMEOUT)

    # Récupérer les devices vus depuis scan_start (via l'API interne)
    try:
        r = await client.get(
            f"{API}/bacnet/devices",
            headers=HEADERS,
            params={"since_iso": scan_start.isoformat(), "limit": 500},
            timeout=10,
        )
        r.raise_for_status()
        devices = r.json()
    except Exception as exc:
        dbg_scan(f"list devices failed: {exc}")
        devices = []

    dbg_scan(f"scan terminé : sniffer a vu {len(devices)} device(s) pendant la fenêtre")

    # Remonter chaque device dans le job de scan
    for dev in devices:
        addr = f"{dev['ip_address']}:{dev['port']}"
        did = dev.get("device_id")
        name = f"BACnet Device {did}" if did is not None else "Équipement BACnet"
        await client.post(
            f"{API}/collector/scans/{job['id']}/devices",
            headers=HEADERS,
            data={
                "protocol": "bacnet",
                "address": addr,
                "name": name,
                "metadata": json.dumps({
                    "device_id": did,
                    "vendor_id": dev.get("vendor_id"),
                    "max_apdu": dev.get("max_apdu"),
                    "transport": "BACnet/IP",
                    "discovered_via": effective_target,
                    "via_sniffer": True,
                }),
            },
        )




# ============================================================================
# Round 12 : discovery des objets d'un device (RP object-list + RPM par objet)
# ============================================================================

async def discover_device_objects(job, client):
    """Round 12.6 : logique identique au test manuel réussi (bind 47808 exclusif)."""
    from bacnet_parse.build import build_readpropertymultiple
    from bacnet_parse.frame import decode_frame
    from bacnet_parse.enums import OBJECT_TYPES

    device_uuid = job.get("target", "")
    if not device_uuid or "-" not in device_uuid:
        return

    try:
        r = await client.get(f"{API}/bacnet/devices", headers=HEADERS, timeout=5)
        r.raise_for_status()
        devices = r.json()
    except Exception as exc:
        print(f"[bacnet-discovery] fetch failed: {exc}", flush=True)
        return

    device = next((d for d in devices if d["id"] == device_uuid), None)
    if not device or not device.get("device_id"):
        return

    ip = device["ip_address"]
    device_instance = device["device_id"]
    bacnet_port = 47808

    iface = pick_interface_for_target(ip)
    bind_ip = iface["ip"] if iface else "192.168.0.147"

    # 1. Demander au sniffer de libérer 47808
    print(f"[bacnet-discovery] demande pause sniffer", flush=True)
    _sniffer_stop_event.set()
    print(f"[bacnet-discovery] attente 2s libération 47808...", flush=True)
    await asyncio.sleep(2.0)  # laisser au sniffer le temps (0.5s wait_for + 0.5s marge)

    # 2. Bind exclusif 47808 (EXACTEMENT comme le test manuel)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        # Round 12.9 : bind INADDR_ANY (comme le sniffer) pour recevoir aussi
        # les réponses envoyées en broadcast par certains devices.
        sock.bind(("", bacnet_port))
        print(f"[bacnet-discovery] bind 0.0.0.0:{bacnet_port} OK (source-IP={bind_ip})", flush=True)
    except OSError as exc:
        print(f"[bacnet-discovery] bind ÉCHOUÉ : {exc}", flush=True)
        _sniffer_stop_event.clear()
        return
    sock.setblocking(False)
    loop = asyncio.get_running_loop()

    async def rpm_wait(pkt, timeout=3.0):
        await loop.sock_sendto(sock, pkt, (ip, bacnet_port))
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            try:
                data, peer = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65536), timeout=remaining,
                )
            except (asyncio.TimeoutError, TimeoutError):
                return None
            if peer[0] != ip:
                continue
            d = decode_frame(data, src_ip=peer[0], src_port=peer[1])
            try:
                await push_frame(client, peer[0], peer[1], bind_ip, bacnet_port, d)
                print(f"[bacnet-discovery] pushed frame {d.get('operation_detail', '?')[:60]}", flush=True)
            except Exception as exc:
                print(f"[bacnet-discovery] push_frame EXCEPTION: {exc}", flush=True)
            if d.get("apdu_type") == "Error":
                print(f"[bacnet-discovery] {ip} ERROR : {d.get('operation_detail')} hex={data.hex()}", flush=True)
            return d
        return None

    try:
        print(f"[bacnet-discovery] {ip} device:{device_instance} → RPM object-list[0]", flush=True)

        pkt = build_readpropertymultiple(
            invoke_id=1,
            specs=[{"obj_type": 8, "obj_instance": device_instance,
                    "properties": [{"id": 76, "index": 0}]}],
        )
        decoded = await rpm_wait(pkt, timeout=5.0)
        if not decoded or decoded.get("apdu_type") == "Error":
            print(f"[bacnet-discovery] {ip} : count échoué", flush=True)
            return

        # Extraction robuste du count depuis plusieurs sources
        count = 0
        # Essai 1 : value_num direct
        try:
            count = int(decoded.get("value_num") or 0)
        except (ValueError, TypeError):
            pass
        # Essai 2 : parse extra.rpm_results
        if count == 0:
            rpm = decoded.get("extra", {}).get("rpm_results", {})
            for k, v in rpm.items():
                # v peut être "76=13" ou "object-list[0]=13"
                if isinstance(v, (str, int)):
                    s = str(v)
                    import re
                    m = re.search(r"=\s*(\d+)", s)
                    if m:
                        count = int(m.group(1))
                        break
        # Essai 3 : parse le hex brut - chercher UnsignedInt LVT 1 après 4e (property-value opening)
        if count == 0:
            raw = decoded.get("raw_hex", "")
            if isinstance(raw, str) and "4e" in raw:
                # 4e = ctx tag 4 opening, puis 21 XX = UnsignedInt 1 byte
                idx = raw.find("4e21")
                if idx > 0:
                    try:
                        count = int(raw[idx+4:idx+6], 16)
                    except (ValueError, IndexError):
                        pass
                # Ou 4e22 XX XX = UnsignedInt 2 bytes
                if count == 0:
                    idx = raw.find("4e22")
                    if idx > 0:
                        try:
                            count = int(raw[idx+4:idx+8], 16)
                        except (ValueError, IndexError):
                            pass
        print(f"[bacnet-discovery] {ip} : decoded value_num={decoded.get('value_num')} value={decoded.get('value')} extra={decoded.get('extra', {}).get('rpm_results')}", flush=True)
        print(f"[bacnet-discovery] {ip} : count={count} objets", flush=True)
        if count <= 0 or count > 5000:
            return

        # Batches de 10 array-indices
        object_list = []
        BATCH = 10
        invoke_id = 2
        for start in range(1, count + 1, BATCH):
            end = min(start + BATCH - 1, count)
            props = [{"id": 76, "index": i} for i in range(start, end + 1)]
            pkt = build_readpropertymultiple(
                invoke_id=invoke_id,
                specs=[{"obj_type": 8, "obj_instance": device_instance, "properties": props}],
            )
            invoke_id = ((invoke_id + 1) & 0xFF) or 1
            d = await rpm_wait(pkt, timeout=3.0)
            if not d or d.get("apdu_type") == "Error":
                print(f"[bacnet-discovery] batch {start}-{end} échoué", flush=True)
                continue
            # Parser les ObjectIDs directement depuis le hex brut.
            # Pattern : c4 XX XX XX XX (app tag 12, ObjectID 4 bytes)
            raw = d.get("raw_hex", "")
            import re
            batch_objs = []
            for m in re.finditer(r"c4([0-9a-f]{8})", raw):
                raw_id = int(m.group(1), 16)
                otype = (raw_id >> 22) & 0x3FF
                inst = raw_id & 0x3FFFFF
                type_name = OBJECT_TYPES.get(otype, f"type-{otype}")
                batch_objs.append({"type_name": type_name, "instance": inst})
            print(f"[bacnet-discovery] batch {start}-{end}: {len(batch_objs)} objets extraits", flush=True)
            object_list.extend(batch_objs)
            await asyncio.sleep(0.05)

        seen = set()
        object_list = [o for o in object_list if not ((o["type_name"], o["instance"]) in seen or seen.add((o["type_name"], o["instance"])))]
        print(f"[bacnet-discovery] {ip} : {len(object_list)} objet(s)", flush=True)

        type_rev = {v: k for k, v in OBJECT_TYPES.items()}
        business = {"analog-input", "analog-output", "analog-value",
                    "binary-input", "binary-output", "binary-value",
                    "multi-state-input", "multi-state-output", "multi-state-value",
                    "accumulator", "pulse-converter", "loop", "trend-log"}
        filtered = [{**o, "type_int": type_rev.get(o["type_name"], -1)}
                    for o in object_list
                    if o["type_name"] != "device" and o["type_name"] in business]
        print(f"[bacnet-discovery] {ip} : {len(filtered)} métier", flush=True)

        for obj in filtered:
            if obj["type_int"] < 0:
                continue
            pkt = build_readpropertymultiple(
                invoke_id=invoke_id,
                specs=[{"obj_type": obj["type_int"], "obj_instance": obj["instance"],
                        "property_ids": [77, 116, 28, 85]}],
            )
            invoke_id = ((invoke_id + 1) & 0xFF) or 1
            await rpm_wait(pkt, timeout=1.5)
            await asyncio.sleep(0.03)

        print(f"[bacnet-discovery] {ip} : discovery terminé", flush=True)

    finally:
        sock.close()
        # 3. Rendre 47808 au sniffer
        _sniffer_stop_event.clear()
        print(f"[bacnet-discovery] port 47808 libéré, sniffer va reprendre", flush=True)



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
                    if job.get("mode") == "discover_objects":
                        await discover_device_objects(job, client)
                    else:
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
