"""
Routes KNX de l'API : monitoring temps réel (SSE), import ETS, keyring.

Round 1 : le stockage des événements est dans ClickHouse (bms.frames).
Postgres reste utilisé pour :
- Le catalogue sémantique (knx_group_addresses, knx_individual_addresses)
- Le chiffrement des keyrings via Fernet

Voir ARCHITECTURE.md pour la répartition des rôles.
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
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .knxparse import etsimport, keyring as knx_keyring


router = APIRouter(prefix="/knx", tags=["knx"])

CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")


# ---------------------------------------------------------------------------
# Migration schéma Postgres — appelée depuis le lifespan de main.py.
# Round 1 : n'ajoute plus rien à collector_events (table supprimée).
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

CREATE TABLE IF NOT EXISTS knx_individual_addresses (
    address     TEXT PRIMARY KEY,
    name        TEXT,
    device_type TEXT,
    line        TEXT,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def apply_knx_schema(conn) -> None:
    """Applique les migrations KNX Postgres. À appeler depuis le lifespan de main.py."""
    await conn.execute(KNX_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# ClickHouse writer — batch async avec flush périodique
# ---------------------------------------------------------------------------


class ClickHouseWriter:
    """
    Bufferise les inserts et flush en batch pour minimiser le coût par ligne.
    Flush automatique tous les 500ms OU quand le buffer atteint 100 lignes.
    """

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
            # Log stderr sans crash — perdre 100 lignes vaut mieux que planter
            # tout le pipeline. Un futur monitoring alertera si le taux dépasse un seuil.
            print(f"[knx_router] ClickHouse insert failed: {exc}", file=sys.stderr)


ch_writer = ClickHouseWriter(CLICKHOUSE_URL)


# ---------------------------------------------------------------------------
# Bus SSE : fan-out mémoire des télégrammes vers les clients UI
# ---------------------------------------------------------------------------


class TelegramBus:
    """
    Fan-out mémoire des télégrammes : chaque abonné a sa propre queue,
    on push le message à tout le monde. Backpressure : si un abonné est
    trop lent, on drop ses plus vieux messages plutôt que bloquer les autres.
    """

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


# ---------------------------------------------------------------------------
# Endpoints publics
# ---------------------------------------------------------------------------


@router.get("/group-addresses")
async def list_group_addresses(request: Request, limit: int = 500, search: str = ""):
    db = request.app.state.db
    safe_limit = min(limit, 5000)
    if search:
        pattern = f"%{search}%"
        rows = await db.fetch(
            """SELECT address, name, dpt, description, unit, source, updated_at
               FROM knx_group_addresses
               WHERE address ILIKE $1 OR name ILIKE $1
               ORDER BY address LIMIT $2""",
            pattern,
            safe_limit,
        )
    else:
        rows = await db.fetch(
            """SELECT address, name, dpt, description, unit, source, updated_at
               FROM knx_group_addresses ORDER BY address LIMIT $1""",
            safe_limit,
        )
    return [dict(row) for row in rows]


@router.patch("/group-addresses/{address}")
async def update_group_address(address: str, payload: GroupAddressPatch, request: Request):
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
            address,
            payload.dpt,
            payload.name,
            payload.description,
            payload.unit,
        )
    else:
        await db.execute(
            """INSERT INTO knx_group_addresses(address, name, dpt, description, unit, source)
               VALUES($1, $2, $3, $4, $5, 'manual')""",
            address,
            payload.name or f"GA {address}",
            payload.dpt,
            payload.description,
            payload.unit,
        )
    return {"ok": True}


@router.post("/import/esf")
async def import_esf(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    entries = etsimport.parse_esf(content)
    imported, updated = await _persist_entries(request.app.state.db, entries, "ets_esf")
    return {"imported": imported, "updated": updated, "total": len(entries)}


@router.post("/import/knxproj")
async def import_knxproj(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    entries = etsimport.parse_knxproj(content)
    if not entries:
        raise HTTPException(422, "Aucune adresse de groupe trouvée — archive vide ou mot de passe requis.")
    imported, updated = await _persist_entries(request.app.state.db, entries, "ets_knxproj")
    return {"imported": imported, "updated": updated, "total": len(entries)}


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

    from cryptography.fernet import Fernet  # local import pour éviter cycle

    fernet: Fernet = request.app.state.fernet
    envelope = json.dumps(
        {
            "kind": "knx_keyring",
            "project": ring.project,
            "signature": ring.signature,
            "raw": content.hex(),
        }
    ).encode()

    credential_id = uuid.uuid4()
    await request.app.state.db.execute(
        """INSERT INTO credentials(id, name, kind, scope, encrypted_payload, fingerprint)
           VALUES($1, $2, $3, $4, $5, $6)""",
        credential_id,
        f"KNX Keyring — {ring.project or 'sans projet'}",
        "knx_keyring",
        scope,
        fernet.encrypt(envelope),
        ring.signature[:16] if ring.signature else None,
    )
    return {"id": str(credential_id), "summary": ring.summary()}


@router.get("/stream")
async def stream(request: Request):
    """SSE : flux temps réel des télégrammes."""
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
# Endpoint interne appelé par le collector
# ---------------------------------------------------------------------------


@router.post("/collector/telegram", status_code=202)
async def collector_telegram(
    request: Request,
    gateway_id: str = Form(...),
    source: str = Form(...),
    destination: str = Form(...),
    apci: str = Form(...),
    value: str = Form(""),
    unit: str = Form(""),
    dpt: str = Form(""),
    point_name: str = Form(""),
    priority: str = Form(""),
    hop_count: int = Form(0),
    raw_hex: str = Form(...),
    x_internal_token: str = Header(""),
):
    """
    Reçoit un télégramme décodé depuis le collector KNX, le persiste dans
    ClickHouse (bms.frames) et le diffuse via SSE.
    """
    from .main import INTERNAL_TOKEN  # partage la conf

    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(403, "Accès interne refusé")

    ts = datetime.now(timezone.utc)

    # Cast numérique si possible — permet des agrégations SUM/AVG sur value_num
    value_num: Optional[float] = None
    try:
        value_num = float(value)
    except (TypeError, ValueError):
        value_num = None

    # Ligne ClickHouse
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
    }
    await ch_writer.push(row)

    # Message SSE (format UI, indépendant du schéma CH)
    message = {
        "ts": ts.isoformat(),
        "gateway_id": gateway_id,
        "source": source,
        "destination": destination,
        "apci": apci,
        "value": value,
        "unit": unit,
        "dpt": dpt,
        "point_name": point_name,
        "priority": priority,
        "hop_count": hop_count,
        "raw_hex": raw_hex,
    }
    await bus.publish(message)
    return {"accepted": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _persist_entries(db, entries, source_tag: str) -> tuple[int, int]:
    inserted = 0
    updated = 0
    async with db.acquire() as conn:
        async with conn.transaction():
            for entry in entries:
                if not entry.address:
                    continue
                result = await conn.execute(
                    """INSERT INTO knx_group_addresses(address, name, dpt, description, unit, source)
                       VALUES($1, $2, $3, $4, $5, $6)
                       ON CONFLICT(address) DO UPDATE
                       SET name=EXCLUDED.name,
                           dpt=COALESCE(EXCLUDED.dpt, knx_group_addresses.dpt),
                           description=COALESCE(EXCLUDED.description, knx_group_addresses.description),
                           unit=COALESCE(EXCLUDED.unit, knx_group_addresses.unit),
                           source=EXCLUDED.source,
                           updated_at=now()""",
                    entry.address,
                    entry.name,
                    entry.dpt,
                    entry.description or None,
                    entry.unit or None,
                    source_tag,
                )
                if result.endswith("1 0"):
                    inserted += 1
                else:
                    updated += 1
    return inserted, updated


def _sse(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"))
    return f"data: {body}\n\n".encode("utf-8")
