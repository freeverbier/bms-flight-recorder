"""
Parser ASN.1 tagué BACnet (ANSI/ASHRAE 135, clause 20).

Chaque valeur BACnet est précédée d'un tag byte:
  Bits 7-4 : Tag Number (0-14) ou 15 = extended tag (byte suivant)
  Bit  3   : Class (0=Application, 1=Context)
  Bits 2-0 : LVT (Length/Value/Type)
    LVT ≤ 4 : longueur des data qui suivent
    LVT = 5 : longueur étendue (byte suivant, avec 254/255 pour 2/4 bytes)
    LVT = 6 : Opening tag (SEQUENCE start)
    LVT = 7 : Closing tag (SEQUENCE end)

Application Tags (BACnet standard) :
  0 = Null,    1 = Boolean,  2 = UnsignedInt,   3 = SignedInt,
  4 = Real,    5 = Double,   6 = OctetString,   7 = CharString,
  8 = BitString, 9 = Enumerated, 10 = Date,     11 = Time,
  12 = ObjectIdentifier

Context Tags : mêmes primitives, sémantique dépend du service.

L'API principale est parse_value() qui retourne (value_dict, cursor_next).
Pour un buffer complet, iter_tags() énumère tous les tags top-level.
"""

from __future__ import annotations

import struct
from typing import Iterator


class ASN1Error(Exception):
    pass


# ---------------------------------------------------------------------------
# Tag decoding
# ---------------------------------------------------------------------------

def _decode_tag(data: bytes, i: int) -> tuple[int, int, int, int]:
    """
    Retourne (tag_number, tag_class, lvt, cursor_after_tag).
    tag_class : 0=Application, 1=Context.
    lvt : 0..4 = longueur, 5=len étendue, 6=opening, 7=closing.
    """
    if i >= len(data):
        raise ASN1Error(f"tag truncated at {i}")
    b = data[i]
    tag_num = (b >> 4) & 0x0F
    tag_cls = (b >> 3) & 0x01
    lvt = b & 0x07
    i += 1
    if tag_num == 15:
        # Extended tag number
        if i >= len(data):
            raise ASN1Error("extended tag truncated")
        tag_num = data[i]
        i += 1
    return tag_num, tag_cls, lvt, i


def _decode_length(data: bytes, i: int, lvt: int) -> tuple[int, int]:
    """Retourne (length, cursor_after_length)."""
    if lvt < 5:
        return lvt, i
    if lvt == 5:
        if i >= len(data):
            raise ASN1Error("extended length truncated")
        b = data[i]
        i += 1
        if b < 254:
            return b, i
        if b == 254:
            if i + 2 > len(data):
                raise ASN1Error("extended length 2b truncated")
            return int.from_bytes(data[i:i+2], "big"), i + 2
        # b == 255
        if i + 4 > len(data):
            raise ASN1Error("extended length 4b truncated")
        return int.from_bytes(data[i:i+4], "big"), i + 4
    # lvt 6 or 7 = opening/closing tags (no length)
    return 0, i


# ---------------------------------------------------------------------------
# Primitive value decoders
# ---------------------------------------------------------------------------

def _decode_boolean(data: bytes, length: int, lvt_hint: int, is_context: bool):
    if is_context:
        return data[:length] != b"\x00", data[length:]
    # Application-tagged Boolean : LVT encode directement la valeur
    return bool(lvt_hint), data


def _decode_unsigned(data: bytes, length: int):
    return int.from_bytes(data[:length], "big"), data[length:]


def _decode_signed(data: bytes, length: int):
    return int.from_bytes(data[:length], "big", signed=True), data[length:]


def _decode_real(data: bytes, length: int):
    if length != 4:
        raise ASN1Error(f"Real must be 4 bytes, got {length}")
    return struct.unpack(">f", data[:4])[0], data[4:]


def _decode_double(data: bytes, length: int):
    if length != 8:
        raise ASN1Error(f"Double must be 8 bytes, got {length}")
    return struct.unpack(">d", data[:8])[0], data[8:]


def _decode_octet_string(data: bytes, length: int):
    return data[:length], data[length:]


def _decode_char_string(data: bytes, length: int):
    """
    ANSI/ASHRAE 135 : premier byte = codeset (0=UTF-8, 1=UCS-4, 3=UCS-2, 4=ISO-8859-1).
    On tente UTF-8 par défaut, fallback latin-1.
    """
    if length == 0:
        return "", data
    codeset = data[0]
    payload = data[1:length]
    encoding = {0: "utf-8", 3: "utf-16-be", 4: "latin-1"}.get(codeset, "latin-1")
    try:
        return payload.decode(encoding, errors="replace"), data[length:]
    except Exception:
        return payload.decode("latin-1", errors="replace"), data[length:]


def _decode_bit_string(data: bytes, length: int):
    """
    Premier byte = nombre de bits inutilisés dans le dernier octet.
    Retourne un dict {"bits": <int>, "value": <hex>, "unused": <int>}.
    """
    if length == 0:
        return {"bits": 0, "value": "", "unused": 0}, data
    unused = data[0]
    payload = data[1:length]
    total_bits = (len(payload) * 8) - unused
    return {"bits": total_bits, "value": payload.hex(), "unused": unused}, data[length:]


def _decode_enumerated(data: bytes, length: int):
    return int.from_bytes(data[:length], "big"), data[length:]


def _decode_date(data: bytes, length: int):
    if length != 4:
        raise ASN1Error(f"Date must be 4 bytes, got {length}")
    year, month, day, dow = data[0], data[1], data[2], data[3]
    return {
        "year": (year + 1900) if year != 255 else "*",
        "month": month if month != 255 else "*",
        "day": day if day != 255 else "*",
        "dow": dow if dow != 255 else "*",
    }, data[4:]


def _decode_time(data: bytes, length: int):
    if length != 4:
        raise ASN1Error(f"Time must be 4 bytes, got {length}")
    return {
        "hour":       data[0] if data[0] != 255 else "*",
        "minute":     data[1] if data[1] != 255 else "*",
        "second":     data[2] if data[2] != 255 else "*",
        "hundredths": data[3] if data[3] != 255 else "*",
    }, data[4:]


def _decode_object_id(data: bytes, length: int):
    if length != 4:
        raise ASN1Error(f"ObjectID must be 4 bytes, got {length}")
    v = int.from_bytes(data[:4], "big")
    obj_type = (v >> 22) & 0x3FF
    instance = v & 0x3FFFFF
    return {"type": obj_type, "instance": instance}, data[4:]


# ---------------------------------------------------------------------------
# Dispatch table by application tag number
# ---------------------------------------------------------------------------

APP_TAG_NAMES = {
    0: "Null", 1: "Boolean", 2: "UnsignedInt", 3: "SignedInt",
    4: "Real", 5: "Double", 6: "OctetString", 7: "CharString",
    8: "BitString", 9: "Enumerated", 10: "Date", 11: "Time",
    12: "ObjectIdentifier",
}


def _decode_app_primitive(tag_num: int, payload: bytes, length: int, lvt: int):
    """Décode une primitive application-tagged. Retourne (value, tail)."""
    if tag_num == 0:  # Null
        return None, payload
    if tag_num == 1:  # Boolean
        return bool(lvt), payload  # lvt = 0 ou 1, PAS de payload à consommer
    if tag_num == 2:
        v, tail = _decode_unsigned(payload, length)
        return v, tail
    if tag_num == 3:
        v, tail = _decode_signed(payload, length)
        return v, tail
    if tag_num == 4:
        v, tail = _decode_real(payload, length)
        return v, tail
    if tag_num == 5:
        v, tail = _decode_double(payload, length)
        return v, tail
    if tag_num == 6:
        v, tail = _decode_octet_string(payload, length)
        return v.hex(), tail
    if tag_num == 7:
        v, tail = _decode_char_string(payload, length)
        return v, tail
    if tag_num == 8:
        v, tail = _decode_bit_string(payload, length)
        return v, tail
    if tag_num == 9:
        v, tail = _decode_enumerated(payload, length)
        return v, tail
    if tag_num == 10:
        v, tail = _decode_date(payload, length)
        return v, tail
    if tag_num == 11:
        v, tail = _decode_time(payload, length)
        return v, tail
    if tag_num == 12:
        v, tail = _decode_object_id(payload, length)
        return v, tail
    # Unknown application tag
    return {"unknown_app_tag": tag_num, "hex": payload[:length].hex()}, payload[length:]


# ---------------------------------------------------------------------------
# Top-level iteration
# ---------------------------------------------------------------------------

def parse_next(data: bytes, i: int = 0) -> tuple[dict, int]:
    """
    Décode le prochain élément (tag + valeur). Retourne (item, cursor_after).
    Un item est un dict :
      {"tag": <n>, "class": "app"|"ctx", "kind": "primitive"|"open"|"close",
       "value": <val>, "raw_len": <n>}
    Pour "open": value = liste d'items à l'intérieur (récursif jusqu'au close).
    """
    tag_num, tag_cls, lvt, i = _decode_tag(data, i)
    cls_name = "ctx" if tag_cls else "app"

    if lvt == 6:  # Opening tag
        items = []
        while i < len(data):
            # Regarder si le prochain tag est un closing pour ce tag_num
            peek_b = data[i]
            peek_num = (peek_b >> 4) & 0x0F
            peek_cls = (peek_b >> 3) & 0x01
            peek_lvt = peek_b & 0x07
            if peek_num == 15:
                # extended tag
                if i + 1 < len(data):
                    peek_num = data[i + 1]
            if peek_lvt == 7 and peek_num == tag_num and peek_cls == tag_cls:
                # Consommer le closing
                _, _, _, i = _decode_tag(data, i)
                return {"tag": tag_num, "class": cls_name, "kind": "open",
                        "value": items, "raw_len": 0}, i
            item, i = parse_next(data, i)
            items.append(item)
        # Buffer épuisé sans closing → tag ouvert reste ouvert
        return {"tag": tag_num, "class": cls_name, "kind": "open",
                "value": items, "raw_len": 0}, i

    if lvt == 7:  # Closing tag orphelin (mal placé)
        return {"tag": tag_num, "class": cls_name, "kind": "close",
                "value": None, "raw_len": 0}, i

    length, i = _decode_length(data, i, lvt)
    payload = data[i:i + length] if length > 0 else b""

    if tag_cls == 0:  # Application
        val, _ = _decode_app_primitive(tag_num, payload, length, lvt)
    else:  # Context — on garde en bytes, le service saura l'interpréter
        val = payload

    return {"tag": tag_num, "class": cls_name, "kind": "primitive",
            "value": val, "raw_len": length}, i + length


def iter_tags(data: bytes, offset: int = 0) -> Iterator[dict]:
    """Énumère tous les items top-level à partir de offset."""
    i = offset
    while i < len(data):
        try:
            item, i = parse_next(data, i)
        except ASN1Error:
            break
        yield item


def parse_all(data: bytes, offset: int = 0) -> list[dict]:
    """Retourne la liste des items top-level."""
    return list(iter_tags(data, offset))


# ---------------------------------------------------------------------------
# Utilities pour extraire des valeurs typées depuis les items décodés
# ---------------------------------------------------------------------------

def get_ctx(items: list[dict], tag: int, default=None):
    """Retourne la valeur du premier context-tag matching."""
    for item in items:
        if item["class"] == "ctx" and item["tag"] == tag:
            return item["value"]
    return default


def get_ctx_item(items: list[dict], tag: int):
    """Retourne l'item entier (utile pour distinguer open/primitive)."""
    for item in items:
        if item["class"] == "ctx" and item["tag"] == tag:
            return item
    return None


def get_app(items: list[dict], tag: int, default=None):
    for item in items:
        if item["class"] == "app" and item["tag"] == tag:
            return item["value"]
    return default


def ctx_as_unsigned(raw: bytes) -> int:
    return int.from_bytes(raw, "big") if raw else 0


def ctx_as_object_id(raw: bytes) -> dict:
    if len(raw) != 4:
        return {"type": 0, "instance": 0}
    v = int.from_bytes(raw, "big")
    return {"type": (v >> 22) & 0x3FF, "instance": v & 0x3FFFFF}
