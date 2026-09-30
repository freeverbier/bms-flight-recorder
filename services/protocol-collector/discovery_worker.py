"""Worker discovery des objets BACnet — I/O sync via asyncio.to_thread."""
import asyncio
import socket
import time


async def run_discovery(job, client, api_url, headers, decode_frame, 
                        build_rpm, object_types, push_frame,
                        pick_interface, sniffer_stop_event):
    """Discovery des objets d'un device BACnet.
    Utilise sockets sync + asyncio.to_thread pour éviter les bugs asyncio Docker.
    """
    import re
    device_uuid = job.get("target", "")
    if not device_uuid or "-" not in device_uuid:
        return

    r = await client.get(f"{api_url}/bacnet/devices", headers=headers, timeout=5)
    devices = r.json()
    device = next((d for d in devices if d["id"] == device_uuid), None)
    if not device or not device.get("device_id"):
        return

    ip = device["ip_address"]
    device_instance = device["device_id"]
    bacnet_port = 47808
    iface = pick_interface(ip)
    bind_ip = iface["ip"] if iface else "192.168.0.147"

    # Pauser sniffer
    print(f"[bacnet-discovery] demande pause sniffer", flush=True)
    sniffer_stop_event.set()
    await asyncio.sleep(3.0)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind((bind_ip, bacnet_port))
        print(f"[bacnet-discovery] bind {bind_ip}:{bacnet_port} OK", flush=True)
    except OSError as exc:
        print(f"[bacnet-discovery] bind ECHOUE : {exc}", flush=True)
        sniffer_stop_event.clear()
        return
    sock.setblocking(True)

    def sync_send_recv(pkt, timeout):
        try:
            sock.settimeout(timeout)
            n = sock.sendto(pkt, (ip, bacnet_port))
            print(f"[bacnet-discovery] sendto {n}b -> {ip}:{bacnet_port}", flush=True)
        except Exception as exc:
            print(f"[bacnet-discovery] sendto EXCEPTION: {exc}", flush=True)
            return None, None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                sock.settimeout(max(0.1, deadline - time.time()))
                data, peer = sock.recvfrom(65536)
            except socket.timeout:
                return None, None
            if peer[0] == ip:
                return data, peer
        return None, None

    async def rpm(pkt, timeout=3.0):
        data, peer = await asyncio.to_thread(sync_send_recv, pkt, timeout)
        if data is None:
            return None
        d = decode_frame(data, src_ip=peer[0], src_port=peer[1])
        try:
            await push_frame(client, peer[0], peer[1], bind_ip, bacnet_port, d)
        except Exception as exc:
            print(f"[bacnet-discovery] push_frame failed: {exc}", flush=True)
        if d.get("apdu_type") == "Error":
            print(f"[bacnet-discovery] ERROR: {d.get('operation_detail')} hex={data.hex()}", flush=True)
        return d

    try:
        # 1. Count
        pkt = build_rpm(1, [{"obj_type": 8, "obj_instance": device_instance,
                             "properties": [{"id": 76, "index": 0}]}])
        print(f"[bacnet-discovery] {ip} device:{device_instance} -> RPM count", flush=True)
        d = await rpm(pkt, timeout=5.0)
        if not d or d.get("apdu_type") == "Error":
            print(f"[bacnet-discovery] count echec", flush=True)
            return
        count = 0
        try:
            count = int(d.get("value_num") or d.get("value") or 0)
        except (ValueError, TypeError):
            pass
        if count == 0:
            raw = d.get("raw_hex", "")
            m = re.search(r"4e21([0-9a-f]{2})", raw)
            if m:
                count = int(m.group(1), 16)
        print(f"[bacnet-discovery] count={count}", flush=True)
        if count <= 0 or count > 5000:
            return

        # 2. Batches array-index
        object_list = []
        invoke_id = 2
        for start in range(1, count + 1, 10):
            end = min(start + 9, count)
            props = [{"id": 76, "index": i} for i in range(start, end + 1)]
            pkt = build_rpm(invoke_id, [{"obj_type": 8, "obj_instance": device_instance,
                                          "properties": props}])
            invoke_id = ((invoke_id + 1) & 0xFF) or 1
            d = await rpm(pkt, timeout=3.0)
            if not d or d.get("apdu_type") == "Error":
                continue
            raw = d.get("raw_hex", "")
            batch = []
            for m in re.finditer(r"c4([0-9a-f]{8})", raw):
                raw_id = int(m.group(1), 16)
                otype = (raw_id >> 22) & 0x3FF
                inst = raw_id & 0x3FFFFF
                tname = object_types.get(otype, f"type-{otype}")
                batch.append({"type_name": tname, "instance": inst})
            print(f"[bacnet-discovery] batch {start}-{end}: {len(batch)} objs", flush=True)
            object_list.extend(batch)
            await asyncio.sleep(0.05)

        seen = set()
        unique = []
        for o in object_list:
            k = (o["type_name"], o["instance"])
            if k not in seen:
                seen.add(k)
                unique.append(o)
        print(f"[bacnet-discovery] {len(unique)} objets uniques", flush=True)

        # 3. Filter + RPM detail par objet
        type_rev = {v: k for k, v in object_types.items()}
        business = {"analog-input", "analog-output", "analog-value",
                    "binary-input", "binary-output", "binary-value",
                    "multi-state-input", "multi-state-output", "multi-state-value",
                    "accumulator", "pulse-converter", "loop", "trend-log"}
        filtered = [{**o, "type_int": type_rev.get(o["type_name"], -1)}
                    for o in unique
                    if o["type_name"] != "device" and o["type_name"] in business]
        print(f"[bacnet-discovery] {len(filtered)} objets metier", flush=True)

        for obj in filtered:
            if obj["type_int"] < 0:
                continue
            pkt = build_rpm(invoke_id, [{
                "obj_type": obj["type_int"], "obj_instance": obj["instance"],
                "property_ids": [77, 116, 28, 85],
            }])
            invoke_id = ((invoke_id + 1) & 0xFF) or 1
            await rpm(pkt, timeout=1.5)
            await asyncio.sleep(0.03)

        print(f"[bacnet-discovery] termine", flush=True)
    finally:
        sock.close()
        sniffer_stop_event.clear()
        print(f"[bacnet-discovery] port libere", flush=True)
