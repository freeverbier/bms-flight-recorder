"""
Routes KNX de l'API — Round 5 + 6 + 7.

Round 5 : décodeur APCI complet + registre DPT dynamique (Postgres).
Round 6 : endpoint historique bucketisé pour graphique.
Round 7 : séparation valeur d'import ETS vs override manuel.
           - Colonnes _imported préservées par les ré-imports
           - PATCH manual passe source='manual', ne touche pas aux _imported
           - POST /reset restaure la valeur d'import
           - Ré-import non destructif : si source='manual', l'effectif est préservé
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
from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .knxparse import etsimport, keyring as knx_keyring


router = APIRouter(prefix="/knx", tags=["knx"])

CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")


# ---------------------------------------------------------------------------
# Migrations schéma Postgres
# ---------------------------------------------------------------------------

KNX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knx_group_addresses (
    address     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    dpt         TEXT,
    description TEXT,
    unit        TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knx_group_addresses_name
    ON knx_group_addresses USING gin (to_tsvector('simple', name));

-- Round 7 : séparation valeur d'import vs override manuel
ALTER TABLE knx_group_addresses ADD COLUMN IF NOT EXISTS name_imported        TEXT;
ALTER TABLE knx_group_addresses ADD COLUMN IF NOT EXISTS dpt_imported         TEXT;
ALTER TABLE knx_group_addresses ADD COLUMN IF NOT EXISTS unit_imported        TEXT;
ALTER TABLE knx_group_addresses ADD COLUMN IF NOT EXISTS description_imported TEXT;

-- Backfill des lignes existantes qui n'ont pas encore d'_imported : si la ligne
-- existe et que source ≠ 'manual', les valeurs actuelles SONT l'import → recopie.
UPDATE knx_group_addresses
   SET name_imported        = COALESCE(name_imported, name),
       dpt_imported         = COALESCE(dpt_imported, dpt),
       unit_imported        = COALESCE(unit_imported, unit),
       description_imported = COALESCE(description_imported, description)
 WHERE (name_imported IS NULL OR dpt_imported IS NULL
        OR unit_imported IS NULL OR description_imported IS NULL)
   AND source <> 'manual';

CREATE TABLE IF NOT EXISTS knx_individual_addresses (
    address     TEXT PRIMARY KEY,
    name        TEXT,
    device_type TEXT,
    line        TEXT,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Round 5 : catalogue DPT dynamique
CREATE TABLE IF NOT EXISTS knx_dpt_registry (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dpt_id       TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    size_bits    INTEGER NOT NULL DEFAULT 8,
    kind         TEXT NOT NULL DEFAULT 'bytes',
    unit         TEXT NOT NULL DEFAULT '',
    spec_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    handler_code TEXT,
    handler_name TEXT,
    is_standard  BOOLEAN NOT NULL DEFAULT false,
    enabled      BOOLEAN NOT NULL DEFAULT true,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knx_dpt_registry_enabled
    ON knx_dpt_registry (enabled) WHERE enabled;
"""


STANDARD_DPTS = [
    ("1.001", "DPT_Switch", 1, "bool", "", {}, "Switch on/off"),
    ("1.002", "DPT_Bool", 1, "bool", "", {}, "Boolean value"),
    ("1.003", "DPT_Enable", 1, "bool", "", {}, "Enable/disable"),
    ("1.008", "DPT_UpDown", 1, "bool", "", {}, "Up/Down (blinds)"),
    ("1.009", "DPT_OpenClose", 1, "bool", "", {}, "Open/Close"),
    ("1.010", "DPT_Start", 1, "bool", "", {}, "Start/Stop"),
    ("3.007", "DPT_Control_Dimming", 4, "step_control", "", {}, "Dimming step control"),
    ("3.008", "DPT_Control_Blinds", 4, "step_control", "", {}, "Blinds step control"),
    ("5.001", "DPT_Scaling", 8, "percent_u8", "%", {}, "0..100 % (u8 scaled)"),
    ("5.003", "DPT_Angle", 8, "angle_u8", "°", {}, "0..360° (u8 scaled)"),
    ("5.004", "DPT_Percent_U8", 8, "uint8", "%", {}, "0..255 %"),
    ("5.010", "DPT_Value_1_Ucount", 8, "uint8", "", {}, "Counter u8"),
    ("6.001", "DPT_Percent_V8", 8, "int8", "%", {}, "-128..127 %"),
    ("7.001", "DPT_Value_2_Ucount", 16, "uint16", "", {}, "Counter u16"),
    ("8.001", "DPT_Value_2_Count", 16, "int16", "", {}, "Counter s16"),
    ("9.001", "DPT_Value_Temp", 16, "float16", "°C", {}, "Temperature"),
    ("9.002", "DPT_Value_Tempd", 16, "float16", "K", {}, "Temperature difference"),
    ("9.004", "DPT_Value_Lux", 16, "float16", "lx", {}, "Illuminance"),
    ("9.005", "DPT_Value_Wsp", 16, "float16", "m/s", {}, "Wind speed"),
    ("9.006", "DPT_Value_Pres", 16, "float16", "Pa", {}, "Pressure"),
    ("9.007", "DPT_Value_Humidity", 16, "float16", "%", {}, "Humidity"),
    ("9.008", "DPT_Value_AirQuality", 16, "float16", "ppm", {}, "Air quality"),
    ("9.024", "DPT_Value_Power", 16, "float16", "kW", {}, "Power"),
    ("9.025", "DPT_Value_Volume_Flow", 16, "float16", "l/h", {}, "Volume flow"),
    ("9.028", "DPT_Value_Wsp_kmh", 16, "float16", "km/h", {}, "Wind speed km/h"),
    ("10.001", "DPT_TimeOfDay", 24, "time", "", {}, "Time of day"),
    ("11.001", "DPT_Date", 24, "date", "", {}, "Date"),
    ("12.001", "DPT_Value_4_Ucount", 32, "uint32", "", {}, "Counter u32"),
    ("13.001", "DPT_Value_4_Count", 32, "int32", "", {}, "Counter s32"),
    ("13.010", "DPT_ActiveEnergy", 32, "int32", "Wh", {}, "Active energy"),
    ("13.013", "DPT_ActiveEnergy_kWh", 32, "int32", "kWh", {}, "Active energy (kWh)"),
    ("14.000", "DPT_Value_Acceleration", 32, "float32", "m/s²", {}, "Acceleration"),
    ("14.007", "DPT_Value_Angle_Deg", 32, "float32", "°", {}, "Angle"),
    ("14.019", "DPT_Value_Electric_Current", 32, "float32", "A", {}, "Electric current"),
    ("14.027", "DPT_Value_Electric_Potential", 32, "float32", "V", {}, "Voltage"),
    ("14.056", "DPT_Value_Power_f32", 32, "float32", "W", {}, "Power (float32)"),
    ("16.000", "DPT_String_ASCII", 112, "string_ascii", "", {}, "14 bytes ASCII string"),
    ("232.600", "DPT_Colour_RGB", 24, "bytes", "", {}, "RGB colour (3 bytes)"),
]


async def apply_knx_schema(conn) -> None:
    await conn.execute(KNX_SCHEMA_SQL)
    for dpt_id, name, size, kind, unit, spec, description in STANDARD_DPTS:
        await conn.execute(
            """INSERT INTO knx_dpt_registry
                 (dpt_id, name, size_bits, kind, unit, spec_json, is_standard, description)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, true, $7)
               ON CONFLICT (dpt_id) DO NOTHING""",
            dpt_id, name, size, kind, unit, json.dumps(spec), description,
        )


# ---------------------------------------------------------------------------
# ClickHouse writer
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

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush()
        if self._client:
            await self._client.aclose()

    async def push(self, row: dict) -> None:
        async with self._lock:
            self._buffer.append(row)
            if len(self._buffer) >= self._max_batch:
                await self._flush_locked()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            async with self._lock:
                await self._flush_locked()

    async def _flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self) -> None:
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
            print(f"[knx_router] ClickHouse insert failed: {exc}", file=sys.stderr)


ch_writer = ClickHouseWriter(CLICKHOUSE_URL)


# ---------------------------------------------------------------------------
# Bus SSE
# ---------------------------------------------------------------------------


class TelegramBus:
    def __init__(self, backlog: int = 200, queue_max: int = 500) -> None:
        self._history: deque[dict] = deque(maxlen=backlog)
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._queue_max = queue_max
        self._lock = asyncio.Lock()

    async def subscribe(self) -> tuple[asyncio.Queue[dict], list[dict]]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._queue_max)
        async with self._lock:
            self._subscribers.add(queue)
            history = list(self._history)
        return queue, history

    async def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, message: dict) -> None:
        async with self._lock:
            self._history.append(message)
            dead: list[asyncio.Queue] = []
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


bus = TelegramBus()


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------


class GroupAddressPatch(BaseModel):
    dpt: str | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=20)


class DptRegistryIn(BaseModel):
    dpt_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    size_bits: int = Field(default=8, ge=1, le=4096)
    kind: str = Field(default="bytes", max_length=32)
    unit: str = Field(default="", max_length=32)
    spec_json: dict = Field(default_factory=dict)
    handler_code: str | None = None
    handler_name: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=500)
    enabled: bool = True


class DptRegistryPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    size_bits: int | None = Field(default=None, ge=1, le=4096)
    kind: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=32)
    spec_json: dict | None = None
    handler_code: str | None = None
    handler_name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Group addresses — Round 7 : lecture enrichie avec _imported
# ---------------------------------------------------------------------------


@router.get("/group-addresses")
async def list_group_addresses(request: Request, limit: int = 500, search: str = ""):
    db = request.app.state.db
    safe_limit = min(limit, 5000)
    cols = """address, name, dpt, description, unit, source, updated_at,
              name_imported, dpt_imported, unit_imported, description_imported"""
    if search:
        pattern = f"%{search}%"
        rows = await db.fetch(
            f"""SELECT {cols}
               FROM knx_group_addresses
               WHERE address ILIKE $1 OR name ILIKE $1
               ORDER BY address LIMIT $2""",
            pattern, safe_limit,
        )
    else:
        rows = await db.fetch(
            f"""SELECT {cols} FROM knx_group_addresses ORDER BY address LIMIT $1""",
            safe_limit,
        )
    result = []
    for row in rows:
        d = dict(row)
        # Round 7 : flag "modified" pratique pour l'UI
        d["is_modified"] = d["source"] == "manual"
        d["has_import"] = (
            d["name_imported"] is not None
            or d["dpt_imported"] is not None
            or d["unit_imported"] is not None
            or d["description_imported"] is not None
        )
        result.append(d)
    return result


@router.patch("/group-addresses/{address:path}")
async def update_group_address(address: str, payload: GroupAddressPatch, request: Request):
    """
    Patch manuel : passe source='manual', ne touche PAS aux _imported.
    Ainsi si l'utilisateur ré-importe le ESF, ses modifs sont préservées.
    """
    db = request.app.state.db
    existing = await db.fetchrow(
        "SELECT address FROM knx_group_addresses WHERE address=$1", address
    )
    if existing:
        await db.execute(
            """UPDATE knx_group_addresses
               SET dpt=COALESCE($2, dpt),
                   name=COALESCE($3, name),
                   description=COALESCE($4, description),
                   unit=COALESCE($5, unit),
                   source='manual',
                   updated_at=now()
               WHERE address=$1""",
            address, payload.dpt, payload.name, payload.description, payload.unit,
        )
    else:
        # GA créée manuellement (pas d'import préalable)
        await db.execute(
            """INSERT INTO knx_group_addresses(address, name, dpt, description, unit, source)
               VALUES($1, $2, $3, $4, $5, 'manual')""",
            address, payload.name or f"GA {address}", payload.dpt,
            payload.description, payload.unit,
        )
    return {"ok": True}


@router.post("/group-addresses/{address:path}/reset")
async def reset_group_address(address: str, request: Request):
    """
    Round 7 : restaure les valeurs d'import (name/dpt/unit/description venus de
    l'ETS) et repasse source à sa valeur d'origine. La ligne perd son statut
    "manual".
    """
    db = request.app.state.db
    row = await db.fetchrow(
        """SELECT name_imported, dpt_imported, unit_imported, description_imported
           FROM knx_group_addresses WHERE address=$1""",
        address,
    )
    if not row:
        raise HTTPException(404, "Adresse inconnue")
    if all(row[c] is None for c in row.keys()):
        raise HTTPException(
            422,
            "Aucune valeur d'import disponible pour cette adresse — elle a été "
            "créée manuellement. Utilisez DELETE pour la supprimer.",
        )
    # On ne peut pas savoir source d'origine (ets_esf vs ets_knxproj) : on met
    # 'ets_reimport' par convention. Un ré-import ultérieur remettra le vrai tag.
    await db.execute(
        """UPDATE knx_group_addresses
           SET name        = COALESCE(name_imported, name),
               dpt         = dpt_imported,
               unit        = unit_imported,
               description = description_imported,
               source      = 'ets_reimport',
               updated_at  = now()
           WHERE address=$1""",
        address,
    )
    return {"ok": True, "restored_from": "import"}


@router.delete("/group-addresses/{address:path}", status_code=204)
async def delete_group_address(address: str, request: Request):
    """Round 7 : suppression d'une GA (utile pour lignes créées manuellement)."""
    db = request.app.state.db
    result = await db.execute(
        "DELETE FROM knx_group_addresses WHERE address=$1", address
    )
    if result.endswith("0"):
        raise HTTPException(404, "Adresse inconnue")


# ---------------------------------------------------------------------------
# DPT Registry — CRUD (Round 5)
# ---------------------------------------------------------------------------


@router.get("/dpt-registry")
async def list_dpt_registry(request: Request, include_disabled: bool = False):
    db = request.app.state.db
    if include_disabled:
        rows = await db.fetch(
            """SELECT id, dpt_id, name, size_bits, kind, unit, spec_json,
                      handler_code, handler_name, is_standard, enabled,
                      description, created_at, updated_at
               FROM knx_dpt_registry ORDER BY is_standard DESC, dpt_id"""
        )
    else:
        rows = await db.fetch(
            """SELECT id, dpt_id, name, size_bits, kind, unit, spec_json,
                      handler_code, handler_name, is_standard, enabled,
                      description, created_at, updated_at
               FROM knx_dpt_registry WHERE enabled ORDER BY is_standard DESC, dpt_id"""
        )
    result = []
    for row in rows:
        d = dict(row)
        d["id"] = str(d["id"])
        if isinstance(d.get("spec_json"), str):
            try:
                d["spec_json"] = json.loads(d["spec_json"])
            except Exception:
                d["spec_json"] = {}
        result.append(d)
    return result


@router.post("/dpt-registry", status_code=201)
async def create_dpt_entry(payload: DptRegistryIn, request: Request):
    db = request.app.state.db
    existing = await db.fetchrow(
        "SELECT id FROM knx_dpt_registry WHERE dpt_id=$1", payload.dpt_id
    )
    if existing:
        raise HTTPException(409, f"DPT {payload.dpt_id} existe déjà")
    dpt_uuid = uuid.uuid4()
    await db.execute(
        """INSERT INTO knx_dpt_registry
             (id, dpt_id, name, size_bits, kind, unit, spec_json,
              handler_code, handler_name, is_standard, enabled, description)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, false, $10, $11)""",
        dpt_uuid, payload.dpt_id, payload.name, payload.size_bits, payload.kind,
        payload.unit, json.dumps(payload.spec_json),
        payload.handler_code, payload.handler_name, payload.enabled, payload.description,
    )
    return {"id": str(dpt_uuid), "dpt_id": payload.dpt_id}


@router.patch("/dpt-registry/{dpt_id}")
async def update_dpt_entry(dpt_id: str, payload: DptRegistryPatch, request: Request):
    db = request.app.state.db
    existing = await db.fetchrow(
        "SELECT id, is_standard FROM knx_dpt_registry WHERE dpt_id=$1", dpt_id
    )
    if not existing:
        raise HTTPException(404, "DPT introuvable")
    if existing["is_standard"] and payload.kind is not None:
        raise HTTPException(422, "Le kind d'un DPT standard ne peut pas être modifié")
    updates = payload.model_dump(exclude_unset=True)
    if "spec_json" in updates:
        updates["spec_json"] = json.dumps(updates["spec_json"])
    if not updates:
        return {"ok": True, "changed": 0}
    fields = list(updates.keys())
    values = list(updates.values())
    set_clause = ", ".join(f"{f}=${i+2}" for i, f in enumerate(fields))
    query = f"UPDATE knx_dpt_registry SET {set_clause}, updated_at=now() WHERE dpt_id=$1"
    if "spec_json" in fields:
        idx = fields.index("spec_json") + 2
        query = query.replace(f"spec_json=${idx}", f"spec_json=${idx}::jsonb")
    await db.execute(query, dpt_id, *values)
    return {"ok": True, "changed": len(fields)}


@router.delete("/dpt-registry/{dpt_id}", status_code=204)
async def delete_dpt_entry(dpt_id: str, request: Request):
    db = request.app.state.db
    existing = await db.fetchrow(
        "SELECT is_standard FROM knx_dpt_registry WHERE dpt_id=$1", dpt_id
    )
    if not existing:
        raise HTTPException(404, "DPT introuvable")
    if existing["is_standard"]:
        raise HTTPException(422, "Un DPT standard ne peut pas être supprimé (désactive-le à la place)")
    await db.execute("DELETE FROM knx_dpt_registry WHERE dpt_id=$1", dpt_id)


# ---------------------------------------------------------------------------
# Imports ETS / keyring
# ---------------------------------------------------------------------------


@router.post("/import/esf")
async def import_esf(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    entries = etsimport.parse_esf(content)
    stats = await _persist_entries(request.app.state.db, entries, "ets_esf")
    return {"imported": stats[0], "updated": stats[1], "preserved": stats[2],
            "total": len(entries)}


@router.post("/import/knxproj")
async def import_knxproj(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    entries = etsimport.parse_knxproj(content)
    if not entries:
        raise HTTPException(422, "Aucune adresse de groupe trouvée")
    stats = await _persist_entries(request.app.state.db, entries, "ets_knxproj")
    return {"imported": stats[0], "updated": stats[1], "preserved": stats[2],
            "total": len(entries)}


@router.post("/import/keyring")
async def import_keyring(
    request: Request,
    file: UploadFile = File(...),
    password: str = Form(...),
    scope: str = Form("global"),
):
    content = await file.read()
    try:
        ring = knx_keyring.load_keyring(content, password)
    except knx_keyring.KeyringError as exc:
        raise HTTPException(422, f"Keyring invalide : {exc}") from exc

    from cryptography.fernet import Fernet
    fernet: Fernet = request.app.state.fernet
    envelope = json.dumps({
        "kind": "knx_keyring",
        "project": ring.project,
        "signature": ring.signature,
        "raw": content.hex(),
    }).encode()

    credential_id = uuid.uuid4()
    await request.app.state.db.execute(
        """INSERT INTO credentials(id, name, kind, scope, encrypted_payload, fingerprint)
           VALUES($1, $2, $3, $4, $5, $6)""",
        credential_id, f"KNX Keyring — {ring.project or 'sans projet'}",
        "knx_keyring", scope, fernet.encrypt(envelope),
        ring.signature[:16] if ring.signature else None,
    )
    return {"id": str(credential_id), "summary": ring.summary()}


# ---------------------------------------------------------------------------
# SSE
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


# ---------------------------------------------------------------------------
# Endpoint interne : POST télégramme
# ---------------------------------------------------------------------------


@router.post("/collector/telegram", status_code=202)
async def collector_telegram(
    request: Request,
    gateway_id: str = Form(...),
    source: str = Form(...),
    destination: str = Form(...),
    apci: str = Form(...),
    apci_category: str = Form("runtime"),
    tpci: str = Form(""),
    value: str = Form(""),
    unit: str = Form(""),
    dpt: str = Form(""),
    point_name: str = Form(""),
    priority: str = Form(""),
    hop_count: int = Form(0),
    extra_json: str = Form("{}"),
    raw_hex: str = Form(...),
    x_internal_token: str = Header(""),
):
    from .main import INTERNAL_TOKEN
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")

    ts = datetime.now(timezone.utc)

    value_num: Optional[float] = None
    try:
        value_num = float(value)
    except (TypeError, ValueError):
        value_num = None

    try:
        extra = json.loads(extra_json) if extra_json else {}
    except json.JSONDecodeError:
        extra = {}
    extra_cast = {str(k): str(v) for k, v in extra.items()} if isinstance(extra, dict) else {}

    row = {
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "protocol": "knx",
        "source_kind": "gateway",
        "source_id": gateway_id,
        "src": source,
        "dst": destination,
        "operation": apci,
        "value": value,
        "value_num": value_num,
        "unit": unit,
        "dpt": dpt,
        "point_name": point_name,
        "priority": priority,
        "hop_count": hop_count,
        "raw_hex": raw_hex,
        "frame_len": len(raw_hex) // 2,
        "status": "ok",
        "apci_category": apci_category,
        "tpci": tpci,
        "extra": extra_cast,
    }
    await ch_writer.push(row)

    message = {
        "ts": ts.isoformat(),
        "gateway_id": gateway_id,
        "source": source,
        "destination": destination,
        "apci": apci,
        "apci_category": apci_category,
        "tpci": tpci,
        "value": value,
        "unit": unit,
        "dpt": dpt,
        "point_name": point_name,
        "priority": priority,
        "hop_count": hop_count,
        "raw_hex": raw_hex,
        "extra": extra_cast,
    }
    await bus.publish(message)
    return {"accepted": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _persist_entries(db, entries, source_tag: str) -> tuple[int, int, int]:
    """
    Round 7 : ré-import non destructif.
    - Nouvelles lignes : insertion normale (name/dpt/unit/description +
      leur reflet dans _imported).
    - Lignes existantes avec source != 'manual' : on écrase name/dpt/unit/description
      (comme avant) ET on met à jour _imported.
    - Lignes existantes avec source == 'manual' : on garde les valeurs effectives,
      on met à jour _imported uniquement (l'utilisateur pourra "reset" plus tard).

    Retourne (inserted, updated, preserved_manual).
    """
    inserted = 0
    updated = 0
    preserved = 0
    async with db.acquire() as conn:
        async with conn.transaction():
            for entry in entries:
                if not entry.address:
                    continue
                # Récupérer l'état actuel pour décider
                current = await conn.fetchrow(
                    "SELECT source FROM knx_group_addresses WHERE address=$1",
                    entry.address,
                )
                if current is None:
                    # Nouvelle ligne : insert avec _imported = valeurs importées
                    await conn.execute(
                        """INSERT INTO knx_group_addresses
                             (address, name, dpt, description, unit, source,
                              name_imported, dpt_imported, unit_imported, description_imported)
                           VALUES($1, $2, $3, $4, $5, $6, $2, $3, $5, $4)""",
                        entry.address, entry.name, entry.dpt,
                        entry.description or None, entry.unit or None, source_tag,
                    )
                    inserted += 1
                elif current["source"] == "manual":
                    # Override manuel présent : on met juste à jour les _imported
                    await conn.execute(
                        """UPDATE knx_group_addresses
                           SET name_imported=$2,
                               dpt_imported=$3,
                               unit_imported=$5,
                               description_imported=$4,
                               updated_at=now()
                           WHERE address=$1""",
                        entry.address, entry.name, entry.dpt,
                        entry.description or None, entry.unit or None,
                    )
                    preserved += 1
                else:
                    # Ligne existante venue d'un import : écrase tout, refresh _imported
                    await conn.execute(
                        """UPDATE knx_group_addresses
                           SET name=$2,
                               dpt=COALESCE($3, dpt),
                               description=COALESCE($4, description),
                               unit=COALESCE($5, unit),
                               name_imported=$2,
                               dpt_imported=$3,
                               unit_imported=$5,
                               description_imported=$4,
                               source=$6,
                               updated_at=now()
                           WHERE address=$1""",
                        entry.address, entry.name, entry.dpt,
                        entry.description or None, entry.unit or None, source_tag,
                    )
                    updated += 1
    return inserted, updated, preserved


def _sse(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"))
    return f"data: {body}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Round 6 — endpoint historique
# ---------------------------------------------------------------------------

from .knx_history import get_history


@router.get("/history")
async def history_endpoint(
    request: Request,
    address: str,
    since: str = "24h",
    field: str = "value_num",
):
    return await get_history(request, address, since, field, clickhouse_url=CLICKHOUSE_URL)
