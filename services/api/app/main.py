import base64
import csv
import io
import json
import os
import uuid
from pathlib import Path
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

DATABASE_URL = os.environ["DATABASE_URL"]
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "bms")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "telemetry")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")
DEMO_DATA = os.getenv("DEMO_DATA", "true").lower() == "true"


def make_fernet() -> Fernet:
    raw = os.environ["APP_MASTER_KEY"].encode()
    padded = raw + b"=" * (-len(raw) % 4)
    key = base64.urlsafe_b64encode(base64.urlsafe_b64decode(padded))
    return Fernet(key)


fernet = make_fernet()

SCHEMA = """
CREATE TABLE IF NOT EXISTS gateways (
  id UUID PRIMARY KEY, name TEXT NOT NULL, site TEXT NOT NULL, line TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('routing','tunneling')),
  host TEXT, port INTEGER NOT NULL DEFAULT 3671, multicast_group TEXT,
  secure BOOLEAN NOT NULL DEFAULT FALSE, credential_id UUID,
  enabled BOOLEAN NOT NULL DEFAULT TRUE, status TEXT NOT NULL DEFAULT 'configured',
  last_seen TIMESTAMPTZ, last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS credentials (
  id UUID PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
  encrypted_payload BYTEA NOT NULL, fingerprint TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS collector_events (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, gateway_id UUID,
  source TEXT, destination TEXT, apci TEXT, value TEXT, raw_hex TEXT
);
CREATE TABLE IF NOT EXISTS protocol_sources (
  id UUID PRIMARY KEY, protocol TEXT NOT NULL CHECK (protocol IN ('bacnet','modbus')),
  name TEXT NOT NULL, site TEXT NOT NULL, mode TEXT NOT NULL,
  host TEXT, port INTEGER NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL DEFAULT 'configured', last_seen TIMESTAMPTZ,
  last_error TEXT, config JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS data_points (
  id UUID PRIMARY KEY, source_id UUID NOT NULL REFERENCES protocol_sources(id) ON DELETE CASCADE,
  name TEXT NOT NULL, point_key TEXT NOT NULL, address INTEGER,
  function_code INTEGER, data_type TEXT, scale DOUBLE PRECISION NOT NULL DEFAULT 1,
  unit TEXT, poll_seconds INTEGER NOT NULL DEFAULT 30, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  config JSONB NOT NULL DEFAULT '{}'::jsonb, UNIQUE(source_id, point_key)
);
CREATE TABLE IF NOT EXISTS telemetry_events (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(), source_id UUID,
  protocol TEXT NOT NULL, point_key TEXT NOT NULL, point_name TEXT,
  value DOUBLE PRECISION, value_text TEXT, unit TEXT, quality TEXT NOT NULL,
  origin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_jobs (
  id UUID PRIMARY KEY, protocol TEXT NOT NULL CHECK (protocol IN ('bacnet','knx')),
  mode TEXT NOT NULL, target TEXT NOT NULL, port INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, last_error TEXT
);
CREATE TABLE IF NOT EXISTS discovered_devices (
  id UUID PRIMARY KEY, scan_id UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
  protocol TEXT NOT NULL, address TEXT NOT NULL, name TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb, last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(scan_id, protocol, address)
);
"""

DEMO_FRAMES = [
    {"ts":"2026-09-05T08:42:17.238Z","protocol":"KNX","src":"1.1.42","dst":"2/3/17","operation":"GroupValueWrite","value":"42 %","frame_len":23,"status":"ok"},
    {"ts":"2026-09-05T08:42:16.904Z","protocol":"BACnet","src":"192.168.10.21","dst":"192.168.10.5","operation":"ConfirmedCOVNotification","value":"21.7 °C","frame_len":118,"status":"ok"},
    {"ts":"2026-09-05T08:42:16.112Z","protocol":"Modbus","src":"192.168.20.10","dst":"192.168.20.31","operation":"ReadHoldingRegisters","value":"40042 → 215","frame_len":66,"status":"ok"},
    {"ts":"2026-09-05T08:42:15.443Z","protocol":"KNX Secure","src":"1.2.18","dst":"3/1/4","operation":"GroupValueWrite","value":"ON","frame_len":41,"status":"decrypted"},
    {"ts":"2026-09-05T08:42:14.082Z","protocol":"BACnet/SC","src":"hub-a","dst":"ahu-04","operation":"TLS application data","value":"Opaque","frame_len":283,"status":"encrypted"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with app.state.db.acquire() as conn:
        await conn.execute(SCHEMA)
        if DEMO_DATA:
            count = await conn.fetchval("SELECT count(*) FROM gateways")
            if count == 0:
                await conn.execute("""INSERT INTO gateways(id,name,site,line,mode,host,port,multicast_group,secure,status,last_seen)
                VALUES($1,'Routeur IP — Bâtiment A','Campus Genève','1.1','routing',NULL,3671,'224.0.23.12',false,'online',now()),
                ($2,'Interface chaufferie','Campus Genève','1.2','tunneling','192.168.12.20',3671,NULL,true,'online',now()),
                ($3,'Interface bureaux','Campus Genève','2.1','tunneling','192.168.21.15',3671,NULL,false,'degraded',now()-interval '4 minutes')""",
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
            source_count = await conn.fetchval("SELECT count(*) FROM protocol_sources")
            if source_count == 0:
                bacnet_id, modbus_id = uuid.uuid4(), uuid.uuid4()
                await conn.execute("""INSERT INTO protocol_sources(id,protocol,name,site,mode,host,port,status,last_seen,config)
                  VALUES($1,'bacnet','Réseau BACnet CVC','Campus Genève','passive','192.168.10.255',47808,'online',now(),'{"network": 10, "discovery": false}'),
                        ($2,'modbus','Automate chaufferie','Campus Genève','polling','192.168.20.31',502,'online',now(),'{"unit_id": 1}')""", bacnet_id, modbus_id)
                await conn.execute("""INSERT INTO data_points(id,source_id,name,point_key,address,function_code,data_type,scale,unit,poll_seconds)
                  VALUES($1,$2,'Température départ','hr-42',42,3,'int16',0.1,'°C',15),
                        ($3,$2,'Consigne chaudière','hr-44',44,3,'uint16',0.1,'°C',30)""", uuid.uuid4(), modbus_id, uuid.uuid4())
    yield
    await app.state.db.close()


app = FastAPI(title="BMS Flight Recorder API", version="0.1.0", lifespan=lifespan)


class GatewayIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    site: str = Field(min_length=2, max_length=100)
    line: str = Field(min_length=1, max_length=20)
    mode: str = Field(pattern="^(routing|tunneling)$")
    host: str | None = None
    port: int = Field(default=3671, ge=1, le=65535)
    multicast_group: str | None = "224.0.23.12"
    secure: bool = False
    credential_id: uuid.UUID | None = None
    enabled: bool = True


class SourceIn(BaseModel):
    protocol: str = Field(pattern="^(bacnet|modbus)$")
    name: str = Field(min_length=2, max_length=100)
    site: str = Field(min_length=2, max_length=100)
    mode: str = Field(pattern="^(passive|discovery|polling)$")
    host: str | None = None
    port: int = Field(ge=1, le=65535)
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class PointIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    point_key: str = Field(min_length=1, max_length=100)
    address: int | None = Field(default=None, ge=0, le=65535)
    function_code: int | None = Field(default=3)
    data_type: str | None = Field(default="uint16", pattern="^(uint16|int16|uint32|int32|float32|bool)$")
    scale: float = 1
    unit: str | None = None
    poll_seconds: int = Field(default=30, ge=2, le=86400)
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class ScanIn(BaseModel):
    protocol: str = Field(pattern="^(bacnet|knx)$")
    mode: str = Field(pattern="^(bacnet_whois|knx_search)$")
    target: str
    port: int = Field(default=3671, ge=1, le=65535)


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc)}


@app.get("/summary")
async def summary():
    return {"packets_per_second": 184, "frames_today": 2841671, "active_gateways": 2,
            "packet_loss_percent": 0.02, "protocols": [
              {"name":"KNX","percent":44,"count":1249920}, {"name":"BACnet","percent":31,"count":881041},
              {"name":"Modbus","percent":18,"count":511501}, {"name":"Autres","percent":7,"count":199209}]}


@app.get("/frames")
async def frames(limit: int = 50):
    try:
        query = "SELECT ts,protocol,src,dst,operation,value,frame_len,status FROM bms.frames ORDER BY ts DESC LIMIT %d FORMAT JSON" % min(limit, 500)
        async with httpx.AsyncClient(timeout=2) as client:
            res = await client.post(CLICKHOUSE_URL, content=query)
            if res.is_success and res.json().get("data"):
                return res.json()["data"]
    except Exception:
        pass
    return DEMO_FRAMES[:limit]


@app.get("/gateways")
async def gateways():
    rows = await app.state.db.fetch("SELECT * FROM gateways ORDER BY site,name")
    return [dict(row) for row in rows]


@app.get("/knx-monitor", response_class=HTMLResponse)
async def knx_monitor():
    return Path(__file__).with_name("knx-monitor.html").read_text(encoding="utf-8")


@app.get("/knx/telegrams")
async def knx_telegrams(gateway_id: uuid.UUID, after: int = 0):
    if after < 0:
        raise HTTPException(422, "Curseur invalide")
    if after == 0:
        rows = await app.state.db.fetch("""SELECT * FROM (
          SELECT * FROM collector_events WHERE gateway_id=$1 ORDER BY id DESC LIMIT 200
          ) recent ORDER BY id""", gateway_id)
    else:
        rows = await app.state.db.fetch("SELECT * FROM collector_events WHERE gateway_id=$1 AND id>$2 ORDER BY id LIMIT 200", gateway_id, after)
    return [dict(row) for row in rows]


@app.get("/sources")
async def sources(protocol: str | None = None):
    if protocol:
        rows = await app.state.db.fetch("SELECT * FROM protocol_sources WHERE protocol=$1 ORDER BY site,name", protocol)
    else:
        rows = await app.state.db.fetch("SELECT * FROM protocol_sources ORDER BY protocol,site,name")
    return [dict(row) for row in rows]


@app.post("/sources", status_code=201)
async def create_source(payload: SourceIn):
    if payload.protocol == "bacnet" and payload.mode == "polling":
        raise HTTPException(422, "Le polling Modbus n'est pas un mode BACnet")
    if payload.protocol == "modbus" and payload.mode == "discovery":
        raise HTTPException(422, "La découverte Who-Is n'est pas un mode Modbus")
    if payload.mode in ("discovery", "polling") and not payload.host:
        raise HTTPException(422, "Une adresse réseau est requise pour ce mode")
    sid = uuid.uuid4()
    await app.state.db.execute("""INSERT INTO protocol_sources(id,protocol,name,site,mode,host,port,enabled,config)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""", sid, payload.protocol, payload.name,
      payload.site, payload.mode, payload.host, payload.port, payload.enabled, json.dumps(payload.config))
    return {"id": sid, "status": "configured", **payload.model_dump()}


@app.patch("/sources/{source_id}/status")
async def source_status(source_id: uuid.UUID, status: str = Form(...), error: str | None = Form(None),
                        x_internal_token: str = Header("")):
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")
    await app.state.db.execute("UPDATE protocol_sources SET status=$2,last_error=$3,last_seen=CASE WHEN $2='online' THEN now() ELSE last_seen END WHERE id=$1", source_id, status, error)
    return {"ok": True}


@app.get("/sources/{source_id}/points")
async def points(source_id: uuid.UUID):
    rows = await app.state.db.fetch("SELECT * FROM data_points WHERE source_id=$1 ORDER BY address,name", source_id)
    return [dict(row) for row in rows]


@app.post("/sources/{source_id}/points", status_code=201)
async def create_point(source_id: uuid.UUID, payload: PointIn):
    if not await app.state.db.fetchval("SELECT EXISTS(SELECT 1 FROM protocol_sources WHERE id=$1)", source_id):
        raise HTTPException(404, "Source inconnue")
    pid = uuid.uuid4()
    await app.state.db.execute("""INSERT INTO data_points(id,source_id,name,point_key,address,function_code,data_type,scale,unit,poll_seconds,enabled,config)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)""", pid,source_id,payload.name,payload.point_key,
      payload.address,payload.function_code,payload.data_type,payload.scale,payload.unit,payload.poll_seconds,payload.enabled,json.dumps(payload.config))
    return {"id": pid, "source_id": source_id, **payload.model_dump()}


@app.get("/values")
async def values(limit: int = 100):
    safe_limit = min(limit, 1000)
    rows = await app.state.db.fetch("SELECT * FROM telemetry_events ORDER BY ts DESC LIMIT $1", safe_limit)
    result = [dict(row) for row in rows]
    if INFLUX_TOKEN and len(result) < safe_limit:
        flux = f'''from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == "building_point" and r._field == "value")
          |> group(columns: ["protocol", "point_id"])
          |> last()
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {safe_limit - len(result)})'''
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.post(
                    f"{INFLUX_URL}/api/v2/query", params={"org": INFLUX_ORG},
                    headers={"Authorization": f"Token {INFLUX_TOKEN}", "Accept": "application/csv"},
                    json={"query": flux, "type": "flux"},
                )
                response.raise_for_status()
            clean_csv = "\n".join(line for line in response.text.splitlines() if line and not line.startswith("#"))
            for item in csv.DictReader(io.StringIO(clean_csv)):
                if item.get("_time") == "_time" or not item.get("_value"):
                    continue
                result.append({"ts": item.get("_time"), "protocol": item.get("protocol", ""),
                    "point_key": item.get("point_id", ""), "point_name": item.get("point_id", ""),
                    "value": float(item["_value"]), "unit": "", "quality": "good", "origin": "passive"})
        except Exception:
            pass
    if result:
        return result[:safe_limit]
    return [
      {"ts":"2026-09-05T08:42:16.904Z","protocol":"bacnet","point_key":"analog-input:3.present-value","point_name":"Température soufflage","value":21.7,"unit":"°C","quality":"good","origin":"passive"},
      {"ts":"2026-09-05T08:42:16.112Z","protocol":"modbus","point_key":"hr-42","point_name":"Température départ","value":21.5,"unit":"°C","quality":"good","origin":"polling"},
    ]


@app.get("/scans")
async def scans():
    rows = await app.state.db.fetch("""SELECT s.*,
      (SELECT count(*) FROM discovered_devices d WHERE d.scan_id=s.id) AS device_count
      FROM scan_jobs s ORDER BY created_at DESC LIMIT 50""")
    return [dict(row) for row in rows]


@app.post("/scans", status_code=201)
async def create_scan(payload: ScanIn):
    expected = "bacnet_whois" if payload.protocol == "bacnet" else "knx_search"
    if payload.mode != expected:
        raise HTTPException(422, "Mode de scan incompatible avec le protocole")
    sid = uuid.uuid4()
    await app.state.db.execute("INSERT INTO scan_jobs(id,protocol,mode,target,port) VALUES($1,$2,$3,$4,$5)",
                               sid, payload.protocol, payload.mode, payload.target, payload.port)
    return {"id": sid, "status": "queued", "device_count": 0, **payload.model_dump()}


@app.get("/scans/{scan_id}/devices")
async def scan_devices(scan_id: uuid.UUID):
    rows = await app.state.db.fetch("SELECT * FROM discovered_devices WHERE scan_id=$1 ORDER BY protocol,address", scan_id)
    return [dict(row) for row in rows]


def require_internal(token: str):
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")


@app.get("/collector/scans/next")
async def next_scan(protocol: str, x_internal_token: str = Header("")):
    require_internal(x_internal_token)
    async with app.state.db.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""SELECT * FROM scan_jobs WHERE protocol=$1 AND status='queued'
              ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""", protocol)
            if not row:
                return Response(status_code=204)
            await conn.execute("UPDATE scan_jobs SET status='running',started_at=now() WHERE id=$1", row["id"])
    return dict(row) | {"status": "running"}


@app.post("/collector/scans/{scan_id}/devices", status_code=202)
async def add_scan_device(scan_id: uuid.UUID, protocol: str = Form(...), address: str = Form(...),
                          name: str = Form(""), metadata: str = Form("{}"), x_internal_token: str = Header("")):
    require_internal(x_internal_token)
    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(422, "Métadonnées JSON invalides")
    await app.state.db.execute("""INSERT INTO discovered_devices(id,scan_id,protocol,address,name,metadata)
      VALUES($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT(scan_id,protocol,address)
      DO UPDATE SET name=excluded.name,metadata=excluded.metadata,last_seen=now()""",
      uuid.uuid4(), scan_id, protocol, address, name, json.dumps(parsed))
    return {"accepted": True}


@app.patch("/collector/scans/{scan_id}")
async def finish_scan(scan_id: uuid.UUID, status: str = Form(...), error: str = Form(""),
                      x_internal_token: str = Header("")):
    require_internal(x_internal_token)
    if status not in ("completed", "failed"):
        raise HTTPException(422, "État final invalide")
    await app.state.db.execute("UPDATE scan_jobs SET status=$2,last_error=$3,completed_at=now() WHERE id=$1",
                               scan_id, status, error or None)
    return {"ok": True}


@app.post("/collector/value", status_code=202)
async def collector_value(source_id: uuid.UUID | None = Form(None), protocol: str = Form(...), point_key: str = Form(...),
                          point_name: str = Form(""), value: float | None = Form(None), value_text: str = Form(""),
                          unit: str = Form(""), quality: str = Form("good"), origin: str = Form("passive"),
                          x_internal_token: str = Header("")):
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")
    await app.state.db.execute("""INSERT INTO telemetry_events(source_id,protocol,point_key,point_name,value,value_text,unit,quality,origin)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",source_id,protocol,point_key,point_name,value,value_text,unit,quality,origin)
    return {"accepted": True}


@app.post("/gateways", status_code=201)
async def create_gateway(payload: GatewayIn):
    if payload.mode == "tunneling" and not payload.host:
        raise HTTPException(422, "Une adresse IP est requise en mode tunneling")
    gid = uuid.uuid4()
    await app.state.db.execute("""INSERT INTO gateways(id,name,site,line,mode,host,port,multicast_group,secure,credential_id,enabled)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""", gid, payload.name, payload.site, payload.line,
      payload.mode, payload.host, payload.port, payload.multicast_group, payload.secure, payload.credential_id, payload.enabled)
    return {"id": gid, **payload.model_dump()}


@app.patch("/gateways/{gateway_id}/status")
async def gateway_status(gateway_id: uuid.UUID, status: str = Form(...), error: str | None = Form(None), x_internal_token: str = Header("")):
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")
    await app.state.db.execute("UPDATE gateways SET status=$2,last_error=$3,last_seen=CASE WHEN $2='online' THEN now() ELSE last_seen END WHERE id=$1", gateway_id, status, error)
    return {"ok": True}


@app.post("/collector/telegram", status_code=202)
async def telegram(gateway_id: uuid.UUID = Form(...), source: str = Form(...), destination: str = Form(...),
                   apci: str = Form(...), value: str = Form(""), raw_hex: str = Form(...), x_internal_token: str = Header("")):
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")
    await app.state.db.execute("INSERT INTO collector_events(ts,gateway_id,source,destination,apci,value,raw_hex) VALUES(now(),$1,$2,$3,$4,$5,$6)", gateway_id, source, destination, apci, value, raw_hex)
    return {"accepted": True}


@app.post("/credentials", status_code=201)
async def credential(name: str = Form(...), kind: str = Form(...), scope: str = Form(...),
                     password: str = Form(""), file: UploadFile | None = File(None)):
    content = await file.read() if file else b""
    envelope = json.dumps({"password": password, "filename": file.filename if file else None,
                           "content_b64": base64.b64encode(content).decode()}).encode()
    cid = uuid.uuid4()
    fingerprint = __import__("hashlib").sha256(content).hexdigest()[:16] if content else None
    await app.state.db.execute("INSERT INTO credentials(id,name,kind,scope,encrypted_payload,fingerprint) VALUES($1,$2,$3,$4,$5,$6)", cid,name,kind,scope,fernet.encrypt(envelope),fingerprint)
    return {"id": cid, "name": name, "kind": kind, "scope": scope, "fingerprint": fingerprint}


@app.get("/credentials")
async def credentials():
    rows = await app.state.db.fetch("SELECT id,name,kind,scope,fingerprint,created_at FROM credentials ORDER BY created_at DESC")
    return [dict(row) for row in rows]
