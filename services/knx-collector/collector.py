import asyncio, hashlib, json, os, socket, struct, time
import httpx

API=os.getenv("API_URL","http://127.0.0.1:8080/api")
TOKEN=os.getenv("INTERNAL_TOKEN","")
SEEN={}

def ia(v): return f"{v>>12}.{(v>>8)&15}.{v&255}"
def ga(v): return f"{v>>11}/{(v>>8)&7}/{v&255}"

def parse_cemi(data):
    if len(data)<10 or data[0] not in (0x29,0x2e): return None
    i=2+data[1]
    if len(data)<i+8:return None
    ctrl2=data[i+1]; src=int.from_bytes(data[i+2:i+4],"big"); dst=int.from_bytes(data[i+4:i+6],"big")
    apdu=data[i+7:]
    apci=((apdu[0]&3)<<2)|((apdu[1]>>6)&3) if len(apdu)>1 else -1
    opname={0:"GroupValueRead",1:"GroupValueResponse",2:"GroupValueWrite"}.get(apci,"APCI")
    value=hex(apdu[1]&0x3f) if len(apdu)>1 else ""
    return ia(src), ga(dst) if ctrl2&0x80 else ia(dst), opname, value

async def post_telegram(client,gid,parsed,raw):
    now=time.monotonic(); key=hashlib.sha256(raw).digest()
    if key in SEEN and now-SEEN[key]<2: return
    SEEN[key]=now
    if len(SEEN)>10000:
        for old,timestamp in list(SEEN.items()):
            if now-timestamp>5: SEEN.pop(old,None)
    src,dst,apci,value=parsed
    await client.post(f"{API}/collector/telegram",headers={"X-Internal-Token":TOKEN},data={"gateway_id":gid,"source":src,"destination":dst,"apci":apci,"value":value,"raw_hex":raw.hex()})

async def routing_listener(gateway, client):
    group=gateway.get("multicast_group") or "224.0.23.12"
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); sock.bind(("",gateway["port"]))
    sock.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton(group)+socket.inet_aton("0.0.0.0"))
    sock.setblocking(False); loop=asyncio.get_running_loop()
    await client.patch(f"{API}/gateways/{gateway['id']}/status",headers={"X-Internal-Token":TOKEN},data={"status":"online"})
    while True:
        data,_=await loop.sock_recvfrom(sock,2048)
        if len(data)>=6 and data[2:4]==b"\x05\x30":
            parsed=parse_cemi(data[6:])
            if parsed: await post_telegram(client,gateway["id"],parsed,data)

async def tunneling_listener(gateway, client):
    # KNXnet/IP tunneling link-layer. Secure tunneling is intentionally rejected until a credential adapter is selected.
    if gateway.get("secure"):
        await client.patch(f"{API}/gateways/{gateway['id']}/status",headers={"X-Internal-Token":TOKEN},data={"status":"credential_required","error":"Adaptateur KNX IP Secure requis"})
        while True: await asyncio.sleep(300)
    loop=asyncio.get_running_loop(); sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.bind(("0.0.0.0",0)); sock.setblocking(False)
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); probe.connect((gateway["host"],gateway["port"])); local_ip=probe.getsockname()[0]; probe.close()
    local_port=sock.getsockname()[1]
    hpai=b"\x08\x01"+socket.inet_aton(local_ip)+struct.pack("!H",local_port)
    req=b"\x06\x10\x02\x05\x00\x1a"+hpai+hpai+b"\x04\x04\x02\x00"
    await loop.sock_sendto(sock,req,(gateway["host"],gateway["port"]))
    try: resp,_=await asyncio.wait_for(loop.sock_recvfrom(sock,2048),5)
    except TimeoutError: raise RuntimeError("Aucune réponse KNXnet/IP")
    if len(resp)<8 or resp[2:4]!=b"\x02\x06" or resp[7]!=0: raise RuntimeError(f"Connexion refusée ({resp[7] if len(resp)>7 else 'réponse invalide'})")
    channel=resp[6]; seq=0
    await client.patch(f"{API}/gateways/{gateway['id']}/status",headers={"X-Internal-Token":TOKEN},data={"status":"online"})
    while True:
        try: data,peer=await asyncio.wait_for(loop.sock_recvfrom(sock,2048),50)
        except TimeoutError:
            state=b"\x06\x10\x02\x07\x00\x10"+bytes([channel,0])+hpai
            await loop.sock_sendto(sock,state,(gateway["host"],gateway["port"])); continue
        if len(data)>=10 and data[2:4]==b"\x04\x20" and data[7]==channel:
            ack=b"\x06\x10\x04\x21\x00\x0a\x04"+bytes([channel,data[8],0])
            await loop.sock_sendto(sock,ack,peer)
            parsed=parse_cemi(data[10:])
            if parsed: await post_telegram(client,gateway["id"],parsed,data)
            seq=(seq+1)&255

async def run_gateway(gateway):
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                if gateway["mode"]=="routing": await routing_listener(gateway,client)
                else: await tunneling_listener(gateway,client)
            except Exception as exc:
                try: await client.patch(f"{API}/gateways/{gateway['id']}/status",headers={"X-Internal-Token":TOKEN},data={"status":"offline","error":str(exc)[:200]})
                except Exception: pass
                await asyncio.sleep(15)

def parse_search_response(data, peer):
    result={"address":f"{peer[0]}:{peer[1]}","name":"Gateway KNXnet/IP","metadata":{"transport":"KNXnet/IP"}}
    if len(data)>=68 and data[2:4]==b"\x02\x02" and data[15]==1:
        individual=int.from_bytes(data[18:20],"big")
        name=data[38:68].split(b"\x00",1)[0].decode("latin-1",errors="replace").strip()
        result["name"]=name or result["name"]
        result["metadata"]["individual_address"]=ia(individual)
    return result

async def scan_knx(job,client):
    target=job.get("target") or "224.0.23.12"; target_port=int(job.get("port") or 3671)
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(("0.0.0.0",0)); sock.setblocking(False)
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); probe.connect((target,target_port)); local_ip=probe.getsockname()[0]; probe.close()
    hpai=b"\x08\x01"+socket.inet_aton(local_ip)+struct.pack("!H",sock.getsockname()[1])
    request=b"\x06\x10\x02\x01\x00\x0e"+hpai
    loop=asyncio.get_running_loop(); await loop.sock_sendto(sock,request,(target,target_port))
    deadline=loop.time()+5; seen=set()
    while loop.time()<deadline:
        try: data,peer=await asyncio.wait_for(loop.sock_recvfrom(sock,4096),deadline-loop.time())
        except TimeoutError: break
        if len(data)<14 or data[2:4]!=b"\x02\x02": continue
        device=parse_search_response(data,peer)
        if device["address"] in seen: continue
        seen.add(device["address"])
        await client.post(f"{API}/collector/scans/{job['id']}/devices",headers={"X-Internal-Token":TOKEN},data={"protocol":"knx","address":device["address"],"name":device["name"],"metadata":json.dumps(device["metadata"])})
    sock.close()

async def scan_worker():
    headers={"X-Internal-Token":TOKEN}
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                response=await client.get(f"{API}/collector/scans/next",params={"protocol":"knx"},headers=headers)
                if response.status_code==204: await asyncio.sleep(3); continue
                response.raise_for_status(); job=response.json()
                try:
                    await scan_knx(job,client)
                    await client.patch(f"{API}/collector/scans/{job['id']}",headers=headers,data={"status":"completed"})
                except Exception as exc:
                    await client.patch(f"{API}/collector/scans/{job['id']}",headers=headers,data={"status":"failed","error":str(exc)[:200]})
            except Exception as exc:
                print(f"KNX scan: {exc}",flush=True); await asyncio.sleep(5)

async def sync_gateways():
    tasks={}
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                gateways=(await client.get(f"{API}/gateways")).json()
                active={g["id"] for g in gateways if g.get("enabled")}
                for gid in list(tasks):
                    if gid not in active: tasks.pop(gid).cancel()
                for g in gateways:
                    if g.get("enabled") and g["id"] not in tasks: tasks[g["id"]]=asyncio.create_task(run_gateway(g))
            except Exception as exc: print(f"gateway sync: {exc}",flush=True)
            await asyncio.sleep(30)
async def main(): await asyncio.gather(sync_gateways(),scan_worker())
if __name__=="__main__": asyncio.run(main())
