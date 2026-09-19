"""Unit tests for the HA-independent modules (artnet, fixture, controller).

Loads the modules without running the package __init__ (which imports
Home Assistant), so these run on any Python >= 3.11.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import socket
import sys
import types

import pytest

PKG_DIR = Path(__file__).parent.parent / "custom_components" / "artnet_light"
_pkg = types.ModuleType("artnet_core")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules.setdefault("artnet_core", _pkg)

from artnet_core.artnet import (  # noqa: E402
    build_artdmx,
    build_artpoll,
    build_artpollreply,
    is_artpoll,
    parse_artdmx,
    parse_artpollreply,
)
from artnet_core.controller import ArtNetController  # noqa: E402
from artnet_core.fixture import Fixture, find_overlap, normalize_order  # noqa: E402

# ---------------------------------------------------------------- protocol


def test_artdmx_header_and_universe_split():
    pkt = build_artdmx(0x0123, 7, bytes([1, 2, 3]))
    assert pkt[:8] == b"Art-Net\x00"
    assert pkt[8:10] == b"\x00\x50"  # OpDmx little endian
    assert pkt[10:12] == b"\x00\x0e"  # protocol 14
    assert pkt[12] == 7
    assert pkt[14] == 0x23 and pkt[15] == 0x01  # SubUni, Net
    assert pkt[16:18] == b"\x00\x04"  # padded to even length
    assert pkt[18:] == bytes([1, 2, 3, 0])
    assert parse_artdmx(pkt) == (0x0123, 7, bytes([1, 2, 3, 0]))


def test_artdmx_full_universe():
    pkt = build_artdmx(0, 1, bytes(512))
    assert len(pkt) == 18 + 512


def test_artdmx_rejects_bad_universe():
    with pytest.raises(ValueError):
        build_artdmx(0x8000, 1, b"\x00\x00")


def test_artpoll():
    pkt = build_artpoll()
    assert is_artpoll(pkt)
    assert len(pkt) == 14


def test_artpollreply_roundtrip():
    raw = build_artpollreply(
        "192.168.1.200", "Node-1", "Long name", mac="aa:bb:cc:dd:ee:ff", universes=[16, 17]
    )
    node = parse_artpollreply(raw)
    assert node is not None
    assert node.ip == "192.168.1.200"
    assert node.port == 6454
    assert node.short_name == "Node-1"
    assert node.long_name == "Long name"
    assert node.mac == "aa:bb:cc:dd:ee:ff"
    assert node.unique_id == "aa:bb:cc:dd:ee:ff"
    assert node.universes == [16, 17]


def test_artpollreply_without_mac_uses_ip():
    raw = build_artpollreply("10.0.0.5", "X")
    node = parse_artpollreply(raw)
    assert node.mac is None
    assert node.unique_id == "10.0.0.5"


def test_parse_ignores_other_packets():
    assert parse_artpollreply(build_artpoll()) is None
    assert parse_artpollreply(b"garbage") is None


# ----------------------------------------------------------------- fixture


def fx(**kw) -> Fixture:
    return Fixture(**{"id": "a", "name": "t", "type": "rgb", **kw})


def test_channel_counts():
    assert fx(type="dimmer").channel_count == 1
    assert fx(type="cct").channel_count == 2
    assert fx(type="rgb").channel_count == 3
    assert fx(type="rgbw").channel_count == 4
    assert fx(type="rgbww").channel_count == 5
    assert fx(type="rgbww", bits=16).channel_count == 10
    assert fx(start_channel=510).end_channel == 512


def test_order_validation():
    assert normalize_order("rgb", "cold_warm", "") == "RGB"
    assert normalize_order("rgb", "cold_warm", "grb") == "GRB"
    assert normalize_order("rgb", "cold_warm", "RGBW") is None
    assert normalize_order("rgb", "cold_warm", "RGX") is None
    assert normalize_order("cct", "cold_warm", "WC") == "WC"
    assert normalize_order("cct", "intensity_temp", "") == "IT"
    assert normalize_order("rgbww", "cold_warm", "") == "RGBCW"


def test_rgb_levels_and_order():
    f = fx(channel_order="GRB")
    levels = f.compute_levels(is_on=True, brightness=255, rgb=(255, 128, 0))
    assert f.encode(levels) == bytes([128, 255, 0])
    half = f.compute_levels(is_on=True, brightness=128, rgb=(255, 0, 0))
    assert f.encode(half) == bytes([0, 128, 0])


def test_off_is_zero():
    f = fx(type="rgbww", min_output=20)
    assert f.encode(f.compute_levels(is_on=False)) == bytes(5)


def test_dimmer_16bit():
    f = fx(type="dimmer", bits=16)
    assert f.encode(f.compute_levels(is_on=True, brightness=255)) == b"\xff\xff"
    assert f.encode(f.compute_levels(is_on=True, brightness=128)) == bytes((0x80, 0x80))


def test_cct_cold_warm():
    f = fx(type="cct", min_kelvin=2700, max_kelvin=6500)
    assert f.encode(f.compute_levels(is_on=True, kelvin=6500)) == bytes([255, 0])
    assert f.encode(f.compute_levels(is_on=True, kelvin=2700)) == bytes([0, 255])
    assert f.encode(f.compute_levels(is_on=True, kelvin=4600)) == bytes([128, 128])
    f2 = fx(type="cct", channel_order="WC")
    assert f2.encode(f2.compute_levels(is_on=True, kelvin=6500)) == bytes([0, 255])


def test_cct_intensity_temp():
    f = fx(type="cct", cct_mode="intensity_temp")
    assert f.channel_order == "IT"
    assert f.encode(f.compute_levels(is_on=True, brightness=128, kelvin=2700)) == bytes([128, 0])
    assert f.encode(f.compute_levels(is_on=True, brightness=255, kelvin=6500)) == bytes([255, 255])


def test_output_limits():
    f = fx(type="dimmer", min_output=10, max_output=200)
    assert f.encode(f.compute_levels(is_on=True, brightness=255)) == bytes([200])
    assert f.encode(f.compute_levels(is_on=True, brightness=1)) == bytes([11])
    # temperature channel is not limited
    c = fx(type="cct", cct_mode="intensity_temp", max_output=100)
    assert c.encode(c.compute_levels(is_on=True, kelvin=6500)) == bytes([100, 255])


def test_rgbw_and_rgbww():
    f = fx(type="rgbw")
    assert f.encode(f.compute_levels(is_on=True, rgbw=(1, 2, 3, 255))) == bytes([1, 2, 3, 255])
    g = fx(type="rgbww")
    assert g.encode(g.compute_levels(is_on=True, rgbww=(1, 2, 3, 4, 5))) == bytes([1, 2, 3, 4, 5])


def test_overlap():
    a = fx(id="a", start_channel=1)  # 1-3
    b = fx(id="b", start_channel=3)  # 3-5
    c = fx(id="c", start_channel=4)
    d = fx(id="d", start_channel=1, universe=1)
    assert find_overlap([a], b) is a
    assert find_overlap([a], c) is None
    assert find_overlap([a], d) is None
    assert find_overlap([a], a) is None  # editing itself


def test_dict_roundtrip():
    f = fx(type="rgbw", bits=16, universe=3, start_channel=9, channel_order="WRGB")
    assert Fixture.from_dict(f.to_dict()) == f


# -------------------------------------------------------------- controller


class _Receiver(asyncio.DatagramProtocol):
    def __init__(self):
        self.packets: list[tuple[int, int, bytes]] = []

    def datagram_received(self, data, addr):
        if parsed := parse_artdmx(data):
            self.packets.append(parsed)


async def _receiver():
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(_Receiver, local_addr=("127.0.0.1", 0))
    return transport, proto, transport.get_extra_info("sockname")[1]


def test_controller_on_change_and_fade():
    async def run():
        transport, rx, port = await _receiver()
        ctl = ArtNetController("127.0.0.1", port, send_mode="on_change", keepalive=5)
        await ctl.async_start()
        ctl.async_start_sending()
        f = fx(universe=2, start_channel=10)

        ctl.apply(f, f.compute_levels(is_on=True, rgb=(255, 0, 0)))
        await asyncio.sleep(0.1)
        assert rx.packets, "no packet sent on change"
        uni, seq, data = rx.packets[-1]
        assert uni == 2 and seq == 1
        assert data[9:12] == bytes([255, 0, 0])

        rx.packets.clear()
        ctl.apply(f, f.compute_levels(is_on=False), transition=0.3)
        await asyncio.sleep(0.5)
        reds = [p[2][9] for p in rx.packets]
        assert len(reds) > 3, "fade should produce several frames"
        assert reds == sorted(reds, reverse=True)
        assert reds[-1] == 0
        await ctl.async_stop()
        transport.close()

    asyncio.run(run())


def test_controller_continuous():
    async def run():
        transport, rx, port = await _receiver()
        ctl = ArtNetController("127.0.0.1", port, send_mode="continuous", fps=40)
        await ctl.async_start()
        ctl.set_channels(0, 1, b"\x01")
        ctl.async_start_sending()
        await asyncio.sleep(0.5)
        assert len(rx.packets) >= 10
        await ctl.async_stop()
        transport.close()

    asyncio.run(run())


def test_controller_keepalive():
    async def run():
        transport, rx, port = await _receiver()
        ctl = ArtNetController("127.0.0.1", port, send_mode="on_change", keepalive=0.2)
        await ctl.async_start()
        ctl.set_channels(0, 1, b"\x05")
        ctl.async_start_sending()
        await asyncio.sleep(0.75)
        assert len(rx.packets) >= 3  # initial + keep-alives without any change
        await ctl.async_stop()
        transport.close()

    asyncio.run(run())


def test_controller_blackout_sends_immediately():
    async def run():
        transport, rx, port = await _receiver()
        ctl = ArtNetController("127.0.0.1", port, send_mode="on_change", keepalive=5)
        await ctl.async_start()  # sender loop deliberately not started
        ctl.set_channels(3, 1, b"\xff\xff")
        assert ctl.universes == {3}
        ctl.blackout({3, 4})
        await asyncio.sleep(0.1)
        assert {p[0] for p in rx.packets} == {3, 4}
        assert all(p[2] == bytes(512) for p in rx.packets)
        assert ctl.universe_data(3) == bytes(512)
        await ctl.async_stop()
        transport.close()

    asyncio.run(run())
