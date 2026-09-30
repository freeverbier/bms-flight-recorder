"""
Collecteur KNX temps réel — Round 5.

Un ensemble de tâches asyncio, une par gateway configurée :
- routing multicast : rejoint le groupe et écoute passivement,
- tunneling : ouvre une session KNXnet/IP link-layer, acquitte, envoie
  périodiquement un ConnectionState, se reconnecte sur erreur.

Chaque télégramme reçu est décodé via `knxparse.cemi.decode_cemi`, qui utilise
en interne :
- la table APCI complète (`apci.py`) — tous les services KNX classifiés
- le registre DPT dynamique (`dpt_registry.py`) — chargé depuis Postgres via l'API

Ensuite pushé vers l'API sur `/knx/collector/telegram`. L'API relaie sur SSE et
insère dans ClickHouse.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import time
from collections import OrderedDict
from typing import Optional

import httpx

from knxparse import knxnetip
from knxparse.cemi import decode_cemi
from knxparse.dpt_registry import DptRegistry

API = os.getenv("API_URL", "http://127.0.0.1:8080/api")
TOKEN = os.getenv("INTERNAL_TOKEN", "")
HEADERS = {"X-Internal-Token": TOKEN}
SCAN_DURATION = float(os.getenv("KNX_SCAN_SECONDS", "5"))
GATEWAY_SYNC_INTERVAL = float(os.getenv("KNX_GATEWAY_SYNC_SECONDS", "15"))
DPT_RELOAD_INTERVAL = int(os.getenv("KNX_DPT_RELOAD_SECONDS", "30"))
DEDUP_WINDOW_S = float(os.getenv("KNX_DEDUP_WINDOW_SECONDS", "1.5"))
DEDUP_CAPACITY = int(os.getenv("KNX_DEDUP_CAPACITY", "4096"))

# Registres partagés entre les gateways
# _ga_registry : {ga_str: {"dpt": "9.001", "name": "Temp salon"}}
_ga_registry: dict[str, dict] = {}
_ga_registry_lock = asyncio.Lock()
_ga_registry_loaded_at: float = 0.0

# Registre DPT dynamique (thread interne + reload périodique)
_dpt_registry = DptRegistry(API, TOKEN, reload_interval_s=DPT_RELOAD_INTERVAL)


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("knx-collector")


class DedupCache:
    """Cache LRU pour éviter de compter deux fois un même télégramme."""

    def __init__(self, capacity: int, window: float) -> None:
        self._data: OrderedDict[bytes, float] = OrderedDict()
        self._capacity = capacity
        self._window = window

    def check_and_add(self, raw: bytes) -> bool:
        key = hashlib.blake2b(raw, digest_size=16).digest()
        now = time.monotonic()
        if len(self._data) >= self._capacity:
            oldest_key = next(iter(self._data))
            self._data.pop(oldest_key)
        seen_at = self._data.get(key)
        if seen_at is not None and now - seen_at < self._window:
            return False
        self._data[key] = now
        self._data.move_to_end(key)
        return True


_dedup = DedupCache(DEDUP_CAPACITY, DEDUP_WINDOW_S)


# ---------------------------------------------------------------------------
# Publication des télégrammes vers l'API
# ---------------------------------------------------------------------------


async def publish_telegram(
    client: httpx.AsyncClient,
    gateway_id: str,
    cemi_raw: bytes,
) -> None:
    """
    Décode le cEMI et envoie le télégramme normalisé à l'API.
    Round 5 : utilise decode_cemi() qui gère toute la spec APCI + DPT registry.
    """
    async with _ga_registry_lock:
        ga_snapshot = dict(_ga_registry)  # snapshot pour éviter mutation pendant décodage

    decoded = decode_cemi(cemi_raw, dpt_registry=_dpt_registry, ga_registry=ga_snapshot)
    if not decoded:
        return

    payload = {
        "gateway_id": gateway_id,
        "source": decoded["source"],
        "destination": decoded["destination"],
        "apci": decoded["apci"],
        "apci_category": decoded["apci_category"],
        "tpci": decoded["tpci"],
        "value": decoded["value"],
        "unit": decoded["unit"],
        "dpt": decoded["dpt"],
        "point_name": decoded["point_name"],
        "priority": decoded["priority"],
        "hop_count": decoded["hop_count"],
        "extra_json": json.dumps(decoded["extra"] or {}, separators=(",", ":")),
        "raw_hex": decoded["raw_hex"],
    }

    try:
        await client.post(
            f"{API}/knx/collector/telegram",
            headers=HEADERS,
            data=payload,
            timeout=5,
        )
    except Exception as exc:
        log.warning("Publication télégramme échouée : %s", exc)


# ---------------------------------------------------------------------------
# Registre des adresses de groupe (ETS)
# ---------------------------------------------------------------------------


async def refresh_group_addresses(client: httpx.AsyncClient) -> None:
    global _ga_registry, _ga_registry_loaded_at
    try:
        response = await client.get(f"{API}/knx/group-addresses", timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("Impossible de recharger les GA : %s", exc)
        return
    async with _ga_registry_lock:
        _ga_registry = {
            row["address"]: {"dpt": row.get("dpt") or "", "name": row.get("name") or ""}
            for row in payload
            if row.get("address")
        }
        _ga_registry_loaded_at = time.monotonic()
    log.info("Registre GA rechargé : %d entrées", len(_ga_registry))


# ---------------------------------------------------------------------------
# Routing multicast (KNXnet/IP)
# ---------------------------------------------------------------------------


async def routing_listener(gateway: dict, client: httpx.AsyncClient) -> None:
    group = gateway.get("multicast_group") or knxnetip.DEFAULT_MULTICAST
    port = int(gateway.get("port") or knxnetip.DEFAULT_PORT)
    bind_ip = os.getenv("KNX_BIND_IP", "0.0.0.0")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((bind_ip, port))
    except OSError as exc:
        raise RuntimeError(f"bind {bind_ip}:{port} impossible ({exc})") from exc
    mreq = socket.inet_aton(group) + socket.inet_aton(bind_ip)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setblocking(False)
    loop = asyncio.get_running_loop()

    await set_status(client, gateway["id"], "online")
    log.info("Routing sur %s:%d (gateway %s)", group, port, gateway["id"])

    try:
        while True:
            data, _ = await loop.sock_recvfrom(sock, 2048)
            cemi = knxnetip.parse_routing_indication(data)
            if not cemi:
                continue
            if not _dedup.check_and_add(cemi):
                continue
            await publish_telegram(client, gateway["id"], cemi)
    finally:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
        except OSError:
            pass
        sock.close()


# ---------------------------------------------------------------------------
# Tunneling KNXnet/IP link-layer
# ---------------------------------------------------------------------------


async def tunneling_listener(gateway: dict, client: httpx.AsyncClient) -> None:
    if gateway.get("secure"):
        await set_status(
            client, gateway["id"], "credential_required",
            "Adaptateur KNX IP Secure non activé dans cette version",
        )
        while True:
            await asyncio.sleep(300)

    host = gateway["host"]
    port = int(gateway.get("port") or knxnetip.DEFAULT_PORT)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)
    loop = asyncio.get_running_loop()

    local_ip = await knxnetip.local_ip_for(host, port)
    local_port = sock.getsockname()[1]
    hpai = knxnetip.build_hpai(local_ip, local_port)
    request = knxnetip.build_connect_request(hpai, hpai)

    await loop.sock_sendto(sock, request, (host, port))
    try:
        resp, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), 5)
    except TimeoutError:
        raise RuntimeError("Aucune réponse KNXnet/IP dans les 5 s")

    parsed = knxnetip.parse_connect_response(resp)
    if not parsed or parsed.status != 0:
        code = parsed.status if parsed else "réponse invalide"
        raise RuntimeError(f"Connexion refusée (code {code})")

    channel = parsed.channel
    last_activity = time.monotonic()
    log.info("Tunnel ouvert vers %s:%d (canal %d)", host, port, channel)
    await set_status(client, gateway["id"], "online")

    try:
        while True:
            timeout = max(1.0, 50 - (time.monotonic() - last_activity))
            try:
                data, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), timeout)
            except TimeoutError:
                state = knxnetip.build_connectionstate_request(channel, hpai)
                await loop.sock_sendto(sock, state, (host, port))
                last_activity = time.monotonic()
                continue

            tunnel = knxnetip.parse_tunneling_request(data)
            if tunnel and tunnel.channel == channel:
                ack = knxnetip.build_tunneling_ack(channel, tunnel.sequence)
                await loop.sock_sendto(sock, ack, peer)
                last_activity = time.monotonic()
                if not _dedup.check_and_add(tunnel.cemi):
                    continue
                await publish_telegram(client, gateway["id"], tunnel.cemi)
    finally:
        try:
            disc = knxnetip.build_disconnect_request(channel, hpai)
            sock.sendto(disc, (host, port))
        except OSError:
            pass
        sock.close()


# ---------------------------------------------------------------------------
# Statut et orchestration
# ---------------------------------------------------------------------------


async def set_status(
    client: httpx.AsyncClient, gateway_id: str, status: str, error: str = "",
) -> None:
    try:
        await client.patch(
            f"{API}/gateways/{gateway_id}/status",
            headers=HEADERS,
            data={"status": status, "error": error},
            timeout=5,
        )
    except Exception as exc:
        log.debug("PATCH status impossible : %s", exc)


async def run_gateway(gateway: dict) -> None:
    log.info("Lancement gateway %s (%s)", gateway["id"], gateway["mode"])
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                if gateway["mode"] == "routing":
                    await routing_listener(gateway, client)
                else:
                    await tunneling_listener(gateway, client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Gateway %s en erreur : %s", gateway["id"], exc)
                await set_status(client, gateway["id"], "offline", str(exc)[:200])
                await asyncio.sleep(15)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


async def scan_knx(job: dict, client: httpx.AsyncClient) -> None:
    target = job.get("target") or knxnetip.DEFAULT_MULTICAST
    target_port = int(job.get("port") or knxnetip.DEFAULT_PORT)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    local_ip = await knxnetip.local_ip_for(target, target_port)
    hpai = knxnetip.build_hpai(local_ip, sock.getsockname()[1])
    request = knxnetip.build_search_request(hpai)

    loop = asyncio.get_running_loop()
    await loop.sock_sendto(sock, request, (target, target_port))

    deadline = loop.time() + SCAN_DURATION
    seen: set[str] = set()

    try:
        while loop.time() < deadline:
            try:
                data, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), deadline - loop.time())
            except TimeoutError:
                break
            response = knxnetip.parse_search_response(data, peer)
            if not response or response.address in seen:
                continue
            seen.add(response.address)
            await client.post(
                f"{API}/collector/scans/{job['id']}/devices",
                headers=HEADERS,
                data={
                    "protocol": "knx",
                    "address": f"{response.address}:{response.port}",
                    "name": response.name,
                    "metadata": json.dumps({
                        "individual_address": response.individual_address,
                        "mac": response.mac,
                        "knx_medium": response.knx_medium,
                        "transport": "KNXnet/IP",
                    }),
                },
                timeout=5,
            )
    finally:
        sock.close()


async def scan_worker() -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(
                    f"{API}/collector/scans/next",
                    params={"protocol": "knx"},
                    headers=HEADERS,
                    timeout=5,
                )
                if response.status_code == 204:
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                job = response.json()
                try:
                    await scan_knx(job, client)
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}",
                        headers=HEADERS,
                        data={"status": "completed"},
                    )
                except Exception as exc:
                    log.warning("Scan KNX en échec : %s", exc)
                    await client.patch(
                        f"{API}/collector/scans/{job['id']}",
                        headers=HEADERS,
                        data={"status": "failed", "error": str(exc)[:200]},
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Scan worker : %s", exc)
                await asyncio.sleep(5)


async def gateway_sync() -> None:
    tasks: dict[str, asyncio.Task] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        await refresh_group_addresses(client)
        while True:
            try:
                response = await client.get(f"{API}/gateways", timeout=5)
                response.raise_for_status()
                gateways = response.json()
                active = {g["id"] for g in gateways if g.get("enabled")}
                for gid in list(tasks):
                    if gid not in active:
                        tasks.pop(gid).cancel()
                for gateway in gateways:
                    if gateway.get("enabled") and gateway["id"] not in tasks:
                        tasks[gateway["id"]] = asyncio.create_task(run_gateway(gateway))
                if time.monotonic() - _ga_registry_loaded_at > 60:
                    await refresh_group_addresses(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Sync gateways : %s", exc)
            await asyncio.sleep(GATEWAY_SYNC_INTERVAL)


async def main() -> None:
    # Démarre le thread de reload du registre DPT en arrière-plan
    _dpt_registry.start()
    try:
        await asyncio.gather(gateway_sync(), scan_worker())
    finally:
        _dpt_registry.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
