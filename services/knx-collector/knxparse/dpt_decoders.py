"""
Décodeurs génériques réutilisables.

Ces décodeurs sont paramétrés par la spec du DPT (venant du registry Postgres).
Ils gèrent les types atomiques KNX standards et les structs déclaratifs
(champs multiples avec type/scale/unit).

Format retourné (uniforme) :
{
    "value": str,               # représentation lisible
    "value_num": float | None,  # valeur numérique principale (pour agrégations CH)
    "unit": str,                # unité
    "extra": dict[str, str],    # champs additionnels pour Map(String, String) CH
}
"""

from __future__ import annotations

import struct


def _empty(unit: str = "") -> dict:
    return {"value": "", "value_num": None, "unit": unit, "extra": {}}


# ---------------------------------------------------------------------------
# KNX float16 (EIS5 / DPT 9.xxx) — sign/exponent/mantissa
# ---------------------------------------------------------------------------

def decode_knx_float16(payload: bytes) -> float | None:
    """KNX 2-Byte Float : bit 15 = sign, bits 14-11 = exponent, bits 10-0 = mantissa."""
    if len(payload) < 2:
        return None
    raw = (payload[0] << 8) | payload[1]
    sign = (raw >> 15) & 0x01
    exponent = (raw >> 11) & 0x0F
    mantissa = raw & 0x07FF
    if sign:
        mantissa = -(2048 - mantissa)
    return 0.01 * mantissa * (2 ** exponent)


# ---------------------------------------------------------------------------
# Décodeurs par "kind" (colonne knx_dpt_registry.kind)
# ---------------------------------------------------------------------------

def decode_bool(payload: bytes, unit: str = "") -> dict:
    if not payload:
        return _empty(unit)
    v = bool(payload[0] & 0x01)
    return {"value": "1" if v else "0", "value_num": 1.0 if v else 0.0, "unit": unit, "extra": {}}


def decode_uint8(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if not payload:
        return _empty(unit)
    v = payload[0] * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_int8(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if not payload:
        return _empty(unit)
    v = struct.unpack(">b", payload[:1])[0] * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_percent_u8(payload: bytes, unit: str = "%") -> dict:
    """DPT 5.001 : 0..255 → 0..100 %."""
    if not payload:
        return _empty(unit)
    v = payload[0] * 100 / 255
    return {"value": f"{v:.1f}", "value_num": round(v, 2), "unit": unit, "extra": {}}


def decode_angle_u8(payload: bytes, unit: str = "°") -> dict:
    """DPT 5.003 : 0..255 → 0..360°."""
    if not payload:
        return _empty(unit)
    v = payload[0] * 360 / 255
    return {"value": f"{v:.1f}", "value_num": round(v, 2), "unit": unit, "extra": {}}


def decode_uint16(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if len(payload) < 2:
        return _empty(unit)
    raw = struct.unpack(">H", payload[:2])[0]
    v = raw * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_int16(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if len(payload) < 2:
        return _empty(unit)
    raw = struct.unpack(">h", payload[:2])[0]
    v = raw * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_uint32(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if len(payload) < 4:
        return _empty(unit)
    raw = struct.unpack(">I", payload[:4])[0]
    v = raw * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_int32(payload: bytes, unit: str = "", scale: float = 1.0) -> dict:
    if len(payload) < 4:
        return _empty(unit)
    raw = struct.unpack(">i", payload[:4])[0]
    v = raw * scale
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_float16(payload: bytes, unit: str = "") -> dict:
    """DPT 9.xxx — KNX 2-byte float."""
    v = decode_knx_float16(payload)
    if v is None:
        return _empty(unit)
    return {"value": f"{v:.2f}", "value_num": round(v, 3), "unit": unit, "extra": {}}


def decode_float32(payload: bytes, unit: str = "") -> dict:
    """DPT 14.xxx — IEEE 754 float 32-bit."""
    if len(payload) < 4:
        return _empty(unit)
    v = struct.unpack(">f", payload[:4])[0]
    return {"value": f"{v:g}", "value_num": v, "unit": unit, "extra": {}}


def decode_step_control(payload: bytes, unit: str = "") -> dict:
    """DPT 3.007 (dimming) / 3.008 (blinds) : bit 3 = start/stop, bits 2-0 = step."""
    if not payload:
        return _empty(unit)
    b = payload[0]
    action = "Increase" if (b & 0x08) else "Decrease"
    step = b & 0x07
    if step == 0:
        return {"value": "Stop", "value_num": 0.0, "unit": unit, "extra": {"action": "stop"}}
    return {
        "value": f"{action} step {step}",
        "value_num": float(step if action == "Increase" else -step),
        "unit": unit,
        "extra": {"action": action.lower(), "step": str(step)},
    }


def decode_time(payload: bytes, unit: str = "") -> dict:
    """DPT 10.001 : jour de la semaine + hh:mm:ss."""
    if len(payload) < 3:
        return _empty(unit)
    day = (payload[0] >> 5) & 0x07
    hour = payload[0] & 0x1F
    minute = payload[1] & 0x3F
    second = payload[2] & 0x3F
    days = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_name = days[day] if 0 < day < 8 else ""
    val = f"{day_name} {hour:02d}:{minute:02d}:{second:02d}".strip()
    return {"value": val, "value_num": None, "unit": unit,
            "extra": {"day": str(day), "hour": str(hour), "minute": str(minute), "second": str(second)}}


def decode_date(payload: bytes, unit: str = "") -> dict:
    """DPT 11.001 : dd/mm/yy."""
    if len(payload) < 3:
        return _empty(unit)
    d = payload[0] & 0x1F
    m = payload[1] & 0x0F
    y = payload[2] & 0x7F
    y_full = 2000 + y if y < 90 else 1900 + y
    return {"value": f"{y_full:04d}-{m:02d}-{d:02d}", "value_num": None, "unit": unit,
            "extra": {"year": str(y_full), "month": str(m), "day": str(d)}}


def decode_string_ascii(payload: bytes, unit: str = "") -> dict:
    """DPT 16.000 : 14 bytes ASCII."""
    v = payload[:14].rstrip(b"\x00").decode("ascii", errors="replace")
    return {"value": v, "value_num": None, "unit": unit, "extra": {}}


def decode_enum(payload: bytes, mapping: dict[int, str], unit: str = "") -> dict:
    """DPT 20.xxx : uint8 avec mapping vers un nom."""
    if not payload:
        return _empty(unit)
    v = payload[0]
    name = mapping.get(v, f"unknown({v})")
    return {"value": name, "value_num": float(v), "unit": unit, "extra": {"raw": str(v)}}


def decode_bitfield(payload: bytes, fields: list[dict], unit: str = "") -> dict:
    """
    DPT bitfield : chaque bit / groupe de bits nommé et décodé.
    fields = [{"name": "on", "offset": 0, "width": 1}, {"name": "priority", "offset": 1, "width": 2}]
    """
    if not payload:
        return _empty(unit)
    raw = int.from_bytes(payload, "big")
    total_bits = len(payload) * 8
    extra = {}
    for f in fields:
        offset = int(f.get("offset", 0))
        width = int(f.get("width", 1))
        name = str(f.get("name", f"bit{offset}"))
        shift = total_bits - offset - width
        if shift < 0:
            continue
        v = (raw >> shift) & ((1 << width) - 1)
        extra[name] = str(v)
    return {"value": " ".join(f"{k}={v}" for k, v in extra.items()),
            "value_num": None, "unit": unit, "extra": extra}


def decode_bytes(payload: bytes, unit: str = "") -> dict:
    """DPT bytes bruts : renvoie l'hex."""
    v = payload.hex()
    return {"value": v, "value_num": None, "unit": unit, "extra": {}}


# ---------------------------------------------------------------------------
# Décodeur "custom_struct" : struct déclaratif venant du registre
# ---------------------------------------------------------------------------

_STRUCT_FMTS = {
    "uint8":  (">B", 1), "int8":   (">b", 1),
    "uint16": (">H", 2), "int16":  (">h", 2),
    "uint32": (">I", 4), "int32":  (">i", 4),
    "float32": (">f", 4),
}


def decode_custom_struct(payload: bytes, fields: list[dict], unit: str = "") -> dict:
    """
    Décodeur struct déclaratif :
    fields = [{"name": "phase_a", "type": "uint16", "scale": 0.01, "unit": "kWh"}, ...]
    """
    if not payload or not fields:
        return _empty(unit)
    extra: dict[str, str] = {}
    parts: list[str] = []
    offset = 0
    primary_value_num: float | None = None
    primary_unit = unit
    for f in fields:
        ftype = str(f.get("type", "uint8"))
        fname = str(f.get("name", f"field{offset}"))
        scale = float(f.get("scale", 1.0))
        funit = str(f.get("unit", ""))
        fmt = _STRUCT_FMTS.get(ftype)
        if fmt is None:
            # Type inconnu : on skip
            continue
        pack_fmt, size = fmt
        if offset + size > len(payload):
            break
        raw = struct.unpack(pack_fmt, payload[offset:offset + size])[0]
        val = raw * scale
        offset += size
        extra[fname] = f"{val:g}"
        parts.append(f"{fname}={val:g}{funit}")
        if primary_value_num is None:
            primary_value_num = float(val)
            primary_unit = funit or primary_unit
    return {
        "value": " ".join(parts),
        "value_num": primary_value_num,
        "unit": primary_unit,
        "extra": extra,
    }


# ---------------------------------------------------------------------------
# Dispatch principal
# ---------------------------------------------------------------------------

def decode_by_kind(kind: str, payload: bytes, spec: dict, unit: str = "") -> dict:
    """
    Dispatch par kind (colonne knx_dpt_registry.kind). Renvoie le format uniforme.
    spec = knx_dpt_registry.spec_json (fields, mapping, scale, ...).
    """
    scale = float(spec.get("scale", 1.0))

    if kind == "bool":
        return decode_bool(payload, unit)
    if kind == "uint8":
        return decode_uint8(payload, unit, scale)
    if kind == "int8":
        return decode_int8(payload, unit, scale)
    if kind == "percent_u8":
        return decode_percent_u8(payload, unit or "%")
    if kind == "angle_u8":
        return decode_angle_u8(payload, unit or "°")
    if kind == "uint16":
        return decode_uint16(payload, unit, scale)
    if kind == "int16":
        return decode_int16(payload, unit, scale)
    if kind == "uint32":
        return decode_uint32(payload, unit, scale)
    if kind == "int32":
        return decode_int32(payload, unit, scale)
    if kind == "float16":
        return decode_float16(payload, unit)
    if kind == "float32":
        return decode_float32(payload, unit)
    if kind == "step_control":
        return decode_step_control(payload, unit)
    if kind == "time":
        return decode_time(payload, unit)
    if kind == "date":
        return decode_date(payload, unit)
    if kind == "string_ascii":
        return decode_string_ascii(payload, unit)
    if kind == "enum":
        mapping = {int(k): str(v) for k, v in (spec.get("mapping") or {}).items()}
        return decode_enum(payload, mapping, unit)
    if kind == "bitfield":
        return decode_bitfield(payload, spec.get("fields") or [], unit)
    if kind == "custom_struct":
        return decode_custom_struct(payload, spec.get("fields") or [], unit)
    if kind == "bytes":
        return decode_bytes(payload, unit)

    # Kind inconnu — retour brut
    return decode_bytes(payload, unit)
