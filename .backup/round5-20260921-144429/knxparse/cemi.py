"""
Parser cEMI (Common External Message Interface) — KNX standard 3/6/3.

Une trame cEMI ressemble à ceci :
    +--------+--------+--------+--------+
    | MC     | AddIL  | AddInfo …       |  (message code + additional info length + additional info)
    +--------+--------+--------+--------+
    | CTRL1  | CTRL2  | SA (2)          |  (control fields + source individual address)
    +--------+--------+--------+--------+
    | DA (2) | NPDUL  | TPCI  | APCI/data …
    +--------+--------+--------+--------+

Message codes utilisés couramment :
    0x11  L_Data.req         (émission depuis un client)
    0x29  L_Data.ind         (réception, ce qu'on voit en tunnel/routing)
    0x2E  L_Data.con         (confirmation d'émission)
    0x2B  L_Busmon.ind       (bus monitor)

Cette implémentation cible les .ind pour le monitoring passif, avec support
des .req et .con pour affichage complet en debug.

Références :
- KNX Standard 03/06/03 EMI/IMI section 4.1.5
- Extended APCI: 03/03/07 sections 3.3.1 / 3.4
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class MessageCode(IntEnum):
    L_DATA_REQ = 0x11
    L_DATA_CON = 0x2E
    L_DATA_IND = 0x29
    L_BUSMON_IND = 0x2B
    L_RAW_IND = 0x2D
    L_RAW_REQ = 0x10
    L_RAW_CON = 0x2F
    L_POLL_DATA_REQ = 0x13
    L_POLL_DATA_CON = 0x25


# APCI 4 bits standard (bits 9..6 combinés) puis APCI étendu 10 bits pour certains cas.
APCI_STANDARD = {
    0x000: "GroupValueRead",
    0x040: "GroupValueResponse",
    0x080: "GroupValueWrite",
    0x0C0: "IndividualAddressWrite",
    0x100: "IndividualAddressRead",
    0x140: "IndividualAddressResponse",
    0x180: "ADCRead",
    0x1C0: "ADCResponse",
    0x200: "MemoryRead",
    0x240: "MemoryResponse",
    0x280: "MemoryWrite",
    0x2C0: "UserMessage",
    0x300: "MaskVersionRead",
    0x340: "MaskVersionResponse",
    0x380: "Restart",
    0x3C0: "Escape",
}

# APCI étendus 10 bits (bits 9..0), à décoder si les 4 bits standard = 0x3C0 (Escape).
APCI_EXTENDED = {
    0x3D0: "PropertyValueRead",
    0x3D1: "PropertyValueResponse",
    0x3D2: "PropertyValueWrite",
    0x3D3: "PropertyDescriptionRead",
    0x3D4: "PropertyDescriptionResponse",
    0x3D5: "NetworkParameterRead",
    0x3D6: "NetworkParameterResponse",
    0x3D7: "IndividualAddressSerialNumberRead",
    0x3D8: "IndividualAddressSerialNumberResponse",
    0x3D9: "IndividualAddressSerialNumberWrite",
    0x3DA: "DomainAddressWrite",
    0x3DB: "DomainAddressRead",
    0x3DC: "DomainAddressResponse",
    0x3DD: "DomainAddressSelectiveRead",
    0x3DE: "NetworkParameterWrite",
    0x3E0: "LinkRead",
    0x3E1: "LinkResponse",
    0x3E2: "LinkWrite",
    0x3E3: "GroupPropValueRead",
    0x3E4: "GroupPropValueResponse",
    0x3E5: "GroupPropValueWrite",
    0x3E6: "GroupPropValueInfoReport",
    0x3E7: "DomainAddressSerialNumberRead",
    0x3E8: "DomainAddressSerialNumberResponse",
    0x3E9: "DomainAddressSerialNumberWrite",
    0x3EA: "FileStreamInfoReport",
}


@dataclass
class CemiFrame:
    """Trame cEMI décodée. `apdu` contient les octets utiles (avec l'APCI et les data)."""

    message_code: int
    source: str  # adresse individuelle "A.L.D" (area.line.device)
    destination: str  # adresse individuelle ou de groupe
    is_group: bool
    hop_count: int
    priority: str
    apci: int  # APCI décodé (standard 4 bits ou étendu 10 bits)
    apci_name: str
    apdu: bytes  # APDU (APCI + data)
    data: bytes  # data brute (après APCI)
    tpci: int
    sequence: Optional[int] = None
    raw: bytes = b""

    @property
    def is_broadcast(self) -> bool:
        return self.destination == "0/0/0"


def individual_address(value: int) -> str:
    """Adresse individuelle : Area(4bits).Line(4bits).Device(8bits)."""
    return f"{(value >> 12) & 0x0F}.{(value >> 8) & 0x0F}.{value & 0xFF}"


def group_address_3_level(value: int) -> str:
    """Adresse de groupe 3 niveaux : Main(5bits)/Middle(3bits)/Sub(8bits)."""
    return f"{(value >> 11) & 0x1F}/{(value >> 8) & 0x07}/{value & 0xFF}"


def group_address_2_level(value: int) -> str:
    """Adresse de groupe 2 niveaux : Main(5bits)/Sub(11bits)."""
    return f"{(value >> 11) & 0x1F}/{value & 0x7FF}"


def decode_priority(ctrl1: int) -> str:
    return {0: "system", 1: "normal", 2: "urgent", 3: "low"}[(ctrl1 >> 2) & 0x03]


def parse_cemi(data: bytes, group_address_style: str = "3-level") -> Optional[CemiFrame]:
    """
    Décode une trame cEMI.

    :param data: octets bruts commençant par le message code
    :param group_address_style: "3-level" (défaut) ou "2-level"
    :return: CemiFrame ou None si trame invalide

    Structure minimale attendue pour L_Data : 10 octets (MC + AddIL=0 + CTRL1 + CTRL2 + SA + DA + NPDUL + TPCI).
    """
    if len(data) < 10:
        return None

    message_code = data[0]
    if message_code not in (
        MessageCode.L_DATA_REQ,
        MessageCode.L_DATA_CON,
        MessageCode.L_DATA_IND,
    ):
        # On ne décode que L_Data pour l'instant. Le busmon et le raw sont ignorés.
        return None

    add_il = data[1]
    idx = 2 + add_il
    if len(data) < idx + 8:
        return None

    ctrl1 = data[idx]
    ctrl2 = data[idx + 1]
    source = int.from_bytes(data[idx + 2 : idx + 4], "big")
    destination = int.from_bytes(data[idx + 4 : idx + 6], "big")
    npdu_length = data[idx + 6]
    tpci_apci = data[idx + 7]

    if len(data) < idx + 8 + npdu_length:
        return None

    # TPCI = bits 7..2 de l'octet 7, APCI = bits 1..0 de l'octet 7 + bits 7..6 de l'octet 8
    tpci = tpci_apci >> 2
    is_group = bool(ctrl2 & 0x80)
    hop_count = (ctrl2 >> 4) & 0x07

    # APDU = octets 7 (partie basse pour APCI) + tout ce qui suit jusqu'à NPDUL inclus
    apdu = data[idx + 7 : idx + 8 + npdu_length]

    apci_standard = 0
    apci_name = "TDataConnected"  # défaut pour trames sans APCI (Ack, etc.)
    sequence = None
    payload = b""

    # Bit 7 du TPCI = 1 → transport numbered (contient un TSAP number)
    if tpci & 0x20:
        sequence = (tpci >> 2) & 0x0F

    if len(apdu) >= 2:
        # 4 bits standard APCI = bits 1..0 de apdu[0] + bits 7..6 de apdu[1]
        apci_standard = ((apdu[0] & 0x03) << 8) | (apdu[1] & 0xC0)
        apci_name = APCI_STANDARD.get(apci_standard, f"APCI 0x{apci_standard:03X}")

        # Cas Escape (0x3C0) → APCI étendu 10 bits = bits 1..0 de apdu[0] + tout apdu[1]
        if apci_standard == 0x3C0:
            apci_extended = ((apdu[0] & 0x03) << 8) | apdu[1]
            apci_name = APCI_EXTENDED.get(
                apci_extended, f"Escape 0x{apci_extended:03X}"
            )
            apci_standard = apci_extended

        # Pour GroupValueRead/Response/Write, les 6 bits bas de apdu[1] sont la data si courte,
        # sinon la data commence à apdu[2]. Le NPDUL = 1 → data 6 bits packée dans apdu[1].
        if apci_standard in (0x000, 0x040, 0x080) and npdu_length == 1:
            # Data 6 bits packée
            payload = bytes([apdu[1] & 0x3F])
        elif len(apdu) > 2:
            payload = apdu[2:]

    destination_str = (
        group_address_3_level(destination)
        if is_group and group_address_style == "3-level"
        else group_address_2_level(destination)
        if is_group
        else individual_address(destination)
    )

    return CemiFrame(
        message_code=message_code,
        source=individual_address(source),
        destination=destination_str,
        is_group=is_group,
        hop_count=hop_count,
        priority=decode_priority(ctrl1),
        apci=apci_standard,
        apci_name=apci_name,
        apdu=apdu,
        data=payload,
        tpci=tpci,
        sequence=sequence,
        raw=bytes(data),
    )
