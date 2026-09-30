"""Sniffer BACnet/IP passif — écoute UDP 47808, décode via bacnet_parse.decode_frame, push vers API."""
from __future__ import annotations
import asyncio
import os
import socket
import traceback
from datetime import datetime, timezone

import httpx

from net_utils import pick_interface_for_target

BACNET_SNIFF_PORT = int(os.getenv("BACNET_SNIFF_PORT", "47808"))
BACNET_SNIFF_DEBUG = os.getenv("BACNET_SNIFF_DEBUG", "0") == "1"


async def run_sniffer(api_url: str, headers: dict, stop_event: asyncio.Event, state: dict):
    try:
        from bacnet_parse import decode_frame
    except ImportError as exc:
        print(f"[bacnet-sniff] bacnet_parse.decode_frame introuvable: {exc}", flush=True)
        decode_frame = None

    iface = pick_interface_for_target("255.255.255.255")
    bind_ip_info = iface["ip"] if iface else "aucune"
    print(f"[bacnet-sniff] démarrage sur 0.0.0.0:{BACNET_SNIFF_PORT} "
          f"(interface LAN détectée = {bind_ip_info})", flush=True)

    sock = _open_socket()
    if sock is None:
        return

    async with httpx.AsyncClient(timeout=5, headers=headers) as client:
        while True:
            if stop_event.is_set():
                try:
                    sock.close()
                except Exception:
                    pass
                print("[bacnet-sniff] pause (port cédé au worker)", flush=True)
                while stop_event.is_set():
                    await asyncio.sleep(0.3)
                print("[bacnet-sniff] reprise", flush=True)
                sock = _open_socket()
                if sock is None:
                    return

            try:
                data, peer = await asyncio.wait_for(
                    asyncio.to_thread(_recv_one, sock), timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                print(f"[bacnet-sniff] recv erreur: {exc}", flush=True)
                await asyncio.sleep(1)
                continue

            if not data:
                continue

            state["frames"] = state.get("frames", 0) + 1

            try:
                await _handle_frame(client, api_url, data, peer, decode_frame)
            except Exception as exc:
                print(f"[bacnet-sniff] handle_frame erreur: {exc}", flush=True)
                if BACNET_SNIFF_DEBUG:
                    traceback.print_exc()


def _open_socket() -> socket.socket | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", BACNET_SNIFF_PORT))
        sock.settimeout(1.0)
        return sock
    except OSError as exc:
        print(f"[bacnet-sniff] bind {BACNET_SNIFF_PORT} failed: {exc}", flush=True)
        return None


def _recv_one(sock: socket.socket) -> tuple[bytes, tuple[str, int]]:
    return sock.recvfrom(4096)


async def _handle_frame(client, api_url: str, data: bytes, peer, decode_frame):
    src_ip, src_port = peer
    ts = datetime.now(timezone.utc).isoformat()

    if decode_frame is None:
        await client.post(
            f"{api_url}/bacnet/collector/frame",
            data={"src_ip": src_ip, "src_port": str(src_port),
                  "dst_ip": "0.0.0.0", "dst_port": str(BACNET_SNIFF_PORT),
                  "raw_hex": data.hex(), "ts": ts},
        )
        return

    try:
        decoded = decode_frame(data, src_ip=src_ip, src_port=src_port)
    except Exception as exc:
        if BACNET_SNIFF_DEBUG:
            print(f"[bacnet-sniff] decode_frame failed: {exc}", flush=True)
        decoded = {"raw_hex": data.hex()}

    payload = {
        "src_ip": src_ip,
        "src_port": str(src_port),
        "dst_ip": "0.0.0.0",
        "dst_port": str(BACNET_SNIFF_PORT),
        "raw_hex": decoded.get("raw_hex", data.hex()),
        "ts": ts,
        "bvlc_function": str(decoded.get("bvlc_function", "") or ""),
        "apdu_type": str(decoded.get("apdu_type", "") or ""),
        "service": str(decoded.get("service", "") or ""),
        "invoke_id": str(decoded.get("invoke_id", "") or ""),
        "object_ref": str(decoded.get("object_ref", "") or ""),
        "property": str(decoded.get("property", "") or ""),
        "value": str(decoded.get("value", "") or ""),
        "unit": str(decoded.get("unit", "") or ""),
        "operation_detail": str(decoded.get("operation_detail", "") or ""),
    }

    value_num = decoded.get("value_num")
    if value_num is not None:
        payload["value_num"] = str(value_num)

    extra = decoded.get("extra")
    if isinstance(extra, dict):
        for k, v in extra.items():
            if v is not None:
                payload[f"extra_{k}"] = str(v)

    try:
        r = await client.post(f"{api_url}/bacnet/collector/frame", data=payload)
        if r.status_code >= 400 and BACNET_SNIFF_DEBUG:
            print(f"[bacnet-sniff] push {r.status_code}: {r.text[:200]}", flush=True)
    except Exception as exc:
        if BACNET_SNIFF_DEBUG:
            print(f"[bacnet-sniff] push failed: {exc}", flush=True)
