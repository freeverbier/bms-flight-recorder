"""
Table APCI complète (Application Layer Protocol Control Information).

Référence : KNX Handbook Vol 3/3/7 Application Layer.

Deux encodages coexistent :
  - APCI "court" (4 bits) : GroupValue_Read/Response/Write. Les 4 bits de poids
    fort de l'octet 6 codent l'APCI ; les 6 bits de poids faible peuvent porter
    de la data compressée (short frame) ou du padding.
  - APCI "long" (10 bits) : tous les autres services. Les 10 bits couvrent
    l'octet 6 (2 bits) + l'octet 7 (8 bits). La data suit dans les octets 8+.

Le champ TPCI (Transport Layer PCI) précède l'APCI et distingue :
  - T_Data_Group        (multicast, adresse de groupe)
  - T_Data_Tag_Group    (multicast taggué)
  - T_Data_Broadcast    (broadcast)
  - T_Data_Individual   (unicast connectionless)
  - T_Data_Connected    (unicast connecté, avec numéro de séquence)
  - T_Connect / T_Disconnect / T_ACK / T_NACK (contrôle session unicast)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApciCategory(str, Enum):
    RUNTIME = "runtime"              # GroupValue_* : trafic métier
    PROGRAMMING = "programming"      # IndividualAddress_* : adressage physique
    DEVICE = "device"                # DeviceDescriptor, Restart, ADC
    MEMORY = "memory"                # Memory_*, UserMemory_*
    AUTHORIZATION = "authorization"  # Authorize, Key
    PROPERTY = "property"            # PropertyValue_*, FunctionProperty*
    DIAGNOSTIC = "diagnostic"        # NetworkParameter, SystemNetworkParameter
    COUPLER = "coupler"              # DomainAddress (KNX RF/PL)
    OTHER = "other"                  # Services non classés
    UNKNOWN = "unknown"              # APCI inconnu


@dataclass(frozen=True)
class ApciDef:
    """Définition d'un APCI dans la table de référence."""
    code: int                     # code APCI 10-bit
    name: str                     # nom canonique (ex: "A_GroupValue_Write")
    short_name: str               # nom court pour l'UI (ex: "GroupValueWrite")
    category: ApciCategory
    is_short: bool                # True = 4-bit APCI (data possible dans octet 6)
    description: str = ""


# Table des services APCI. Les codes 10-bit ; is_short=True quand l'APCI ne
# consomme réellement que les 4 bits de poids fort et laisse les 6 bits bas
# pour de la data.
_APCI_TABLE: list[ApciDef] = [
    # --- Runtime : GroupValue (courts, 4 bits) ---
    ApciDef(0x000, "A_GroupValue_Read", "GroupValueRead", ApciCategory.RUNTIME, True),
    ApciDef(0x040, "A_GroupValue_Response", "GroupValueResponse", ApciCategory.RUNTIME, True),
    ApciDef(0x080, "A_GroupValue_Write", "GroupValueWrite", ApciCategory.RUNTIME, True),

    # --- Programming : adressage physique ---
    ApciDef(0x0C0, "A_IndividualAddress_Write", "IndividualAddressWrite",
            ApciCategory.PROGRAMMING, False),
    ApciDef(0x100, "A_IndividualAddress_Read", "IndividualAddressRead",
            ApciCategory.PROGRAMMING, False),
    ApciDef(0x140, "A_IndividualAddress_Response", "IndividualAddressResponse",
            ApciCategory.PROGRAMMING, False),
    ApciDef(0x3DC, "A_IndividualAddressSerialNumber_Read", "IndAddrSerialRead",
            ApciCategory.PROGRAMMING, False),
    ApciDef(0x3DD, "A_IndividualAddressSerialNumber_Response", "IndAddrSerialResponse",
            ApciCategory.PROGRAMMING, False),
    ApciDef(0x3DE, "A_IndividualAddressSerialNumber_Write", "IndAddrSerialWrite",
            ApciCategory.PROGRAMMING, False),

    # --- Device : identification & contrôle ---
    ApciDef(0x180, "A_ADC_Read", "ADCRead", ApciCategory.DEVICE, False),
    ApciDef(0x1C0, "A_ADC_Response", "ADCResponse", ApciCategory.DEVICE, False),
    ApciDef(0x300, "A_DeviceDescriptor_Read", "DeviceDescriptorRead",
            ApciCategory.DEVICE, False),
    ApciDef(0x340, "A_DeviceDescriptor_Response", "DeviceDescriptorResponse",
            ApciCategory.DEVICE, False),
    ApciDef(0x380, "A_Restart", "Restart", ApciCategory.DEVICE, False),
    ApciDef(0x2C4, "A_UserManufacturerInfo_Read", "MfrInfoRead",
            ApciCategory.DEVICE, False),
    ApciDef(0x2C5, "A_UserManufacturerInfo_Response", "MfrInfoResponse",
            ApciCategory.DEVICE, False),

    # --- Memory : téléchargement config ETS ---
    ApciDef(0x200, "A_Memory_Read", "MemoryRead", ApciCategory.MEMORY, False),
    ApciDef(0x240, "A_Memory_Response", "MemoryResponse", ApciCategory.MEMORY, False),
    ApciDef(0x280, "A_Memory_Write", "MemoryWrite", ApciCategory.MEMORY, False),
    ApciDef(0x2C0, "A_UserMemory_Read", "UserMemoryRead", ApciCategory.MEMORY, False),
    ApciDef(0x2C1, "A_UserMemory_Response", "UserMemoryResponse",
            ApciCategory.MEMORY, False),
    ApciDef(0x2C2, "A_UserMemory_Write", "UserMemoryWrite", ApciCategory.MEMORY, False),
    ApciDef(0x2C8, "A_MemoryBit_Write", "MemoryBitWrite", ApciCategory.MEMORY, False),

    # --- Authorization ---
    ApciDef(0x3D1, "A_Authorize_Request", "AuthorizeRequest",
            ApciCategory.AUTHORIZATION, False),
    ApciDef(0x3D2, "A_Authorize_Response", "AuthorizeResponse",
            ApciCategory.AUTHORIZATION, False),
    ApciDef(0x3D3, "A_Key_Write", "KeyWrite", ApciCategory.AUTHORIZATION, False),
    ApciDef(0x3D4, "A_Key_Response", "KeyResponse", ApciCategory.AUTHORIZATION, False),

    # --- Property Access : interface objects modernes ---
    ApciDef(0x3D5, "A_PropertyValue_Read", "PropertyValueRead",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3D6, "A_PropertyValue_Response", "PropertyValueResponse",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3D7, "A_PropertyValue_Write", "PropertyValueWrite",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3D8, "A_PropertyDescription_Read", "PropertyDescRead",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3D9, "A_PropertyDescription_Response", "PropertyDescResponse",
            ApciCategory.PROPERTY, False),
    ApciDef(0x2E0, "A_FunctionPropertyCommand", "FuncPropCommand",
            ApciCategory.PROPERTY, False),
    ApciDef(0x2E1, "A_FunctionPropertyState_Read", "FuncPropStateRead",
            ApciCategory.PROPERTY, False),
    ApciDef(0x2E2, "A_FunctionPropertyState_Response", "FuncPropStateResponse",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3E8, "A_PropertyValueExt_Read", "PropertyValueExtRead",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3E9, "A_PropertyValueExt_Response", "PropertyValueExtResponse",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3EA, "A_PropertyValueExtWriteCon", "PropertyValueExtWriteCon",
            ApciCategory.PROPERTY, False),
    ApciDef(0x3EB, "A_PropertyValueExtWriteConResponse", "PropertyValueExtWriteConResp",
            ApciCategory.PROPERTY, False),

    # --- Diagnostic réseau ---
    ApciDef(0x1C8, "A_SystemNetworkParameter_Read", "SysNetParamRead",
            ApciCategory.DIAGNOSTIC, False),
    ApciDef(0x1C9, "A_SystemNetworkParameter_Response", "SysNetParamResponse",
            ApciCategory.DIAGNOSTIC, False),
    ApciDef(0x1CA, "A_SystemNetworkParameter_Write", "SysNetParamWrite",
            ApciCategory.DIAGNOSTIC, False),
    ApciDef(0x3DA, "A_NetworkParameter_Read", "NetParamRead",
            ApciCategory.DIAGNOSTIC, False),
    ApciDef(0x3DB, "A_NetworkParameter_Response", "NetParamResponse",
            ApciCategory.DIAGNOSTIC, False),
    ApciDef(0x3E4, "A_NetworkParameter_Write", "NetParamWrite",
            ApciCategory.DIAGNOSTIC, False),

    # --- Coupler / KNX RF, PL ---
    ApciDef(0x3E0, "A_DomainAddress_Read", "DomainAddrRead",
            ApciCategory.COUPLER, False),
    ApciDef(0x3E1, "A_DomainAddress_Response", "DomainAddrResponse",
            ApciCategory.COUPLER, False),
    ApciDef(0x3E5, "A_DomainAddress_Write", "DomainAddrWrite",
            ApciCategory.COUPLER, False),
    ApciDef(0x3EC, "A_DomainAddressSerialNumber_Read", "DomainAddrSerialRead",
            ApciCategory.COUPLER, False),
    ApciDef(0x3ED, "A_DomainAddressSerialNumber_Response", "DomainAddrSerialResponse",
            ApciCategory.COUPLER, False),
    ApciDef(0x3EE, "A_DomainAddressSerialNumber_Write", "DomainAddrSerialWrite",
            ApciCategory.COUPLER, False),
]

# Index par code pour lookup O(1)
_APCI_BY_CODE: dict[int, ApciDef] = {a.code: a for a in _APCI_TABLE}

# APCI qui portent un paramètre dans les bits bas :
# - 4 bits bas : Memory_* (0x200, 0x240, 0x280)  →  masque 0x3F0
# - 6 bits bas : ADC_*, DeviceDescriptor_*, Restart (0x180, 0x1C0, 0x300, 0x340, 0x380)  →  masque 0x3C0
_APCI_MASK_4BIT = {0x200, 0x240, 0x280}
_APCI_MASK_6BIT = {0x180, 0x1C0, 0x300, 0x340, 0x380}


def lookup_apci(apci_code_10bit: int) -> ApciDef:
    """
    Retourne la définition de l'APCI, ou un ApciDef 'unknown' si absent.
    Gère les APCI courts (4 bits) et les APCI qui portent un paramètre
    (count/channel/type) dans les 4 ou 6 bits bas.
    """
    # Essai direct : APCI 10-bit exact
    if apci_code_10bit in _APCI_BY_CODE:
        return _APCI_BY_CODE[apci_code_10bit]

    # APCI 4-bit (GroupValue_*) : on prend les 4 bits hauts
    short = apci_code_10bit & 0x3C0
    if short in _APCI_BY_CODE and _APCI_BY_CODE[short].is_short:
        return _APCI_BY_CODE[short]

    # APCI avec paramètre 4 bits bas : Memory_*
    masked4 = apci_code_10bit & 0x3F0
    if masked4 in _APCI_MASK_4BIT and masked4 in _APCI_BY_CODE:
        return _APCI_BY_CODE[masked4]

    # APCI avec paramètre 6 bits bas : ADC, DeviceDescriptor, Restart
    masked6 = apci_code_10bit & 0x3C0
    if masked6 in _APCI_MASK_6BIT and masked6 in _APCI_BY_CODE:
        return _APCI_BY_CODE[masked6]

    return ApciDef(apci_code_10bit, f"A_Unknown_0x{apci_code_10bit:03X}",
                   f"Unknown_0x{apci_code_10bit:03X}", ApciCategory.UNKNOWN, False)


# ---------------------------------------------------------------------------
# TPCI
# ---------------------------------------------------------------------------

class TpciKind(str, Enum):
    DATA_GROUP = "T_Data_Group"
    DATA_TAG_GROUP = "T_Data_Tag_Group"
    DATA_BROADCAST = "T_Data_Broadcast"
    DATA_INDIVIDUAL = "T_Data_Individual"
    DATA_CONNECTED = "T_Data_Connected"
    CONNECT = "T_Connect"
    DISCONNECT = "T_Disconnect"
    ACK = "T_ACK"
    NACK = "T_NACK"
    UNKNOWN = "T_Unknown"


@dataclass(frozen=True)
class TpciInfo:
    kind: TpciKind
    seq_no: int | None = None      # numéro de séquence pour DATA_CONNECTED / ACK / NACK


def decode_tpci(byte6_high: int, address_type: str) -> TpciInfo:
    """
    Décode le TPCI à partir des 2 bits de poids fort de l'octet 6 du cEMI
    et de l'address type (group/individual/broadcast).

    byte6_high : la moitié haute (2 bits) - premier octet de la data TPDU.
    address_type : "group" | "individual" | "broadcast"
    """
    # TPCI codage (byte6 & 0xFC) :
    #   00xxxxxx = data_frame (T_Data_*)
    #   01xxxxxx = data_connected_frame (T_Data_Connected)
    #   10000000 = T_Connect (0x80)
    #   10000001 = T_Disconnect (0x81)
    #   11xxxx10 = T_ACK
    #   11xxxx11 = T_NACK
    tpci_top = byte6_high & 0xC0

    if tpci_top == 0x00:
        # Data frame — le kind dépend du type d'adresse destination
        if address_type == "group":
            return TpciInfo(TpciKind.DATA_GROUP)
        elif address_type == "broadcast":
            return TpciInfo(TpciKind.DATA_BROADCAST)
        else:
            return TpciInfo(TpciKind.DATA_INDIVIDUAL)

    if tpci_top == 0x40:
        # Data connected — extraire le seq_no (bits 5-2)
        seq = (byte6_high >> 2) & 0x0F
        return TpciInfo(TpciKind.DATA_CONNECTED, seq_no=seq)

    if tpci_top == 0x80:
        # Control frame
        control = byte6_high & 0x03
        if control == 0x00:
            return TpciInfo(TpciKind.CONNECT)
        if control == 0x01:
            return TpciInfo(TpciKind.DISCONNECT)

    if tpci_top == 0xC0:
        # ACK/NACK
        seq = (byte6_high >> 2) & 0x0F
        control = byte6_high & 0x03
        if control == 0x02:
            return TpciInfo(TpciKind.ACK, seq_no=seq)
        if control == 0x03:
            return TpciInfo(TpciKind.NACK, seq_no=seq)

    return TpciInfo(TpciKind.UNKNOWN)


def has_apci_payload(tpci: TpciInfo) -> bool:
    """
    Retourne True si le TPCI porte de la data applicative (APCI + payload),
    False pour les frames de contrôle transport pur (Connect, Disconnect, ACK, NACK).
    """
    return tpci.kind in {
        TpciKind.DATA_GROUP,
        TpciKind.DATA_TAG_GROUP,
        TpciKind.DATA_BROADCAST,
        TpciKind.DATA_INDIVIDUAL,
        TpciKind.DATA_CONNECTED,
    }
