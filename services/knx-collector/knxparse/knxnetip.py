"""
Client KNXnet/IP — implémentation minimale des services utilisés en monitoring :

- Search Request/Response (découverte multicast des interfaces)
- Connect Request/Response (établissement d'un tunnel link-layer)
- Tunneling Request/Ack + Disconnect
- Routing Indication (écoute multicast)
- Connection State Request/Response (heartbeat)

Structure d'une trame KNXnet/IP :
    +--------+--------+--------+--------+
    | 06     | 10     | service (2)     |  (header)
    +--------+--------+--------+--------+
    | total length (2)| body …          |
    +-----------------+----------------+

Le body suit le service. cEMI encapsulé pour les Tunneling/Routing Indication.

Références :
- KNX Standard 03/08/02 (Core), 03/08/03 (Device Management),
  03/08/04 (Tunnelling), 03/08/05 (Routing)
"""

from __future__ import annotations

import asyncio
import socket
import struct
from dataclasses import dataclass
from typing import Optional

HEADER = 0x0610
HEADER_SIZE = 6

# Service type identifiers
SEARCH_REQUEST = 0x0201
SEARCH_RESPONSE = 0x0202
DESCRIPTION_REQUEST = 0x0203
DESCRIPTION_RESPONSE = 0x0204
CONNECT_REQUEST = 0x0205
CONNECT_RESPONSE = 0x0206
CONNECTIONSTATE_REQUEST = 0x0207
CONNECTIONSTATE_RESPONSE = 0x0208
DISCONNECT_REQUEST = 0x0209
DISCONNECT_RESPONSE = 0x020A
TUNNELING_REQUEST = 0x0420
TUNNELING_ACK = 0x0421
ROUTING_INDICATION = 0x0530
ROUTING_LOST_MESSAGE = 0x0531

DEFAULT_PORT = 3671
DEFAULT_MULTICAST = "224.0.23.12"


@dataclass
class KnxHeader:
    service_type: int
    total_length: int


def parse_header(data: bytes) -> Optional[KnxHeader]:
    """Analyse l'entête d'une trame KNXnet/IP."""
    if len(data) < HEADER_SIZE:
        return None
    if struct.unpack(">H", data[:2])[0] != HEADER:
        return None
    service_type, total_length = struct.unpack(">HH", data[2:6])
    if total_length != len(data):
        # certains équipements sur-remplissent le buffer ; on tolère plus long, pas plus court
        if total_length > len(data):
            return None
    return KnxHeader(service_type=service_type, total_length=total_length)


def build_hpai(local_ip: str, local_port: int) -> bytes:
    """Host Protocol Address Information — décrit un endpoint UDP/IPv4."""
    return struct.pack(">BB", 8, 0x01) + socket.inet_aton(local_ip) + struct.pack(">H", local_port)


def build_search_request(hpai: bytes) -> bytes:
    body = hpai
    total = HEADER_SIZE + len(body)
    return struct.pack(">HHH", HEADER, SEARCH_REQUEST, total) + body


def build_connect_request(hpai_ctrl: bytes, hpai_data: bytes) -> bytes:
    # CRI : Connection Request Information — 4 octets pour un tunnel link-layer
    # Structure : length(1) | connection type(1) | KNX layer(1) | reserved(1)
    cri = struct.pack(">BBBB", 4, 0x04, 0x02, 0x00)
    body = hpai_ctrl + hpai_data + cri
    total = HEADER_SIZE + len(body)
    return struct.pack(">HHH", HEADER, CONNECT_REQUEST, total) + body


def build_connectionstate_request(channel: int, hpai_ctrl: bytes) -> bytes:
    body = struct.pack(">BB", channel, 0x00) + hpai_ctrl
    total = HEADER_SIZE + len(body)
    return struct.pack(">HHH", HEADER, CONNECTIONSTATE_REQUEST, total) + body


def build_disconnect_request(channel: int, hpai_ctrl: bytes) -> bytes:
    body = struct.pack(">BB", channel, 0x00) + hpai_ctrl
    total = HEADER_SIZE + len(body)
    return struct.pack(">HHH", HEADER, DISCONNECT_REQUEST, total) + body


def build_tunneling_ack(channel: int, sequence: int) -> bytes:
    # Body : length(1) | channel(1) | seq(1) | status(1)
    body = struct.pack(">BBBB", 4, channel, sequence, 0x00)
    total = HEADER_SIZE + len(body)
    return struct.pack(">HHH", HEADER, TUNNELING_ACK, total) + body


@dataclass
class SearchResponse:
    address: str
    port: int
    individual_address: str
    name: str
    mac: str
    knx_medium: str

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "port": self.port,
            "individual_address": self.individual_address,
            "name": self.name,
            "mac": self.mac,
            "knx_medium": self.knx_medium,
        }


_KNX_MEDIUMS = {
    0x01: "TP0",
    0x02: "TP1",
    0x04: "PL110",
    0x08: "PL132",
    0x10: "RF",
    0x20: "IP",
}


def parse_search_response(data: bytes, peer: tuple[str, int]) -> Optional[SearchResponse]:
    """
    Analyse une SEARCH_RESPONSE. Structure du body :
        HPAI(8) + DIB_DeviceInfo(54) + DIB_SuppSvcFamilies(N)
    Le DIB DeviceInfo contient : length(1) | type(1)=0x01 | medium(1) | status(1)
                              | knx individual(2) | project installation(2)
                              | serial(6) | mcast(4) | mac(6) | friendly name(30)
    """
    header = parse_header(data)
    if not header or header.service_type != SEARCH_RESPONSE:
        return None
    body = data[HEADER_SIZE:]
    if len(body) < 8 + 54:
        return None

    # HPAI (8 octets) — on ignore et on prend l'adresse du peer
    dib = body[8:8 + 54]
    if dib[1] != 0x01:
        return None

    medium = _KNX_MEDIUMS.get(dib[2], f"Medium 0x{dib[2]:02X}")
    individual = int.from_bytes(dib[4:6], "big")
    mac = ":".join(f"{b:02X}" for b in dib[18:24])
    name = dib[24:54].split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()

    return SearchResponse(
        address=peer[0],
        port=peer[1],
        individual_address=f"{(individual >> 12) & 0x0F}.{(individual >> 8) & 0x0F}.{individual & 0xFF}",
        name=name or "KNXnet/IP gateway",
        mac=mac,
        knx_medium=medium,
    )


@dataclass
class ConnectResponse:
    channel: int
    status: int
    hpai_data: bytes
    remote_ip: str
    remote_port: int


def parse_connect_response(data: bytes) -> Optional[ConnectResponse]:
    header = parse_header(data)
    if not header or header.service_type != CONNECT_RESPONSE:
        return None
    body = data[HEADER_SIZE:]
    if len(body) < 2:
        return None
    channel = body[0]
    status = body[1]
    hpai_data = body[2:10] if len(body) >= 10 else b""
    remote_ip = ".".join(str(b) for b in hpai_data[2:6]) if len(hpai_data) >= 8 else ""
    remote_port = struct.unpack(">H", hpai_data[6:8])[0] if len(hpai_data) >= 8 else 0
    return ConnectResponse(channel, status, hpai_data, remote_ip, remote_port)


@dataclass
class TunnelingRequest:
    channel: int
    sequence: int
    cemi: bytes


def parse_tunneling_request(data: bytes) -> Optional[TunnelingRequest]:
    header = parse_header(data)
    if not header or header.service_type != TUNNELING_REQUEST:
        return None
    body = data[HEADER_SIZE:]
    # Body : header_length(1) | channel(1) | sequence(1) | reserved(1) | cEMI
    if len(body) < 4:
        return None
    return TunnelingRequest(channel=body[1], sequence=body[2], cemi=body[4:])


def parse_routing_indication(data: bytes) -> Optional[bytes]:
    """Retourne la cEMI portée par une ROUTING_INDICATION, ou None."""
    header = parse_header(data)
    if not header or header.service_type != ROUTING_INDICATION:
        return None
    return data[HEADER_SIZE:]


async def local_ip_for(host: str, port: int) -> str:
    """Utilise le noyau pour trouver l'IP source qui joindrait `host:port`."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        await loop.run_in_executor(None, sock.connect, (host, port))
        return sock.getsockname()[0]
    finally:
        sock.close()
