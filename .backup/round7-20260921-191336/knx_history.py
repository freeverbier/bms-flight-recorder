"""
Endpoint historique KNX — Round 6.

Route : GET /api/knx/history?address=X&since=Y&field=Z

Retourne une série temporelle bucketisée pour tracer un graphique d'une valeur
KNX (une adresse de groupe donnée, un champ spécifique).

À intégrer dans knx_router.py (ajouter le contenu à la fin, avant les helpers).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, Request

# Buckets de downsampling automatique — cible ~500-700 points par graphique
# (garde la latence < 500 ms et un rendu SVG fluide sans limite arbitraire)
BUCKET_TABLE = [
    # (max_window_seconds, bucket_seconds)
    (3600, 5),               # ≤ 1h  → 5s   → 720 pts max
    (6 * 3600, 30),          # ≤ 6h  → 30s  → 720 pts max
    (24 * 3600, 120),        # ≤ 24h → 2min → 720 pts max
    (7 * 24 * 3600, 900),    # ≤ 7j  → 15min → 672 pts max
    (30 * 24 * 3600, 3600),  # ≤ 30j → 1h   → 720 pts max
    (float("inf"), 6 * 3600),  # > 30j → 6h
]

# Regex de sécurité pour éviter l'injection SQL dans le field extra
_EXTRA_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def parse_since(since: str) -> timedelta:
    """
    Convertit "1h", "6h", "24h", "7d", "30d" en timedelta.
    Refuse tout autre format pour éviter l'injection.
    """
    since = (since or "24h").strip().lower()
    m = re.fullmatch(r"(\d+)([hd])", since)
    if not m:
        raise HTTPException(422, f"Format 'since' invalide : {since!r} (attendu ex. 1h, 24h, 7d)")
    n = int(m.group(1))
    unit = m.group(2)
    if n < 1 or n > 365:
        raise HTTPException(422, f"'since' hors bornes : {since!r}")
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(days=n)


def choose_bucket(window_s: float) -> int:
    for max_win, bucket in BUCKET_TABLE:
        if window_s <= max_win:
            return int(bucket)
    return int(BUCKET_TABLE[-1][1])


def field_expr(field: str) -> tuple[str, str]:
    """
    Retourne (expression_sql, label_human) pour le champ demandé.
    Refuse tout ce qui n'est pas 'value_num' ou 'extra.CLÉ' avec clé alphanum.
    """
    field = (field or "value_num").strip()
    if field == "value_num":
        return "value_num", "value_num"
    if field.startswith("extra."):
        key = field[len("extra."):]
        if not _EXTRA_KEY_RE.match(key):
            raise HTTPException(422, f"Nom de champ extra invalide : {key!r}")
        # toFloat64OrNull renvoie NULL si la clé manque ou n'est pas convertible
        return f"toFloat64OrNull(extra['{key}'])", f"extra.{key}"
    raise HTTPException(422, f"Field non supporté : {field!r} (attendu 'value_num' ou 'extra.KEY')")


async def _clickhouse_query(url: str, query: str, params: Optional[dict] = None) -> list[dict]:
    """Exécute une requête CH en JSON et renvoie une liste de dicts."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            url,
            params={"query": query + " FORMAT JSONEachRow"},
            content=(params or {}).get("body", ""),
        )
        r.raise_for_status()
        rows = []
        for line in r.text.strip().splitlines():
            if line.strip():
                import json
                rows.append(json.loads(line))
        return rows


async def get_history(
    request: Request,
    address: str,
    since: str = "24h",
    field: str = "value_num",
    clickhouse_url: str = "http://clickhouse:8123",
) -> dict:
    """
    Renvoie l'historique bucketisé pour une adresse de groupe (ou individuelle).

    Args:
        request: FastAPI request (pour accès au pool Postgres via app.state.db)
        address: '3/4/5' ou '1.1.10'
        since: '1h', '6h', '24h', '7d', '30d'
        field: 'value_num' ou 'extra.KEY'
    """
    if not address or "/" not in address and "." not in address:
        raise HTTPException(422, "Adresse invalide")

    window = parse_since(since)
    to_ts = datetime.now(timezone.utc)
    from_ts = to_ts - window
    bucket_s = choose_bucket(window.total_seconds())
    expr, field_label = field_expr(field)

    # Escape SQL de address (uniquement chars [0-9./])
    if not re.fullmatch(r"[0-9./]+", address):
        raise HTTPException(422, "Adresse invalide (caractères)")

    # Query principale : bucket + moyenne
    from_iso = from_ts.strftime("%Y-%m-%d %H:%M:%S")
    to_iso = to_ts.strftime("%Y-%m-%d %H:%M:%S")

    q_points = f"""
        SELECT
            toStartOfInterval(ts, INTERVAL {bucket_s} SECOND) AS bucket,
            avg({expr}) AS value,
            count() AS cnt
        FROM bms.frames
        WHERE protocol = 'knx'
          AND dst = '{address}'
          AND ts >= toDateTime('{from_iso}')
          AND ts <  toDateTime('{to_iso}')
          AND {expr} IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
    """

    # Query annexe : total frames + clés extra disponibles
    q_meta = f"""
        SELECT
            count() AS total,
            arrayDistinct(arrayFlatten(groupArray(mapKeys(extra)))) AS keys
        FROM bms.frames
        WHERE protocol = 'knx'
          AND dst = '{address}'
          AND ts >= toDateTime('{from_iso}')
          AND ts <  toDateTime('{to_iso}')
    """

    points_rows = await _clickhouse_query(clickhouse_url, q_points)
    meta_rows = await _clickhouse_query(clickhouse_url, q_meta)

    total = int(meta_rows[0]["total"]) if meta_rows else 0
    extra_keys = list(meta_rows[0].get("keys") or []) if meta_rows else []
    # Filtrer les clés qui sont numériques exploitables — on essaie toutes,
    # côté client on ajoutera "value_num" par défaut
    available = ["value_num"] + [f"extra.{k}" for k in sorted(extra_keys)]

    # Enrichissement : dpt / name / unit depuis Postgres
    db = request.app.state.db
    point_name = ""
    dpt = ""
    unit = ""
    if "/" in address:
        row = await db.fetchrow(
            "SELECT name, dpt, unit FROM knx_group_addresses WHERE address = $1",
            address,
        )
        if row:
            point_name = row["name"] or ""
            dpt = row["dpt"] or ""
            unit = row["unit"] or ""

    points = []
    for p in points_rows:
        bucket_str = p["bucket"]
        # ClickHouse renvoie "2026-09-21 12:00:00", on veut ISO 8601 avec T + Z
        if " " in bucket_str and "T" not in bucket_str:
            bucket_str = bucket_str.replace(" ", "T") + "Z"
        elif not bucket_str.endswith("Z") and "+" not in bucket_str:
            bucket_str += "Z"
        points.append({
            "ts": bucket_str,
            "value": float(p["value"]) if p["value"] is not None else None,
            "count": int(p["cnt"]),
        })

    return {
        "meta": {
            "address": address,
            "point_name": point_name,
            "dpt": dpt,
            "unit": unit,
            "field": field_label,
            "bucket_s": bucket_s,
            "from": from_ts.isoformat(),
            "to": to_ts.isoformat(),
            "total_frames": total,
            "available_fields": available,
        },
        "points": points,
    }
