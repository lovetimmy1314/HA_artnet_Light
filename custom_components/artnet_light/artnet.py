"""Minimal Art-Net 4 protocol helpers (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import struct

ARTNET_PORT = 6454
ARTNET_ID = b"Art-Net\x00"
PROTOCOL_VERSION = 14

OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
OP_DMX = 0x5000

DMX_UNIVERSE_SIZE = 512
MAX_PORT_ADDRESS = 0x7FFF

# Offsets inside ArtPollReply
_REPLY_MIN_LEN = 207  # up to and including the MAC address


@dataclass
class ArtNetNode:
    """A node found through ArtPoll."""

    ip: str
    port: int = ARTNET_PORT
    short_name: str = ""
    long_name: str = ""
    mac: str | None = None
    universes: list[int] = field(default_factory=list)

    @property
    def unique_id(self) -> str:
        """MAC if the node reports one, otherwise its IP."""
        return self.mac or self.ip

    @property
    def display_name(self) -> str:
        return self.short_name or self.long_name or self.ip

    def as_dict(self) -> dict:
        return {
            "ip": self.ip,
            "port": self.port,
            "short_name": self.short_name,
            "long_name": self.long_name,
            "mac": self.mac,
            "universes": list(self.universes),
            "unique_id": self.unique_id,
        }


def _opcode(data: bytes) -> int | None:
    if len(data) < 10 or not data.startswith(ARTNET_ID):
        return None
    return struct.unpack_from("<H", data, 8)[0]


def build_artdmx(port_address: int, sequence: int, data: bytes | bytearray) -> bytes:
    """Build an ArtDmx packet for a 15-bit port address (Net:SubNet:Universe)."""
    if not 0 <= port_address <= MAX_PORT_ADDRESS:
        raise ValueError(f"universe {port_address} out of range")
    payload = bytes(data[:DMX_UNIVERSE_SIZE])
    if len(payload) < 2:
        payload = payload.ljust(2, b"\x00")
    if len(payload) % 2:
        payload += b"\x00"
    return (
        ARTNET_ID
        + struct.pack("<H", OP_DMX)
        + struct.pack(">H", PROTOCOL_VERSION)
        + bytes(
            (
                sequence & 0xFF,
                0,  # physical
                port_address & 0xFF,  # SubUni
                (port_address >> 8) & 0x7F,  # Net
            )
        )
        + struct.pack(">H", len(payload))
        + payload
    )


def parse_artdmx(data: bytes) -> tuple[int, int, bytes] | None:
    """Return (port_address, sequence, dmx_data) or None."""
    if _opcode(data) != OP_DMX or len(data) < 18:
        return None
    seq, _phys, sub_uni, net = data[12], data[13], data[14], data[15]
    length = struct.unpack_from(">H", data, 16)[0]
    return (net << 8) | sub_uni, seq, bytes(data[18 : 18 + length])


def build_artpoll() -> bytes:
    """ArtPoll: ask every node to send an ArtPollReply."""
    return ARTNET_ID + struct.pack("<H", OP_POLL) + struct.pack(">H", PROTOCOL_VERSION) + b"\x00\x00"


def is_artpoll(data: bytes) -> bool:
    return _opcode(data) == OP_POLL


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def parse_artpollreply(data: bytes, source_ip: str | None = None) -> ArtNetNode | None:
    """Parse an ArtPollReply packet into an ArtNetNode."""
    if _opcode(data) != OP_POLL_REPLY or len(data) < 174:
        return None

    ip = str(ipaddress.IPv4Address(data[10:14]))
    if ip == "0.0.0.0" and source_ip:
        ip = source_ip
    port = struct.unpack_from("<H", data, 14)[0] or ARTNET_PORT

    net_switch = data[18] & 0x7F
    sub_switch = data[19] & 0x0F
    short_name = _cstr(data[26:44])
    long_name = _cstr(data[44:108])

    universes: list[int] = []
    if len(data) >= 194:
        num_ports = min(struct.unpack_from(">H", data, 172)[0], 4)
        for i in range(num_ports):
            port_type = data[174 + i]
            if port_type & 0x80:  # port can output DMX from the network
                universes.append((net_switch << 8) | (sub_switch << 4) | (data[190 + i] & 0x0F))

    mac = None
    if len(data) >= _REPLY_MIN_LEN:
        raw_mac = data[201:207]
        if any(raw_mac):
            mac = ":".join(f"{b:02x}" for b in raw_mac)

    return ArtNetNode(
        ip=ip,
        port=port,
        short_name=short_name,
        long_name=long_name,
        mac=mac,
        universes=universes,
    )


def build_artpollreply(
    ip: str,
    short_name: str,
    long_name: str = "",
    mac: str | None = None,
    universes: list[int] | None = None,
) -> bytes:
    """Build an ArtPollReply (used by tests and the fake node tool)."""
    universes = (universes or [0])[:4]
    net = (universes[0] >> 8) & 0x7F
    sub = (universes[0] >> 4) & 0x0F
    pkt = bytearray(239)
    pkt[0:8] = ARTNET_ID
    struct.pack_into("<H", pkt, 8, OP_POLL_REPLY)
    pkt[10:14] = ipaddress.IPv4Address(ip).packed
    struct.pack_into("<H", pkt, 14, ARTNET_PORT)
    pkt[18] = net
    pkt[19] = sub
    pkt[26 : 26 + 17] = short_name.encode()[:17].ljust(17, b"\x00")
    pkt[44 : 44 + 63] = long_name.encode()[:63].ljust(63, b"\x00")
    struct.pack_into(">H", pkt, 172, len(universes))
    for i, uni in enumerate(universes):
        pkt[174 + i] = 0x80  # output port, DMX512
        pkt[182 + i] = 0x80
        pkt[190 + i] = uni & 0x0F
    if mac:
        pkt[201:207] = bytes(int(p, 16) for p in mac.split(":"))
    return bytes(pkt)
