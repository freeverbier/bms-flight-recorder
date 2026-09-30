"""
Décodeur cEMI (Common External Message Interface).

Refactor Round 5 : couvre l'intégralité de la spec application layer KNX
via la table APCI + décodage N2 (résumé structuré) pour chaque service.

Structure d'une trame cEMI L_Data.ind (message code 0x29) :
   0: msg_code       (0x29 = L_Data.ind, 0x2E = L_Data.con)
   1: add_info_len
   2: ctrl1
   3: ctrl2
   4-5: source (individual address)
   6-7: destination (individual OU group selon ctrl2 bit 7)
   8: data_length (npdu length excluding tpci byte)
   9: TPCI + APCI high (bits 15-8)
   10: APCI low + data (short) OU APCI low + payload en 11+
   11+: payload (pour APCI 10-bit ou données longues)

Le format retourné par decode_cemi() est un dict enrichi utilisé par le collector
pour construire le payload POST vers l'API.
"""

from __future__ import annotations

import logging
from typing import Optional

from .apci import (
    ApciCategory,
    ApciDef,
    TpciKind,
    decode_tpci,
    has_apci_payload,
    lookup_apci,
)

log = logging.getLogger("knx-collector.cemi")

# Message codes cEMI courants
MSG_CODE_L_DATA_IND = 0x29
MSG_CODE_L_DATA_CON = 0x2E
MSG_CODE_L_DATA_REQ = 0x11


# ---------------------------------------------------------------------------
# Adressage
# ---------------------------------------------------------------------------

def format_individual(raw: int) -> str:
    """Convertit un 16-bit en 'area.line.device' (ex: 1.1.42)."""
    area = (raw >> 12) & 0x0F
    line = (raw >> 8) & 0x0F
    device = raw & 0xFF
    return f"{area}.{line}.{device}"


def format_group(raw: int) -> str:
    """Convertit un 16-bit en 'main/middle/sub' (adressage 3 niveaux, standard)."""
    main = (raw >> 11) & 0x1F
    middle = (raw >> 8) & 0x07
    sub = raw & 0xFF
    return f"{main}/{middle}/{sub}"


# ---------------------------------------------------------------------------
# Décodeurs de payload par APCI (retournent le résumé N2 dans "operation_detail")
# ---------------------------------------------------------------------------

def _describe_memory(apci: ApciDef, payload: bytes, param_bits: int = 0) -> tuple[str, dict]:
    """
    Memory_Read/Response/Write.
    param_bits (4 bits, dans byte APCI low) = count.
    Payload = addr(2 bytes) + optional data(count bytes).
    """
    if len(payload) < 2:
        return apci.short_name, {"payload_hex": payload.hex()}
    count = param_bits & 0x0F
    addr = (payload[0] << 8) | payload[1]
    data = payload[2:2 + count] if len(payload) > 2 else b""
    extra = {"count": str(count), "address": f"0x{addr:04X}"}
    if data:
        extra["data"] = data.hex()
    detail = f"{apci.short_name} addr=0x{addr:04X} count={count}"
    if data:
        detail += f" data={data.hex()}"
    return detail, extra


def _describe_property_value(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """PropertyValue_Read/Response/Write : obj_index, prop_id, nr_elems, start_index, data."""
    if len(payload) < 4:
        return apci.short_name, {"payload_hex": payload.hex()}
    obj_idx = payload[0]
    prop_id = payload[1]
    nr_elems = (payload[2] >> 4) & 0x0F
    start_idx = ((payload[2] & 0x0F) << 8) | payload[3]
    data = payload[4:] if len(payload) > 4 else b""
    extra = {
        "obj_index": str(obj_idx),
        "prop_id": str(prop_id),
        "nr_elems": str(nr_elems),
        "start_index": str(start_idx),
    }
    if data:
        extra["data"] = data.hex()
    detail = f"{apci.short_name} obj={obj_idx} prop={prop_id} nElems={nr_elems} start={start_idx}"
    if data:
        detail += f" data={data.hex()}"
    return detail, extra


def _describe_property_desc(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """PropertyDescription_Read/Response."""
    if len(payload) < 3:
        return apci.short_name, {"payload_hex": payload.hex()}
    obj_idx = payload[0]
    prop_id = payload[1]
    prop_index = payload[2]
    extra = {"obj_index": str(obj_idx), "prop_id": str(prop_id), "prop_index": str(prop_index)}
    detail = f"{apci.short_name} obj={obj_idx} prop={prop_id} idx={prop_index}"
    if len(payload) > 3:
        extra["desc_data"] = payload[3:].hex()
        detail += f" data={payload[3:].hex()}"
    return detail, extra


def _describe_device_descriptor(apci: ApciDef, payload: bytes, param_bits: int = 0) -> tuple[str, dict]:
    """
    DeviceDescriptor_Read/Response.
    param_bits (6 bits) = descriptor_type (0 = mask version, 1 = system state).
    Payload = descriptor value (2 bytes pour Response).
    """
    dtype = param_bits & 0x3F
    extra: dict[str, str] = {"descriptor_type": str(dtype)}
    detail = f"{apci.short_name} type={dtype}"
    if payload:
        extra["descriptor"] = payload.hex()
        detail += f" value={payload.hex()}"
    return detail, extra


def _describe_authorize(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """Authorize_Request : reserved(1) + key(4). Authorize_Response : level(1)."""
    if apci.code == 0x3D1 and len(payload) >= 5:
        key = payload[1:5]
        return f"{apci.short_name} key={key.hex()}", {"key": key.hex()}
    if apci.code == 0x3D2 and len(payload) >= 1:
        return f"{apci.short_name} level={payload[0]}", {"level": str(payload[0])}
    return apci.short_name, {"payload_hex": payload.hex()}


def _describe_key(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """Key_Write : level(1) + key(4). Key_Response : level(1)."""
    if apci.code == 0x3D3 and len(payload) >= 5:
        return f"{apci.short_name} level={payload[0]} key={payload[1:5].hex()}", {
            "level": str(payload[0]), "key": payload[1:5].hex()}
    if apci.code == 0x3D4 and len(payload) >= 1:
        return f"{apci.short_name} level={payload[0]}", {"level": str(payload[0])}
    return apci.short_name, {"payload_hex": payload.hex()}


def _describe_ind_addr_write(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """IndividualAddress_Write : new_address (2 bytes)."""
    if len(payload) < 2:
        return apci.short_name, {}
    new_addr = format_individual((payload[0] << 8) | payload[1])
    return f"{apci.short_name} new={new_addr}", {"new_address": new_addr}


def _describe_ind_addr_serial(apci: ApciDef, payload: bytes) -> tuple[str, dict]:
    """IndAddrSerialRead/Response/Write : serial(6) + [new_addr(2) pour Write]."""
    if len(payload) < 6:
        return apci.short_name, {"payload_hex": payload.hex()}
    serial = payload[:6].hex()
    extra = {"serial": serial}
    detail = f"{apci.short_name} serial={serial}"
    if apci.code == 0x3DE and len(payload) >= 8:
        new_addr = format_individual((payload[6] << 8) | payload[7])
        extra["new_address"] = new_addr
        detail += f" new={new_addr}"
    return detail, extra


def _describe_adc(apci: ApciDef, payload: bytes, param_bits: int = 0) -> tuple[str, dict]:
    """
    ADC_Read : channel_nr(6 bits) + read_count(1 byte).
    ADC_Response : channel_nr(6 bits) + read_count(1 byte) + sum(2 bytes).
    """
    channel = param_bits & 0x3F
    extra: dict[str, str] = {"channel": str(channel)}
    detail = f"{apci.short_name} channel={channel}"
    if payload:
        read_count = payload[0]
        extra["read_count"] = str(read_count)
        detail += f" count={read_count}"
        if apci.code == 0x1C0 and len(payload) >= 3:
            adc_sum = (payload[1] << 8) | payload[2]
            extra["sum"] = str(adc_sum)
            detail += f" sum={adc_sum}"
    return detail, extra


def _describe_restart(apci: ApciDef, payload: bytes, param_bits: int = 0) -> tuple[str, dict]:
    """
    Restart : bit 5 = "response flag", bit 4..0 = erase_code (1 = confirmed restart).
    param_bits (6 bits) porte cette info. Payload vide pour restart basic.
    """
    response = bool(param_bits & 0x20)
    erase_code = param_bits & 0x1F
    if erase_code == 0:
        return f"{apci.short_name} (basic)", {"kind": "basic",
                                              "response": "1" if response else "0"}
    types_map = {1: "MasterReset", 2: "MasterReset(erase_setup)"}
    kind = types_map.get(erase_code, f"erase_code={erase_code}")
    return (f"{apci.short_name} {kind}",
            {"kind": kind, "response": "1" if response else "0"})


# Dispatch : APCI code → décrypteur payload
_APCI_DISPATCHERS = {
    0x0C0: _describe_ind_addr_write,
    0x3DC: _describe_ind_addr_serial,
    0x3DD: _describe_ind_addr_serial,
    0x3DE: _describe_ind_addr_serial,
    0x180: _describe_adc,
    0x1C0: _describe_adc,
    0x300: _describe_device_descriptor,
    0x340: _describe_device_descriptor,
    0x380: _describe_restart,
    0x200: _describe_memory,
    0x240: _describe_memory,
    0x280: _describe_memory,
    0x2C0: _describe_memory,
    0x2C1: _describe_memory,
    0x2C2: _describe_memory,
    0x3D1: _describe_authorize,
    0x3D2: _describe_authorize,
    0x3D3: _describe_key,
    0x3D4: _describe_key,
    0x3D5: _describe_property_value,
    0x3D6: _describe_property_value,
    0x3D7: _describe_property_value,
    0x3D8: _describe_property_desc,
    0x3D9: _describe_property_desc,
}


def describe_apci(apci: ApciDef, payload: bytes, param_bits: int = 0) -> tuple[str, dict]:
    """
    Retourne (operation_detail, extra_dict) pour le résumé N2.
    param_bits = bits bas de l'octet APCI (4 pour Memory, 6 pour DeviceDescriptor/ADC/Restart).
    Fallback : nom court + payload hex si pas de décrypteur spécialisé.
    """
    dispatcher = _APCI_DISPATCHERS.get(apci.code)
    if dispatcher:
        try:
            # Certains dispatchers acceptent param_bits, d'autres non
            return dispatcher(apci, payload, param_bits)
        except TypeError:
            return dispatcher(apci, payload)
    if payload:
        return f"{apci.short_name} data={payload.hex()}", {"payload_hex": payload.hex()}
    return apci.short_name, {}


# ---------------------------------------------------------------------------
# Décodeur principal cEMI
# ---------------------------------------------------------------------------

def decode_cemi(raw: bytes, dpt_registry=None, ga_registry=None) -> Optional[dict]:
    """
    Décode une trame cEMI L_Data.ind (msg_code 0x29) ou L_Data.con (0x2E).

    dpt_registry : instance DptRegistry (peut être None) — pour décoder GroupValue.
    ga_registry  : dict {"1/2/3": {"name": "Salon on", "dpt": "1.001"}} — pour matcher
                   l'adresse de groupe avec sa sémantique.

    Retourne None si la trame n'est pas décodable (trop courte, format inconnu).
    Sinon un dict complet prêt à envoyer au collector :
        {
            "source": "1.0.42",
            "destination": "2/3/17",
            "address_type": "group" | "individual" | "broadcast",
            "apci": "GroupValueWrite",
            "apci_category": "runtime",
            "tpci": "T_Data_Group",
            "operation_detail": "GroupValueWrite value=1",
            "value": "1",
            "value_num": 1.0,
            "unit": "",
            "dpt": "1.001",
            "point_name": "Salon on",
            "priority": "normal",
            "hop_count": 6,
            "extra": {...},
            "raw_hex": "...",
        }
    """
    if len(raw) < 11:
        return None

    msg_code = raw[0]
    if msg_code not in (MSG_CODE_L_DATA_IND, MSG_CODE_L_DATA_CON, MSG_CODE_L_DATA_REQ):
        return None

    add_info_len = raw[1]
    header_len = 2 + add_info_len
    if len(raw) < header_len + 9:
        return None

    ctrl1 = raw[header_len]
    ctrl2 = raw[header_len + 1]
    src_raw = (raw[header_len + 2] << 8) | raw[header_len + 3]
    dst_raw = (raw[header_len + 4] << 8) | raw[header_len + 5]
    npdu_len = raw[header_len + 6]

    # ctrl1 bits : bit 2 = priority, bits 3-4 = system broadcast, etc.
    priority_bits = (ctrl1 >> 2) & 0x03
    priority_map = {0: "system", 1: "urgent", 2: "normal", 3: "low"}
    priority = priority_map.get(priority_bits, "normal")

    # ctrl2 bit 7 : 0 = individual addr, 1 = group addr ; bits 4-6 = hop count
    dst_is_group = bool(ctrl2 & 0x80)
    hop_count = (ctrl2 >> 4) & 0x07

    src = format_individual(src_raw)
    if dst_is_group and dst_raw == 0:
        destination = "broadcast"
        address_type = "broadcast"
    elif dst_is_group:
        destination = format_group(dst_raw)
        address_type = "group"
    else:
        destination = format_individual(dst_raw)
        address_type = "individual"

    # TPCI + APCI : octets 9 et 10
    byte6 = raw[header_len + 7]  # TPCI + APCI bits hauts
    byte7 = raw[header_len + 8]  # APCI bits bas + éventuellement data
    tpci = decode_tpci(byte6, address_type)

    # Trames de contrôle transport pur (Connect, Disconnect, ACK, NACK)
    if not has_apci_payload(tpci):
        return {
            "source": src,
            "destination": destination,
            "address_type": address_type,
            "apci": tpci.kind.value,
            "apci_category": "diagnostic",
            "tpci": tpci.kind.value,
            "operation_detail": f"{tpci.kind.value}"
                                + (f" seq={tpci.seq_no}" if tpci.seq_no is not None else ""),
            "value": "",
            "value_num": None,
            "unit": "",
            "dpt": "",
            "point_name": "",
            "priority": priority,
            "hop_count": hop_count,
            "extra": {"seq": str(tpci.seq_no)} if tpci.seq_no is not None else {},
            "raw_hex": raw.hex(),
        }

    # APCI : 2 bits bas de byte6 + 8 bits de byte7 = 10 bits total
    apci_code_10bit = ((byte6 & 0x03) << 8) | byte7
    apci = lookup_apci(apci_code_10bit)

    # param_bits : bits bas de byte7 qui portent un paramètre (count/type/channel)
    # pour certains APCI. On calcule le décalage à partir de l'APCI matché.
    # Ex: Memory_Read (0x200) matché sur 0x202 → param_bits = 0x02 & 0x0F = 2.
    param_bits = 0
    if apci.code in (0x200, 0x240, 0x280):
        # Memory_* : 4 bits bas = count
        param_bits = byte7 & 0x0F
    elif apci.code in (0x180, 0x1C0, 0x300, 0x340, 0x380):
        # ADC, DeviceDescriptor, Restart : 6 bits bas = type/channel
        param_bits = byte7 & 0x3F

    # Payload : dépend de l'encodage (short = data dans 6 bits bas de byte7, long = octets suivants)
    if apci.is_short:
        # GroupValue courts : la data est soit dans les 6 bits bas de byte7 (npdu_len == 1),
        # soit dans les octets suivants (npdu_len > 1).
        if npdu_len == 1:
            short_data = byte7 & 0x3F
            payload = bytes([short_data])
            is_short_data = True
        else:
            payload = raw[header_len + 9:]
            is_short_data = False
    else:
        # APCI 10-bit : payload commence à l'octet 11
        payload = raw[header_len + 9:]
        is_short_data = False

    # Décodage sémantique du payload
    if apci.category == ApciCategory.RUNTIME and address_type == "group":
        # GroupValue_* : essayer de décoder avec le DPT de l'adresse de groupe
        decoded = _decode_group_value(destination, payload, is_short_data,
                                      dpt_registry, ga_registry)
    else:
        # Autres services : résumé N2 structuré
        detail, extra = describe_apci(apci, payload, param_bits)
        decoded = {
            "value": extra.get("data", "") or extra.get("payload_hex", ""),
            "value_num": None,
            "unit": "",
            "extra": extra,
            "operation_detail": detail,
            "dpt": "",
            "point_name": "",
        }

    return {
        "source": src,
        "destination": destination,
        "address_type": address_type,
        "apci": apci.short_name,
        "apci_category": apci.category.value,
        "tpci": tpci.kind.value,
        "operation_detail": decoded.get("operation_detail", apci.short_name),
        "value": decoded.get("value", ""),
        "value_num": decoded.get("value_num"),
        "unit": decoded.get("unit", ""),
        "dpt": decoded.get("dpt", ""),
        "point_name": decoded.get("point_name", ""),
        "priority": priority,
        "hop_count": hop_count,
        "extra": decoded.get("extra", {}),
        "raw_hex": raw.hex(),
    }


def _decode_group_value(destination: str, payload: bytes, is_short_data: bool,
                        dpt_registry, ga_registry) -> dict:
    """
    Décode un GroupValue_Read/Response/Write :
    - Résout le DPT via ga_registry[destination]
    - Décode via dpt_registry[dpt_id]
    - Round 8 : override unit via ga_registry[destination]["unit"] (prioritaire)
    """
    dpt_id = ""
    point_name = ""
    ga_unit = ""  # Round 8 : unité surchargée dans la sémantique GA

    if ga_registry:
        ga_info = ga_registry.get(destination)
        if ga_info:
            dpt_id = str(ga_info.get("dpt") or "")
            point_name = str(ga_info.get("name") or "")
            ga_unit = str(ga_info.get("unit") or "")

    decoded = {
        "value": payload.hex(),
        "value_num": None,
        "unit": ga_unit,  # Round 8 : défaut à l'override GA si présent
        "extra": {},
        "dpt": dpt_id,
        "point_name": point_name,
        "operation_detail": "GroupValueWrite",
    }

    if dpt_id and dpt_registry:
        entry = dpt_registry.get(dpt_id)
        if entry:
            try:
                d = entry.decode(payload)
                decoded["value"] = d.get("value", "")
                decoded["value_num"] = d.get("value_num")
                # Round 8 : priorité GA unit > DPT decoder unit > DPT registry unit
                decoded["unit"] = ga_unit or d.get("unit") or entry.unit
                decoded["extra"] = d.get("extra") or {}
                decoded["operation_detail"] = (
                    f"GroupValue {point_name or destination}"
                    + (f" = {decoded['value']}{decoded['unit']}" if decoded["value"] else "")
                )
            except Exception as exc:
                log.warning("DPT decode failed for %s (dpt=%s): %s", destination, dpt_id, exc)
                decoded["extra"] = {"decode_error": str(exc)[:100]}

    return decoded
