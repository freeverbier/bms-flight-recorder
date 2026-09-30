"""Worker BACnet — poll /collector/scans/next?protocol=bacnet et exécute :
- bacnet_whois : broadcast Who-Is depuis l'IP LAN
- discover_objects : délégué à discovery_worker.run_discovery
"""
from __future__ import annotations
import asyncio
import os
import socket
import traceback

import httpx

from net_utils import pick_interface_for_target

BACNET_BIND_IP = os.getenv("BACNET_BIND_IP", "")
BACNET_BROADCAST = os.getenv("BACNET_BROADCAST", "")
BACNET_SCAN_TIMEOUT = float(os.getenv("BACNET_SCAN_TIMEOUT", "10"))

POLL_INTERVAL = 3.0


async def run_worker(api_url: str, headers: dict, stop_event: asyncio.Event, state: dict):
    """Boucle principale du worker : poll → dispatch → patch status."""
    print(f"[bacnet-worker] démarrage (poll toutes les {POLL_INTERVAL}s)", flush=True)
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        while True:
            try:
                r = await client.get(
                    f"{api_url}/collector/scans/next",
                    params={"protocol": "bacnet"},
                )
                if r.status_code == 204:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                r.raise_for_status()
                job = r.json()
            except Exception as exc:
                print(f"[bacnet-worker] poll error: {exc}", flush=True)
                await asyncio.sleep(5)
                continue

            job_id = job.get("id")
            mode = job.get("mode", "")
            target = job.get("target", "")
            print(f"[bacnet-worker] job {job_id} mode={mode} target={target}", flush=True)

            error_msg = ""
            try:
                if mode == "bacnet_whois":
                    await _do_whois(job, stop_event)
                elif mode == "discover_objects":
                    await _do_discover_objects(job, client, api_url, stop_event)
                else:
                    error_msg = f"mode inconnu: {mode}"
                    print(f"[bacnet-worker] {error_msg}", flush=True)
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"[:200]
                print(f"[bacnet-worker] job {job_id} EXCEPTION: {error_msg}", flush=True)
                traceback.print_exc()

            # Report status
            status = "completed" if not error_msg else "failed"
            try:
                await client.patch(
                    f"{api_url}/collector/scans/{job_id}",
                    data={"status": status, "error": error_msg},
                )
                state["jobs_done"] = state.get("jobs_done", 0) + 1
                print(f"[bacnet-worker] job {job_id} → {status}", flush=True)
            except Exception as exc:
                print(f"[bacnet-worker] patch status failed: {exc}", flush=True)


async def _do_whois(job: dict, stop_event: asyncio.Event):
    """Envoie un Who-Is broadcast. Pas besoin de bloquer le sniffer (unicast source port éphémère)."""
    target = job.get("target") or "255.255.255.255"
    port = int(job.get("port") or 47808)

    iface = pick_interface_for_target(target)
    bind_ip = iface["ip"] if iface else (BACNET_BIND_IP or "0.0.0.0")

    # Paquet Who-Is standard : BVLC Original-Broadcast-NPDU + APDU unconfirmed whoIs
    packet = bytes.fromhex("810b000c0120ffff00ff1008")

    def _send():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind_ip, 0))
        except OSError as exc:
            print(f"[bacnet-whois] bind {bind_ip} failed (retry sans bind): {exc}", flush=True)
        try:
            n1 = s.sendto(packet, (target, port))
            n2 = s.sendto(packet, (target, port))
            print(f"[bacnet-whois] {bind_ip} → {target}:{port} ({n1}+{n2} bytes)", flush=True)
        finally:
            s.close()

    await asyncio.to_thread(_send)
    # Laisse le sniffer capter les I-Am qui vont arriver
    await asyncio.sleep(2)


async def _do_discover_objects(job: dict, client, api_url: str, stop_event: asyncio.Event):
    """Discovery d'objets d'un device — a besoin du port 47808 → pause le sniffer."""
    try:
        from discovery_worker import run_discovery
    except ImportError as exc:
        raise RuntimeError(f"discovery_worker absent: {exc}")

    device_uuid = job.get("target")
    if not device_uuid:
        raise ValueError("discover_objects: target (device_uuid) manquant")

    print(f"[bacnet-worker] pause sniffer pour discover_objects {device_uuid}", flush=True)
    stop_event.set()
    await asyncio.sleep(2)  # laisser le sniffer fermer son socket

    try:
        await run_discovery(
            device_uuid=device_uuid,
            api_url=api_url,
            client=client,
            bind_ip=BACNET_BIND_IP or "0.0.0.0",
            timeout=BACNET_SCAN_TIMEOUT,
        )
    finally:
        stop_event.clear()
        print(f"[bacnet-worker] port libéré, sniffer reprend", flush=True)
