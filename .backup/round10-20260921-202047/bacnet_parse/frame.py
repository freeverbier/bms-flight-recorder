"""
Décodeur BACnet/IP complet — bytes bruts → dict structuré.

Chaîne : BVLC → NPDU → APDU → Service data (ASN.1 tagué).

L'entrée est un UDP payload. La sortie est un dict prêt à pousser dans ClickHouse
(bms.frames) et le stream SSE :
  {
    "bvlc_function": "Original-Broadcast-NPDU",
    "npdu": {"version": 1, "src_net": None, "dst_net": None, "hop_count": None},
    "apdu_type": "Unconfirmed-Request",
    "service": "iAm",
    "invoke_id": None,
    "object_ref": "device:1234",
    "property": None,
    "value": None,
    "value_num": None,
    "unit": "",
    "operation_detail": "I-Am device:1234 vendor=8 maxAPDU=1476",
    "extra": {...},
  }
"""

from __future__ import annotations

from . import asn1
from .enums import (
    apdu_type_name, bvlc_function_name, confirmed_service_name,
    object_ref, object_type_name, property_name, unconfirmed_service_name,
    unit_symbol, ABORT_REASONS, ERROR_CLASSES, REJECT_REASONS, PROPERTY_IDS,
)


class BACnetDecodeError(Exception):
    pass


# ---------------------------------------------------------------------------
# BVLC
# ---------------------------------------------------------------------------

def decode_bvlc(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 4:
        raise BACnetDecodeError("BVLC header truncated")
    if data[0] != 0x81:
        raise BACnetDecodeError(f"BVLC type mismatch: {data[0]:#x} (expected 0x81)")
    function = data[1]
    length = int.from_bytes(data[2:4], "big")
    if length > len(data):
        raise BACnetDecodeError(f"BVLC length {length} > packet {len(data)}")
    bvlc = {
        "type": 0x81,
        "function": function,
        "function_name": bvlc_function_name(function),
        "length": length,
    }
    # Forwarded-NPDU : 6 octets d'IP/port origine avant le NPDU
    if function == 0x04 and len(data) >= 10:
        bvlc["forwarded_from"] = f"{data[4]}.{data[5]}.{data[6]}.{data[7]}:{int.from_bytes(data[8:10],'big')}"
        return bvlc, data[10:length]
    return bvlc, data[4:length]


# ---------------------------------------------------------------------------
# NPDU
# ---------------------------------------------------------------------------

def decode_npdu(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 2:
        raise BACnetDecodeError("NPDU truncated")
    version = data[0]
    control = data[1]
    i = 2
    npdu = {
        "version": version,
        "control": control,
        "is_network_msg": bool(control & 0x80),
        "expects_reply": bool(control & 0x04),
        "priority": control & 0x03,
        "dst_net": None,
        "dst_addr": None,
        "src_net": None,
        "src_addr": None,
        "hop_count": None,
    }
    # DNET present ?
    if control & 0x20:
        if i + 3 > len(data):
            raise BACnetDecodeError("NPDU DNET truncated")
        npdu["dst_net"] = int.from_bytes(data[i:i+2], "big")
        dlen = data[i+2]
        i += 3
        if dlen:
            npdu["dst_addr"] = data[i:i+dlen].hex()
            i += dlen
    # SNET present ?
    if control & 0x08:
        if i + 3 > len(data):
            raise BACnetDecodeError("NPDU SNET truncated")
        npdu["src_net"] = int.from_bytes(data[i:i+2], "big")
        slen = data[i+2]
        i += 3
        if slen:
            npdu["src_addr"] = data[i:i+slen].hex()
            i += slen
    # Hop count si DNET
    if control & 0x20:
        if i < len(data):
            npdu["hop_count"] = data[i]
            i += 1
    return npdu, data[i:]


# ---------------------------------------------------------------------------
# APDU
# ---------------------------------------------------------------------------

def decode_apdu(data: bytes) -> dict:
    if not data:
        raise BACnetDecodeError("APDU empty")
    b0 = data[0]
    pdu_type = (b0 >> 4) & 0x0F
    result = {
        "pdu_type": pdu_type,
        "pdu_type_name": apdu_type_name(pdu_type),
        "invoke_id": None,
        "service": None,
        "service_data": {},
    }

    if pdu_type == 0x0:
        return _decode_confirmed_request(data, result)
    if pdu_type == 0x1:
        return _decode_unconfirmed_request(data, result)
    if pdu_type == 0x2:
        return _decode_simple_ack(data, result)
    if pdu_type == 0x3:
        return _decode_complex_ack(data, result)
    if pdu_type == 0x4:
        return _decode_segment_ack(data, result)
    if pdu_type == 0x5:
        return _decode_error(data, result)
    if pdu_type == 0x6:
        return _decode_reject(data, result)
    if pdu_type == 0x7:
        return _decode_abort(data, result)
    result["service_data"] = {"raw": data.hex()}
    return result


def _decode_confirmed_request(data: bytes, result: dict) -> dict:
    if len(data) < 4:
        return result
    b0 = data[0]
    segmented = bool(b0 & 0x08)
    result["max_segments"] = (data[1] >> 4) & 0x07
    result["max_apdu"] = data[1] & 0x0F
    result["invoke_id"] = data[2]
    i = 3
    if segmented:
        result["sequence_number"] = data[i]; i += 1
        result["proposed_window"] = data[i]; i += 1
    service = data[i]; i += 1
    result["service_code"] = service
    result["service"] = confirmed_service_name(service)
    payload = data[i:]
    result["service_data"] = _decode_confirmed_service_data(service, payload)
    return result


def _decode_unconfirmed_request(data: bytes, result: dict) -> dict:
    if len(data) < 2:
        return result
    service = data[1]
    result["service_code"] = service
    result["service"] = unconfirmed_service_name(service)
    payload = data[2:]
    result["service_data"] = _decode_unconfirmed_service_data(service, payload)
    return result


def _decode_simple_ack(data: bytes, result: dict) -> dict:
    if len(data) < 3:
        return result
    result["invoke_id"] = data[1]
    service = data[2]
    result["service_code"] = service
    result["service"] = confirmed_service_name(service)
    return result


def _decode_complex_ack(data: bytes, result: dict) -> dict:
    if len(data) < 3:
        return result
    b0 = data[0]
    segmented = bool(b0 & 0x08)
    result["invoke_id"] = data[1]
    i = 2
    if segmented:
        result["sequence_number"] = data[i]; i += 1
        result["proposed_window"] = data[i]; i += 1
    service = data[i]; i += 1
    result["service_code"] = service
    result["service"] = confirmed_service_name(service)
    payload = data[i:]
    result["service_data"] = _decode_ack_service_data(service, payload)
    return result


def _decode_segment_ack(data: bytes, result: dict) -> dict:
    if len(data) < 5:
        return result
    result["invoke_id"] = data[1]
    result["sequence_number"] = data[2]
    result["actual_window"] = data[3]
    return result


def _decode_error(data: bytes, result: dict) -> dict:
    if len(data) < 3:
        return result
    result["invoke_id"] = data[1]
    result["service_code"] = data[2]
    result["service"] = confirmed_service_name(data[2])
    items = asn1.parse_all(data[3:])
    err_class = asn1.get_app(items, 9)  # Enumerated
    err_code = None
    # Le second Enumerated est le code d'erreur
    enums_found = [x["value"] for x in items if x["class"] == "app" and x["tag"] == 9]
    if len(enums_found) >= 2:
        err_code = enums_found[1]
    result["service_data"] = {
        "error_class": ERROR_CLASSES.get(err_class or -1, f"class:{err_class}"),
        "error_code": err_code,
    }
    return result


def _decode_reject(data: bytes, result: dict) -> dict:
    if len(data) < 3:
        return result
    result["invoke_id"] = data[1]
    reason = data[2]
    result["service_data"] = {
        "reject_reason": REJECT_REASONS.get(reason, f"reject:{reason}"),
    }
    return result


def _decode_abort(data: bytes, result: dict) -> dict:
    if len(data) < 3:
        return result
    result["invoke_id"] = data[1]
    reason = data[2]
    result["service_data"] = {
        "abort_reason": ABORT_REASONS.get(reason, f"abort:{reason}"),
    }
    return result


# ---------------------------------------------------------------------------
# Service data decoders
# ---------------------------------------------------------------------------

def _decode_unconfirmed_service_data(service: int, payload: bytes) -> dict:
    items = asn1.parse_all(payload)
    if service == 8:  # whoIs
        low = asn1.get_ctx(items, 0)
        high = asn1.get_ctx(items, 1)
        return {
            "low_limit": asn1.ctx_as_unsigned(low) if low else "*",
            "high_limit": asn1.ctx_as_unsigned(high) if high else "*",
        }
    if service == 0:  # iAm
        # Application-tagged sequence: object-id, max-apdu, segmentation, vendor-id
        obj_id = asn1.get_app(items, 12)
        max_apdu = asn1.get_app(items, 2)
        segmentations = [x["value"] for x in items if x["class"] == "app" and x["tag"] == 9]
        segmentation = segmentations[0] if segmentations else None
        # vendor_id = 2ème UnsignedInt
        unsigneds = [x["value"] for x in items if x["class"] == "app" and x["tag"] == 2]
        vendor_id = unsigneds[1] if len(unsigneds) >= 2 else None
        return {
            "device_id": obj_id["instance"] if obj_id else None,
            "device_object": obj_id,
            "max_apdu": max_apdu,
            "segmentation": _seg_name(segmentation),
            "vendor_id": vendor_id,
        }
    if service == 2:  # unconfirmedCOVNotification
        return _decode_cov_notification(items)
    if service == 7:  # whoHas
        return {"raw_items": _dump_items(items)}
    if service == 1:  # iHave
        return {"raw_items": _dump_items(items)}
    return {"raw": payload.hex()}


def _decode_confirmed_service_data(service: int, payload: bytes) -> dict:
    items = asn1.parse_all(payload)
    if service == 12:  # readProperty request
        obj_raw = asn1.get_ctx(items, 0)
        prop_raw = asn1.get_ctx(items, 1)
        idx_raw = asn1.get_ctx(items, 2)
        return {
            "object": asn1.ctx_as_object_id(obj_raw) if obj_raw else None,
            "property": asn1.ctx_as_unsigned(prop_raw) if prop_raw else None,
            "property_name": property_name(asn1.ctx_as_unsigned(prop_raw)) if prop_raw else None,
            "array_index": asn1.ctx_as_unsigned(idx_raw) if idx_raw else None,
        }
    if service == 15:  # readPropertyMultiple request
        return {"specs": _decode_rpm_request(items)}
    if service == 16:  # writeProperty request
        obj_raw = asn1.get_ctx(items, 0)
        prop_raw = asn1.get_ctx(items, 1)
        idx_raw = asn1.get_ctx(items, 2)
        value_item = asn1.get_ctx_item(items, 3)
        prio_raw = asn1.get_ctx(items, 4)
        return {
            "object": asn1.ctx_as_object_id(obj_raw) if obj_raw else None,
            "property": asn1.ctx_as_unsigned(prop_raw) if prop_raw else None,
            "property_name": property_name(asn1.ctx_as_unsigned(prop_raw)) if prop_raw else None,
            "array_index": asn1.ctx_as_unsigned(idx_raw) if idx_raw else None,
            "value": _extract_value_from_ctx_open(value_item),
            "priority": asn1.ctx_as_unsigned(prio_raw) if prio_raw else None,
        }
    if service == 1:  # confirmedCOVNotification
        return _decode_cov_notification(items)
    if service == 6:  # subscribeCOV
        return {"raw_items": _dump_items(items)}
    return {"raw": payload.hex()}


def _decode_ack_service_data(service: int, payload: bytes) -> dict:
    items = asn1.parse_all(payload)
    if service == 12:  # readProperty ACK
        obj_raw = asn1.get_ctx(items, 0)
        prop_raw = asn1.get_ctx(items, 1)
        idx_raw = asn1.get_ctx(items, 2)
        value_item = asn1.get_ctx_item(items, 3)
        return {
            "object": asn1.ctx_as_object_id(obj_raw) if obj_raw else None,
            "property": asn1.ctx_as_unsigned(prop_raw) if prop_raw else None,
            "property_name": property_name(asn1.ctx_as_unsigned(prop_raw)) if prop_raw else None,
            "array_index": asn1.ctx_as_unsigned(idx_raw) if idx_raw else None,
            "value": _extract_value_from_ctx_open(value_item),
        }
    if service == 15:  # readPropertyMultiple ACK
        return {"results": _decode_rpm_ack(items)}
    return {"raw": payload.hex()}


def _decode_rpm_request(items: list) -> list:
    """Décode une liste de Read-Access-Specification."""
    specs = []
    current_obj = None
    for item in items:
        if item["class"] == "ctx" and item["tag"] == 0 and item["kind"] == "primitive":
            current_obj = asn1.ctx_as_object_id(item["value"])
        elif item["class"] == "ctx" and item["tag"] == 1 and item["kind"] == "open":
            # Liste de Property Reference
            props = []
            sub = item["value"]
            for p in sub:
                if p["class"] == "ctx" and p["tag"] == 0:
                    pid = asn1.ctx_as_unsigned(p["value"]) if isinstance(p["value"], bytes) else 0
                    props.append({"property": pid, "property_name": property_name(pid)})
            specs.append({"object": current_obj, "properties": props})
    return specs


def _decode_rpm_ack(items: list) -> list:
    """Décode une liste de Read-Access-Result."""
    results = []
    current_obj = None
    for item in items:
        if item["class"] == "ctx" and item["tag"] == 0 and item["kind"] == "primitive":
            current_obj = asn1.ctx_as_object_id(item["value"])
        elif item["class"] == "ctx" and item["tag"] == 1 and item["kind"] == "open":
            # Liste de Result par propriété
            props = []
            current_pid = None
            current_pid_name = None
            for p in item["value"]:
                if p["class"] == "ctx" and p["tag"] == 2 and p["kind"] == "primitive":
                    current_pid = asn1.ctx_as_unsigned(p["value"]) if isinstance(p["value"], bytes) else 0
                    current_pid_name = property_name(current_pid)
                elif p["class"] == "ctx" and p["tag"] == 4 and p["kind"] == "open":
                    val = _extract_value_from_open_items(p["value"])
                    props.append({"property": current_pid, "property_name": current_pid_name, "value": val})
                elif p["class"] == "ctx" and p["tag"] == 5 and p["kind"] == "open":
                    # Error
                    err_items = p["value"]
                    err_class = None
                    err_code = None
                    for e in err_items:
                        if e["class"] == "app" and e["tag"] == 9:
                            if err_class is None:
                                err_class = e["value"]
                            else:
                                err_code = e["value"]
                    props.append({
                        "property": current_pid, "property_name": current_pid_name,
                        "error": {"class": ERROR_CLASSES.get(err_class or -1, f"class:{err_class}"),
                                  "code": err_code},
                    })
            results.append({"object": current_obj, "properties": props})
    return results


def _decode_cov_notification(items: list) -> dict:
    sub_pid = asn1.get_ctx(items, 0)
    initiating = asn1.get_ctx(items, 1)
    monitored = asn1.get_ctx(items, 2)
    time_rem = asn1.get_ctx(items, 3)
    list_item = asn1.get_ctx_item(items, 4)
    values = []
    if list_item and list_item["kind"] == "open":
        current_pid = None
        for p in list_item["value"]:
            if p["class"] == "ctx" and p["tag"] == 0 and p["kind"] == "primitive":
                current_pid = asn1.ctx_as_unsigned(p["value"]) if isinstance(p["value"], bytes) else 0
            elif p["class"] == "ctx" and p["tag"] == 2 and p["kind"] == "open":
                v = _extract_value_from_open_items(p["value"])
                values.append({
                    "property": current_pid,
                    "property_name": property_name(current_pid or 0),
                    "value": v,
                })
    return {
        "subscriber_pid": asn1.ctx_as_unsigned(sub_pid) if sub_pid else None,
        "initiating_device": asn1.ctx_as_object_id(initiating) if initiating else None,
        "monitored_object": asn1.ctx_as_object_id(monitored) if monitored else None,
        "time_remaining": asn1.ctx_as_unsigned(time_rem) if time_rem else None,
        "values": values,
    }


# ---------------------------------------------------------------------------
# Value extraction depuis un context-tag "open" (property-value)
# ---------------------------------------------------------------------------

def _extract_value_from_ctx_open(item):
    """Un context-tag 3 en open contient un ou plusieurs application values."""
    if not item or item["kind"] != "open":
        return None
    return _extract_value_from_open_items(item["value"])


def _extract_value_from_open_items(sub_items: list):
    """Extrait la valeur métier depuis les items inside un opening tag."""
    values = []
    for it in sub_items:
        if it["class"] == "app":
            values.append(it["value"])
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg_name(v):
    return {0: "segmented-both", 1: "segmented-transmit",
            2: "segmented-receive", 3: "no-segmentation"}.get(v, f"seg:{v}")


def _dump_items(items):
    return [{"class": it["class"], "tag": it["tag"], "kind": it["kind"]} for it in items]


# ---------------------------------------------------------------------------
# Entrée principale : bytes → dict prêt pour l'ingestion
# ---------------------------------------------------------------------------

def decode_frame(payload: bytes, src_ip: str = "", src_port: int = 0) -> dict:
    """Décode un paquet UDP BACnet/IP complet."""
    result = {
        "raw_hex": payload.hex(),
        "frame_len": len(payload),
        "bvlc_function": None,
        "bvlc_function_code": None,
        "apdu_type": None,
        "service": None,
        "invoke_id": None,
        "object_ref": None,
        "property": None,
        "value": "",
        "value_num": None,
        "unit": "",
        "operation_detail": "",
        "extra": {},
    }
    try:
        bvlc, remainder = decode_bvlc(payload)
        result["bvlc_function"] = bvlc["function_name"]
        result["bvlc_function_code"] = bvlc["function"]
        if bvlc.get("forwarded_from"):
            result["extra"]["forwarded_from"] = bvlc["forwarded_from"]
        # BVLC-only messages (Result, Register-Foreign-Device...)
        if bvlc["function"] in (0x00, 0x05):
            result["operation_detail"] = bvlc["function_name"]
            result["extra"]["bvlc_payload"] = remainder.hex()
            return result

        npdu, apdu_bytes = decode_npdu(remainder)
        result["extra"]["npdu_priority"] = npdu["priority"]
        if npdu["src_net"] is not None:
            result["extra"]["snet"] = npdu["src_net"]
            result["extra"]["saddr"] = npdu["src_addr"]
        if npdu["dst_net"] is not None:
            result["extra"]["dnet"] = npdu["dst_net"]
            result["extra"]["daddr"] = npdu["dst_addr"]

        if npdu["is_network_msg"] or not apdu_bytes:
            result["operation_detail"] = f"NPDU network-msg ctrl=0x{npdu['control']:02x}"
            return result

        apdu = decode_apdu(apdu_bytes)
        result["apdu_type"] = apdu["pdu_type_name"]
        result["service"] = apdu["service"]
        result["invoke_id"] = apdu["invoke_id"]
        _hydrate_from_service(result, apdu)
    except BACnetDecodeError as exc:
        result["extra"]["decode_error"] = str(exc)
        result["operation_detail"] = f"Decode error: {exc}"
    except Exception as exc:
        result["extra"]["decode_error"] = f"{type(exc).__name__}: {exc}"
        result["operation_detail"] = f"Decode error: {exc}"
    return result


def _hydrate_from_service(result: dict, apdu: dict) -> None:
    """Enrichit result à partir des données de service : object_ref, property, value, unit, operation_detail."""
    service = apdu.get("service") or ""
    sd = apdu.get("service_data") or {}
    parts = [apdu.get("pdu_type_name") or "", service]

    if service == "iAm":
        did = sd.get("device_id")
        if did is not None:
            result["object_ref"] = f"device:{did}"
        result["extra"].update({
            "vendor_id": sd.get("vendor_id"),
            "max_apdu": sd.get("max_apdu"),
            "segmentation": sd.get("segmentation"),
        })
        result["operation_detail"] = f"I-Am device:{did} vendor={sd.get('vendor_id')} maxAPDU={sd.get('max_apdu')}"
        return

    if service == "whoIs":
        low = sd.get("low_limit")
        high = sd.get("high_limit")
        result["operation_detail"] = f"Who-Is (low={low} high={high})"
        return

    if service == "readProperty":
        obj = sd.get("object") or {}
        pname = sd.get("property_name") or ""
        if obj:
            result["object_ref"] = object_ref(obj)
        result["property"] = pname or None
        # Value présente uniquement en Complex-ACK
        val = sd.get("value")
        _apply_scalar_value(result, val)
        idx = sd.get("array_index")
        idx_txt = f"[{idx}]" if idx is not None else ""
        val_txt = f" = {result['value']}{result['unit']}" if result["value"] != "" else ""
        result["operation_detail"] = f"ReadProperty {result['object_ref']} {pname}{idx_txt}{val_txt}"
        return

    if service == "writeProperty":
        obj = sd.get("object") or {}
        pname = sd.get("property_name") or ""
        val = sd.get("value")
        prio = sd.get("priority")
        if obj:
            result["object_ref"] = object_ref(obj)
        result["property"] = pname or None
        _apply_scalar_value(result, val)
        prio_txt = f" (priority={prio})" if prio else ""
        val_txt = f" = {result['value']}{result['unit']}" if result["value"] != "" else ""
        result["operation_detail"] = f"WriteProperty {result['object_ref']} {pname}{val_txt}{prio_txt}"
        return

    if service == "readPropertyMultiple":
        specs = sd.get("specs") or sd.get("results") or []
        first_val = None
        first_obj = None
        first_prop = None
        for spec in specs:
            obj = spec.get("object") or {}
            for p in spec.get("properties", []):
                if "value" in p and p["value"] is not None:
                    first_obj = obj
                    first_prop = p.get("property_name")
                    first_val = p["value"]
                    break
            if first_val is not None:
                break
        if first_obj:
            result["object_ref"] = object_ref(first_obj)
        if first_prop:
            result["property"] = first_prop
        _apply_scalar_value(result, first_val)
        n_objs = len(specs)
        result["operation_detail"] = f"ReadPropertyMultiple ({n_objs} obj)"
        # On stocke les autres résultats dans extra pour analyse détaillée UI
        result["extra"]["rpm_results"] = _summarise_rpm(specs)
        return

    if service in ("confirmedCOVNotification", "unconfirmedCOVNotification"):
        mon = sd.get("monitored_object") or {}
        vals = sd.get("values") or []
        if mon:
            result["object_ref"] = object_ref(mon)
        # Prendre present-value en priorité
        pv = next((v for v in vals if v.get("property_name") == "present-value"), None)
        if pv is None and vals:
            pv = vals[0]
        if pv:
            result["property"] = pv.get("property_name")
            _apply_scalar_value(result, pv.get("value"))
        # Chercher units dans le même paquet
        units_val = next((v for v in vals if v.get("property_name") == "units"), None)
        if units_val and isinstance(units_val.get("value"), int):
            result["unit"] = unit_symbol(units_val["value"]) or result["unit"]
        did = sd.get("initiating_device") or {}
        result["extra"]["initiating_device"] = did.get("instance")
        val_txt = f" = {result['value']}{result['unit']}" if result["value"] != "" else ""
        result["operation_detail"] = f"COV {result['object_ref']} {result['property'] or ''}{val_txt}"
        return

    # Autres services : opération générique
    if apdu.get("pdu_type_name") in ("Error", "Reject", "Abort"):
        result["operation_detail"] = f"{apdu['pdu_type_name']} inv={apdu.get('invoke_id')} " + \
            str(sd)
        result["extra"].update(sd)
        return

    result["operation_detail"] = " ".join(p for p in parts if p)
    if sd:
        result["extra"]["service_raw"] = str(sd)[:200]


def _apply_scalar_value(result: dict, val) -> None:
    """Extrait value / value_num depuis une valeur BACnet décodée."""
    if val is None:
        return
    if isinstance(val, list):
        # Plusieurs valeurs : on prend la première scalaire pour value_num
        result["value"] = ", ".join(str(v) for v in val)
        first = val[0]
        if isinstance(first, (int, float)):
            result["value_num"] = float(first)
        return
    if isinstance(val, bool):
        result["value"] = "true" if val else "false"
        result["value_num"] = 1.0 if val else 0.0
        return
    if isinstance(val, (int, float)):
        result["value"] = str(val)
        result["value_num"] = float(val)
        return
    if isinstance(val, dict):
        # ObjectID, Date, Time, BitString
        if "type" in val and "instance" in val:
            result["value"] = object_ref(val)
        else:
            result["value"] = str(val)
        return
    result["value"] = str(val)


def _summarise_rpm(specs: list) -> dict:
    """Résume les résultats RPM pour extra{}."""
    out = {}
    for spec in specs:
        obj = spec.get("object") or {}
        key = object_ref(obj) if obj else "?"
        props_summary = []
        for p in spec.get("properties", []):
            pname = p.get("property_name") or "?"
            if "error" in p:
                props_summary.append(f"{pname}=<error:{p['error'].get('code')}>")
            else:
                v = p.get("value")
                if isinstance(v, (int, float, str, bool)):
                    props_summary.append(f"{pname}={v}")
                elif v is not None:
                    props_summary.append(f"{pname}={type(v).__name__}")
        out[key] = "; ".join(props_summary)[:200]
    return out
