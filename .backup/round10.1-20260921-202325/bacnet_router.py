"""
Routes BACnet de l'API — Round 10.

Miroir de knx_router.py :
- POST /bacnet/collector/frame     : ingestion depuis protocol-collector (auth interne)
- GET  /bacnet/stream              : SSE stream temps réel
- GET  /bacnet/devices             : liste devices auto-découverts
- GET  /bacnet/objects             : liste objets auto-découverts (sémantique éditable)
- PATCH /bacnet/objects/{id}       : override name/unit/description manuel
- GET  /bacnet/history             : historique bucketisé (via knx_history réutilisé)

Les tables bacnet_devices et bacnet_objects sont peuplées automatiquement à partir
des I-Am (device_id), des ReadProperty/RPM ACK (objets présents dans la réponse),
et des COV Notification.

Les frames décodées sont écrites dans bms.frames avec protocol='bacnet' — même
schéma que le KNX. Ce qui rend les endpoints historique et stream déjà réutilisables.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Body, Form, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/bacnet", tags=["bacnet"])

CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")


# ---------------------------------------------------------------------------
# Migrations schéma Postgres
# ---------------------------------------------------------------------------

BACNET_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bacnet_devices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ip_address    TEXT NOT NULL,
    port          INTEGER NOT NULL DEFAULT 47808,
    device_id     INTEGER,
    vendor_id     INTEGER,
    max_apdu      INTEGER,
    segmentation  TEXT,
    name          TEXT,
    description   TEXT,
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ip_address, port)
);

CREATE INDEX IF NOT EXISTS idx_bacnet_devices_device_id
    ON bacnet_devices (device_id);

CREATE TABLE IF NOT EXISTS bacnet_objects (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id         UUID NOT NULL REFERENCES bacnet_devices(id) ON DELETE CASCADE,
    object_type       INTEGER NOT NULL,
    object_instance   INTEGER NOT NULL,
    object_ref        TEXT NOT NULL,      -- "analog-input:5"
    name              TEXT,
    description       TEXT,
    unit              TEXT,
    -- Sémantique éditable manuellement (comme knx_group_addresses Round 7)
    name_imported     TEXT,
    unit_imported     TEXT,
    description_imported TEXT,
    source            TEXT NOT NULL DEFAULT 'sniffed',  -- sniffed | manual
    last_seen         TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_seen        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, object_type, object_instance)
);

CREATE INDEX IF NOT EXISTS idx_bacnet_objects_ref
    ON bacnet_objects (object_ref);
"""


async def apply_bacnet_schema(conn) -> None:
    await conn.execute(BACNET_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# ClickHouse writer partagé (mirror knx_router)
# ---------------------------------------------------------------------------

class ClickHouseWriter:
    def __init__(self, url: str, flush_interval_s: float = 0.5, max_batch: int = 100):
        self._url = url
        self._flush_interval = flush_interval_s
        self._max_batch = max_batch
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._client = httpx.AsyncClient(timeout=10)
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush()
        if self._client:
            await self._client.aclose()

    async def push(self, row: dict):
        async with self._lock:
            self._buffer.append(row)
            if len(self._buffer) >= self._max_batch:
                await self._flush_locked()

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(self._flush_interval)
            async with self._lock:
                await self._flush_locked()

    async def _flush(self):
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self):
        if not self._buffer or not self._client:
            return
        rows = self._buffer
        self._buffer = []
        body = "\n".join(json.dumps(r, separators=(",", ":")) for r in rows)
        try:
            r = await self._client.post(
                self._url,
                params={"query": "INSERT INTO bms.frames FORMAT JSONEachRow"},
                content=body,
            )
            r.raise_for_status()
        except Exception as exc:
            print(f"[bacnet_router] ClickHouse insert failed: {exc}", file=sys.stderr)


ch_writer = ClickHouseWriter(CLICKHOUSE_URL)


# ---------------------------------------------------------------------------
# SSE bus
# ---------------------------------------------------------------------------

class FrameBus:
    def __init__(self, backlog: int = 200, queue_max: int = 500):
        self._history: deque[dict] = deque(maxlen=backlog)
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._queue_max = queue_max
        self._lock = asyncio.Lock()

    async def subscribe(self):
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._queue_max)
        async with self._lock:
            self._subscribers.add(queue)
            history = list(self._history)
        return queue, history

    async def unsubscribe(self, queue):
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, message: dict):
        async with self._lock:
            self._history.append(message)
            dead = []
            for queue in self._subscribers:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)


bus = FrameBus()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BacnetObjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=20)


# ---------------------------------------------------------------------------
# Ingestion — endpoint interne appelé par protocol-collector
# ---------------------------------------------------------------------------

@router.post("/collector/frame", status_code=202)
async def collector_frame(
    request: Request,
    gateway_id: str = Form(...),
    src_ip: str = Form(...),
    src_port: int = Form(...),
    dst_ip: str = Form(""),
    dst_port: int = Form(47808),
    bvlc_function: str = Form(""),
    apdu_type: str = Form(""),
    service: str = Form(""),
    invoke_id: str = Form(""),
    object_ref: str = Form(""),
    property: str = Form(""),  # noqa: A002
    value: str = Form(""),
    value_num: str = Form(""),
    unit: str = Form(""),
    operation_detail: str = Form(""),
    raw_hex: str = Form(...),
    extra_json: str = Form("{}"),
    x_internal_token: str = Header(""),
):
    from .main import INTERNAL_TOKEN
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")

    ts = datetime.now(timezone.utc)

    # Cast value_num
    vnum: Optional[float] = None
    if value_num:
        try:
            vnum = float(value_num)
        except ValueError:
            vnum = None

    try:
        extra = json.loads(extra_json) if extra_json else {}
    except json.JSONDecodeError:
        extra = {}
    extra_cast = {str(k): str(v) for k, v in extra.items()} if isinstance(extra, dict) else {}

    # Auto-discovery : peupler bacnet_devices et bacnet_objects
    await _autodiscover(request.app.state.db, src_ip, src_port,
                        service, object_ref, property, unit, value, vnum, extra_cast)

    # Point name : chercher dans bacnet_objects si connu
    point_name = ""
    if object_ref:
        row = await request.app.state.db.fetchrow(
            "SELECT name FROM bacnet_objects WHERE object_ref=$1 LIMIT 1",
            object_ref,
        )
        if row and row["name"]:
            point_name = row["name"]

    # Écriture ClickHouse (schéma bms.frames identique au KNX)
    row = {
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "protocol": "bacnet",
        "source_kind": "sniffer",
        "source_id": gateway_id,
        "src": f"{src_ip}:{src_port}",
        "dst": object_ref or f"{dst_ip}:{dst_port}",
        "operation": service or apdu_type or bvlc_function,
        "value": value,
        "value_num": vnum,
        "unit": unit,
        "dpt": "",  # BACnet n'a pas de DPT — laisser vide
        "point_name": point_name,
        "priority": str(extra_cast.get("npdu_priority", "")),
        "hop_count": 0,
        "raw_hex": raw_hex,
        "frame_len": len(raw_hex) // 2,
        "status": "ok",
        "apci_category": _classify_service(service),
        "tpci": apdu_type,
        "extra": extra_cast,
    }
    await ch_writer.push(row)

    # SSE broadcast
    message = {
        "ts": ts.isoformat(),
        "gateway_id": gateway_id,
        "src": f"{src_ip}:{src_port}",
        "dst": object_ref or f"{dst_ip}:{dst_port}",
        "bvlc_function": bvlc_function,
        "apdu_type": apdu_type,
        "service": service,
        "invoke_id": invoke_id,
        "object_ref": object_ref,
        "property": property,
        "value": value,
        "value_num": vnum,
        "unit": unit,
        "point_name": point_name,
        "operation_detail": operation_detail,
        "raw_hex": raw_hex,
        "extra": extra_cast,
    }
    await bus.publish(message)
    return {"accepted": True}


def _classify_service(service: str) -> str:
    """Catégorise un service BACnet pour le champ apci_category (réutilisé de KNX)."""
    if not service:
        return "unknown"
    runtime = {"iAm", "whoIs", "readProperty", "readPropertyMultiple", "writeProperty",
               "unconfirmedCOVNotification", "confirmedCOVNotification",
               "subscribeCOV", "subscribeCOVProperty", "writeGroup"}
    device = {"deviceCommunicationControl", "reinitializeDevice", "whoHas", "iHave",
              "timeSynchronization", "utcTimeSynchronization"}
    memory = {"atomicReadFile", "atomicWriteFile", "createObject", "deleteObject"}
    diag = {"getAlarmSummary", "getEnrollmentSummary", "getEventInformation",
            "confirmedEventNotification", "unconfirmedEventNotification"}
    if service in runtime:
        return "runtime"
    if service in device:
        return "device"
    if service in memory:
        return "memory"
    if service in diag:
        return "diagnostic"
    return "other"


async def _autodiscover(db, src_ip: str, src_port: int, service: str,
                        object_ref: str, prop: str, unit: str,
                        value: str, value_num: Optional[float], extra: dict) -> None:
    """Peuple bacnet_devices et bacnet_objects au fil des paquets."""
    # 1. Device : à partir d'un I-Am on récupère device_id, vendor_id, etc.
    async with db.acquire() as conn:
        async with conn.transaction():
            dev_row = await conn.fetchrow(
                """INSERT INTO bacnet_devices(ip_address, port, last_seen)
                   VALUES($1, $2, now())
                   ON CONFLICT(ip_address, port) DO UPDATE SET last_seen=now()
                   RETURNING id""",
                src_ip, src_port,
            )
            device_uuid = dev_row["id"]

            # Enrichir depuis I-Am
            if service == "iAm":
                vendor_id = extra.get("vendor_id")
                max_apdu = extra.get("max_apdu")
                seg = extra.get("segmentation")
                # object_ref = "device:1234"
                dev_id_num = None
                if object_ref.startswith("device:"):
                    try:
                        dev_id_num = int(object_ref.split(":", 1)[1])
                    except ValueError:
                        pass
                await conn.execute(
                    """UPDATE bacnet_devices
                       SET device_id=COALESCE($2, device_id),
                           vendor_id=COALESCE($3::int, vendor_id),
                           max_apdu=COALESCE($4::int, max_apdu),
                           segmentation=COALESCE($5, segmentation)
                       WHERE id=$1""",
                    device_uuid, dev_id_num,
                    int(vendor_id) if str(vendor_id).isdigit() else None,
                    int(max_apdu) if str(max_apdu).isdigit() else None,
                    seg,
                )

            # 2. Object : à partir de tout paquet qui référence un objet
            if object_ref and ":" in object_ref and not object_ref.startswith("device:"):
                otype_name, sep, oinst = object_ref.partition(":")
                try:
                    oinst_i = int(oinst)
                except ValueError:
                    return
                # Trouver le type numérique (reverse lookup enums pas dispo côté API,
                # on stocke -1 en interne mais on garde le ref texte)
                otype_i = _reverse_object_type(otype_name)
                await conn.execute(
                    """INSERT INTO bacnet_objects
                         (device_id, object_type, object_instance, object_ref, unit, last_seen)
                       VALUES($1, $2, $3, $4, $5, now())
                       ON CONFLICT (device_id, object_type, object_instance) DO UPDATE
                       SET last_seen=now(),
                           unit=CASE WHEN bacnet_objects.source='manual'
                                     THEN bacnet_objects.unit
                                     ELSE COALESCE(EXCLUDED.unit, bacnet_objects.unit) END""",
                    device_uuid, otype_i, oinst_i, object_ref, unit or None,
                )


_OBJECT_TYPE_REVERSE = {
    "analog-input": 0, "analog-output": 1, "analog-value": 2,
    "binary-input": 3, "binary-output": 4, "binary-value": 5,
    "calendar": 6, "command": 7, "device": 8, "event-enrollment": 9,
    "file": 10, "group": 11, "loop": 12,
    "multi-state-input": 13, "multi-state-output": 14, "notification-class": 15,
    "program": 16, "schedule": 17, "averaging": 18, "multi-state-value": 19,
    "trend-log": 20, "accumulator": 23, "pulse-converter": 24,
}


def _reverse_object_type(name: str) -> int:
    return _OBJECT_TYPE_REVERSE.get(name, -1)


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

@router.get("/stream")
async def stream(request: Request):
    queue, history = await bus.subscribe()

    async def generator() -> AsyncIterator[bytes]:
        try:
            for message in history:
                yield _sse(message)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _sse(message)
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
        finally:
            await bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), default=str)
    return f"data: {body}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# REST : devices & objects
# ---------------------------------------------------------------------------

@router.get("/devices")
async def list_devices(request: Request, limit: int = 500):
    rows = await request.app.state.db.fetch(
        """SELECT id::text, ip_address, port, device_id, vendor_id, max_apdu,
                  segmentation, name, description, first_seen, last_seen,
                  (SELECT count(*) FROM bacnet_objects o WHERE o.device_id=bacnet_devices.id) AS n_objects
           FROM bacnet_devices
           ORDER BY last_seen DESC LIMIT $1""",
        min(limit, 1000),
    )
    return [dict(r) for r in rows]


@router.get("/objects")
async def list_objects(request: Request, device_id: str = "", limit: int = 500, search: str = ""):
    conds = ["1=1"]
    params: list = []
    if device_id:
        conds.append(f"device_id = ${len(params)+1}::uuid")
        params.append(device_id)
    if search:
        conds.append(f"(object_ref ILIKE ${len(params)+1} OR name ILIKE ${len(params)+1})")
        params.append(f"%{search}%")
    where = " AND ".join(conds)
    params.append(min(limit, 5000))
    query = f"""
        SELECT o.id::text, o.device_id::text, o.object_type, o.object_instance,
               o.object_ref, o.name, o.description, o.unit, o.source,
               o.name_imported, o.unit_imported, o.description_imported,
               o.first_seen, o.last_seen,
               d.ip_address AS device_ip, d.port AS device_port, d.device_id AS device_number
        FROM bacnet_objects o
        JOIN bacnet_devices d ON d.id = o.device_id
        WHERE {where}
        ORDER BY d.ip_address, o.object_type, o.object_instance
        LIMIT ${len(params)}
    """
    rows = await request.app.state.db.fetch(query, *params)
    result = []
    for row in rows:
        d = dict(row)
        d["is_modified"] = d["source"] == "manual"
        result.append(d)
    return result


@router.patch("/objects/{object_id}")
async def update_object(object_id: str, payload: BacnetObjectPatch, request: Request):
    """Override manuel : passe source='manual', préserve les _imported."""
    db = request.app.state.db
    existing = await db.fetchrow(
        "SELECT id FROM bacnet_objects WHERE id=$1::uuid", object_id,
    )
    if not existing:
        raise HTTPException(404, "Objet introuvable")
    await db.execute(
        """UPDATE bacnet_objects
           SET name=COALESCE($2, name),
               unit=COALESCE($3, unit),
               description=COALESCE($4, description),
               source='manual'
           WHERE id=$1::uuid""",
        object_id, payload.name, payload.unit, payload.description,
    )
    return {"ok": True}


@router.post("/objects/{object_id}/reset")
async def reset_object(object_id: str, request: Request):
    """Restaure les valeurs auto-découvertes (mode 'sniffed')."""
    db = request.app.state.db
    row = await db.fetchrow(
        """SELECT name_imported, unit_imported, description_imported
           FROM bacnet_objects WHERE id=$1::uuid""",
        object_id,
    )
    if not row:
        raise HTTPException(404, "Objet introuvable")
    await db.execute(
        """UPDATE bacnet_objects
           SET name=name_imported,
               unit=unit_imported,
               description=description_imported,
               source='sniffed'
           WHERE id=$1::uuid""",
        object_id,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Historique — réutilise knx_history en générique (le get_history est agnostique)
# ---------------------------------------------------------------------------

from .knx_history import get_history


@router.get("/history")
async def history_endpoint(
    request: Request,
    address: str,                       # object_ref, ex "analog-input:5"
    since: str = "24h",
    field: str = "value_num",
):
    """
    Historique bucketisé pour un object_ref BACnet.
    Réutilise get_history() qui filtre par 'dst' dans bms.frames — pour BACnet
    on stocke object_ref dans dst, donc c'est direct.
    """
    return await get_history(request, address, since, field,
                             clickhouse_url=CLICKHOUSE_URL)
