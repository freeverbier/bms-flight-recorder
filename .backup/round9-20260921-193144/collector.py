import asyncio
import os
import socket
import struct
import time
import json

import httpx

API = os.getenv("API_URL", "http://127.0.0.1:8080/api")
TOKEN = os.getenv("INTERNAL_TOKEN", "")
HEADERS = {"X-Internal-Token": TOKEN}


def config_of(item):
    config = item.get("config") or {}
    if isinstance(config, str):
        try:
            return json.loads(config)
        except json.JSONDecodeError:
            return {}
    return config


async def set_status(client, source_id, status, error=None):
    try:
        await client.patch(
            f"{API}/sources/{source_id}/status",
            headers=HEADERS,
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
                # BVLC Original-Broadcast-NPDU + NPDU + unconfirmed Who-Is.
                packet = bytes.fromhex("810b000c0120ffff00ff1008")
                await loop.sock_sendto(sock, packet, (source["host"], int(source["port"])))
                next_discovery = time.monotonic() + int(config_of(source).get("discovery_seconds", 300))
            try:
                await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), timeout=5)
                await set_status(client, source["id"], "online")
            except TimeoutError:
                pass


def decode_registers(registers, data_type, scale, config):
    byte_order = config.get("byte_order", "big")
    word_order = config.get("word_order", "big")
    words = list(registers)
    if word_order == "little" and len(words) > 1:
        words.reverse()
    raw = b"".join(struct.pack(">H", word) for word in words)
    if byte_order == "little":
        raw = b"".join(raw[i:i + 2][::-1] for i in range(0, len(raw), 2))
    formats = {"uint16": ">H", "int16": ">h", "uint32": ">I", "int32": ">i", "float32": ">f"}
    if data_type == "bool":
        return float(bool(registers[0]))
    return float(struct.unpack(formats[data_type], raw)[0]) * float(scale)


async def read_modbus(source, point, transaction_id):
    function = int(point.get("function_code") or 3)
    data_type = point.get("data_type") or "uint16"
    count = 2 if data_type in ("uint32", "int32", "float32") else 1
    unit_id = int(config_of(source).get("unit_id", 1))
    pdu = struct.pack(">BHH", function, int(point["address"]), count)
    request = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id) + pdu
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(source["host"], int(source["port"])), timeout=3
    )
    try:
        writer.write(request)
        await writer.drain()
        header = await asyncio.wait_for(reader.readexactly(7), timeout=3)
        rx_tid, protocol_id, length, _ = struct.unpack(">HHHB", header)
        if rx_tid != transaction_id or protocol_id != 0:
            raise ValueError("Réponse Modbus non corrélée")
        response = await asyncio.wait_for(reader.readexactly(length - 1), timeout=3)
        if response[0] & 0x80:
            raise ValueError(f"Exception Modbus {response[1]}")
        if response[0] != function or response[1] != count * 2:
            raise ValueError("Longueur Modbus inattendue")
        registers = struct.unpack(">" + "H" * count, response[2:2 + count * 2])
        return decode_registers(registers, data_type, point.get("scale", 1), config_of(point))
    finally:
        writer.close()
        await writer.wait_closed()


async def modbus_source(source):
    async with httpx.AsyncClient(timeout=10) as client:
        transaction_id = 1
        next_poll = {}
        while True:
            try:
                points = (await client.get(f"{API}/sources/{source['id']}/points")).json()
                enabled = [point for point in points if point.get("enabled")]
                if source["mode"] != "polling":
                    await set_status(client, source["id"], "online")
                    await asyncio.sleep(30)
                    continue
                for point in enabled:
                    now = time.monotonic()
                    if now < next_poll.get(point["id"], 0):
                        continue
                    value = await read_modbus(source, point, transaction_id)
                    transaction_id = transaction_id % 65535 + 1
                    await client.post(
                        f"{API}/collector/value", headers=HEADERS,
                        data={"source_id": source["id"], "protocol": "modbus",
                              "point_key": point["point_key"], "point_name": point["name"],
                              "value": value, "unit": point.get("unit") or "",
                              "quality": "good", "origin": "polling"},
                    )
                    next_poll[point["id"]] = now + int(point.get("poll_seconds") or 30)
                await set_status(client, source["id"], "online")
            except Exception as exc:
                await set_status(client, source["id"], "offline", str(exc)[:200])
            await asyncio.sleep(1)


async def run_source(source):
    while True:
        try:
            if source["protocol"] == "bacnet":
                await bacnet_source(source)
            else:
                await modbus_source(source)
        except Exception as exc:
            async with httpx.AsyncClient(timeout=10) as client:
                await set_status(client, source["id"], "offline", str(exc)[:200])
            await asyncio.sleep(15)


def bacnet_device_id(data):
    marker = data.find(b"\x10\x00\xc4")
    if marker < 0 or len(data) < marker + 7:
        return None
    object_id = int.from_bytes(data[marker + 3:marker + 7], "big")
    return object_id & 0x3FFFFF


async def scan_bacnet(job, client):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 0))
    sock.setblocking(False)
    loop = asyncio.get_running_loop()
    packet = bytes.fromhex("810b000c0120ffff00ff1008")
    await loop.sock_sendto(sock, packet, (job["target"], int(job["port"])))
    deadline = loop.time() + 5
    seen = set()
    while loop.time() < deadline:
        try:
            data, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), deadline - loop.time())
        except TimeoutError:
            break
        device_id = bacnet_device_id(data)
        key = f"{peer[0]}:{peer[1]}"
        if key in seen:
            continue
        seen.add(key)
        await client.post(f"{API}/collector/scans/{job['id']}/devices", headers=HEADERS, data={
            "protocol": "bacnet", "address": key,
            "name": f"BACnet Device {device_id}" if device_id is not None else "Équipement BACnet",
            "metadata": json.dumps({"device_id": device_id, "transport": "BACnet/IP"}),
        })
    sock.close()


async def scan_worker():
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response = await client.get(f"{API}/collector/scans/next", params={"protocol": "bacnet"}, headers=HEADERS)
                if response.status_code == 204:
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                job = response.json()
                try:
                    await scan_bacnet(job, client)
                    await client.patch(f"{API}/collector/scans/{job['id']}", headers=HEADERS, data={"status": "completed"})
                except Exception as exc:
                    await client.patch(f"{API}/collector/scans/{job['id']}", headers=HEADERS,
                                       data={"status": "failed", "error": str(exc)[:200]})
            except Exception as exc:
                print(f"BACnet scan: {exc}", flush=True)
                await asyncio.sleep(5)


async def sync_sources():
    tasks = {}
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                sources = (await client.get(f"{API}/sources")).json()
                active = {source["id"] for source in sources if source.get("enabled")}
                for source_id in list(tasks):
                    if source_id not in active:
                        tasks.pop(source_id).cancel()
                for source in sources:
                    if source.get("enabled") and source["id"] not in tasks:
                        tasks[source["id"]] = asyncio.create_task(run_source(source))
            except Exception as exc:
                print(f"source sync: {exc}", flush=True)
            await asyncio.sleep(30)


async def main():
    await asyncio.gather(sync_sources(), scan_worker())


if __name__ == "__main__":
    asyncio.run(main())
