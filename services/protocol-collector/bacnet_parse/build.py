"""
Builder minimal BACnet/IP pour les requêtes ReadProperty et ReadPropertyMultiple.
Complète le décodeur bacnet_parse.frame pour permettre au collector d'émettre
des requêtes ciblées lors du discovery des objets d'un device.

Références : ANSI/ASHRAE 135, clauses 15-20.
"""

from __future__ import annotations


def _encode_object_id(obj_type: int, obj_instance: int) -> bytes:
    """Encode un ObjectIdentifier BACnet (4 bytes)."""
    v = ((obj_type & 0x3FF) << 22) | (obj_instance & 0x3FFFFF)
    return v.to_bytes(4, "big")


def _encode_ctx_uint(tag_num: int, value: int) -> bytes:
    """Encode un entier non signé dans un context tag."""
    if value < 256:
        return bytes([(tag_num << 4) | 0x08 | 1, value])
    if value < 65536:
        return bytes([(tag_num << 4) | 0x08 | 2]) + value.to_bytes(2, "big")
    if value < 16777216:
        return bytes([(tag_num << 4) | 0x08 | 3]) + value.to_bytes(3, "big")
    return bytes([(tag_num << 4) | 0x08 | 4]) + value.to_bytes(4, "big")


def _encode_app_uint(value: int) -> bytes:
    """Encode un entier non signé en application tag 2 (UnsignedInt)."""
    if value < 256:
        return bytes([0x21, value])
    if value < 65536:
        return bytes([0x22]) + value.to_bytes(2, "big")
    if value < 16777216:
        return bytes([0x23]) + value.to_bytes(3, "big")
    return bytes([0x24]) + value.to_bytes(4, "big")


def _bvlc_wrap(function: int, npdu_apdu: bytes) -> bytes:
    """Encapsule NPDU+APDU dans un BVLC. function=0x0a unicast, 0x0b broadcast."""
    length = 4 + len(npdu_apdu)
    return bytes([0x81, function]) + length.to_bytes(2, "big") + npdu_apdu


def _npdu(expect_reply: bool = True, priority: int = 0) -> bytes:
    """
    NPDU minimal : version 1, control avec bit expect-reply.
    Pour un broadcast global, il faudrait ajouter DNET=65535 + hop_count,
    mais pour un unicast simple ces bits ne sont pas nécessaires.
    """
    control = (0x04 if expect_reply else 0x00) | (priority & 0x03)
    return bytes([0x01, control])


def build_readproperty(
    invoke_id: int,
    obj_type: int,
    obj_instance: int,
    property_id: int,
    array_index: int | None = None,
    max_apdu_size: int = 5,  # 5 = 1476 bytes
    max_segments: int = 0,   # 0 = no segmentation
) -> bytes:
    """
    Construit un paquet ReadProperty complet (BVLC + NPDU + APDU) pour envoi UDP.

    Args:
        invoke_id: 0-255, matché par la réponse
        obj_type: 8=device, 0=analog-input, etc.
        obj_instance: numéro d'instance
        property_id: 76=object-list, 77=object-name, 116=units, 85=present-value, 28=description
        array_index: pour lire un élément d'une liste (ex. object-list[N])

    Retourne les bytes prêts à envoyer.
    """
    # APDU header : Confirmed-Request, no seg flags
    apdu = bytes([
        0x00,  # PDU type 0 (Confirmed-Request), no flags
        (max_segments << 4) | (max_apdu_size & 0x0F),
        invoke_id & 0xFF,
        13,   # service choice = readProperty (ANSI/ASHRAE 135)
    ])
    # Context tag 0 : object-identifier (LVT=4)
    apdu += bytes([0x0c]) + _encode_object_id(obj_type, obj_instance)
    # Context tag 1 : property-identifier
    apdu += _encode_ctx_uint(1, property_id)
    # Context tag 2 : property-array-index (optionnel)
    if array_index is not None:
        apdu += _encode_ctx_uint(2, array_index)

    return _bvlc_wrap(0x0a, _npdu(expect_reply=True) + apdu)


def build_readpropertymultiple(
    invoke_id: int,
    specs: list[dict],
    max_apdu_size: int = 5,
    max_segments: int = 0,
) -> bytes:
    """
    Construit un ReadPropertyMultiple pour lire plusieurs propriétés
    de un ou plusieurs objets.

    Args:
        specs: [{"obj_type": 0, "obj_instance": 1, "property_ids": [77, 85, 116]}, ...]
    """
    apdu = bytes([
        0x00,
        (max_segments << 4) | (max_apdu_size & 0x0F),
        invoke_id & 0xFF,
        14,   # service choice = readPropertyMultiple (Delta Controls quirk: old code 14 vs standard 15)
    ])
    for spec in specs:
        obj_type = spec["obj_type"]
        obj_instance = spec["obj_instance"]
        # Context tag 0 : object-identifier
        apdu += bytes([0x0c]) + _encode_object_id(obj_type, obj_instance)
        # Context tag 1 opening : list of Property Reference
        apdu += bytes([0x1e])
        for pid in spec["property_ids"]:
            # Context tag 0 inside : property-identifier
            apdu += _encode_ctx_uint(0, pid)
        # Context tag 1 closing
        apdu += bytes([0x1f])

    return _bvlc_wrap(0x0a, _npdu(expect_reply=True) + apdu)
