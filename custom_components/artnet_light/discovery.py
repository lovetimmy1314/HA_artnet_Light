"""Art-Net node discovery via ArtPoll."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import socket

from homeassistant.components import network
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .artnet import ARTNET_PORT, ArtNetNode, build_artpoll, parse_artpollreply
from .const import DISCOVERY_INTERVAL_MIN, DISCOVERY_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

_BACKGROUND_KEY = f"{DOMAIN}_discovery"


class _ReplyCollector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.nodes: dict[str, ArtNetNode] = {}

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        node = parse_artpollreply(data, addr[0])
        if node is None:
            return
        if existing := self.nodes.get(node.unique_id):
            # Nodes with more than 4 ports send one reply per bind index
            existing.universes = sorted({*existing.universes, *node.universes})
        else:
            self.nodes[node.unique_id] = node


def _open_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    try:
        # Spec-compliant nodes reply to port 6454 of the poller
        sock.bind(("0.0.0.0", ARTNET_PORT))
    except OSError:
        # Something else owns 6454; nodes that reply to the source port still work
        sock.bind(("0.0.0.0", 0))
    return sock


async def _broadcast_targets(hass: HomeAssistant) -> set[str]:
    targets = {"255.255.255.255"}
    try:
        targets |= {str(addr) for addr in await network.async_get_ipv4_broadcast_addresses(hass)}
    except Exception:  # noqa: BLE001 - discovery must never break setup
        _LOGGER.debug("Could not read broadcast addresses", exc_info=True)
    return targets


async def async_scan(hass: HomeAssistant, timeout: float = DISCOVERY_TIMEOUT) -> list[ArtNetNode]:
    """Broadcast ArtPoll and collect replies for `timeout` seconds."""
    targets = await _broadcast_targets(hass)
    loop = asyncio.get_running_loop()
    try:
        transport, collector = await loop.create_datagram_endpoint(_ReplyCollector, sock=_open_socket())
    except OSError as err:
        _LOGGER.warning("Art-Net discovery could not open a socket: %s", err)
        return []

    poll = build_artpoll()
    try:
        # Poll twice: UDP broadcasts are occasionally dropped
        for _ in range(2):
            for target in targets:
                try:
                    transport.sendto(poll, (target, ARTNET_PORT))
                except OSError as err:
                    _LOGGER.debug("ArtPoll to %s failed: %s", target, err)
            await asyncio.sleep(timeout / 2)
    finally:
        transport.close()

    nodes = list(collector.nodes.values())
    _LOGGER.debug("Art-Net discovery found %s", [n.as_dict() for n in nodes])
    return nodes


@callback
def async_start_background_discovery(hass: HomeAssistant) -> None:
    """Periodically poll the network and raise discovery flows for new nodes."""
    if _BACKGROUND_KEY in hass.data:
        return

    async def _discover(_now=None) -> None:
        for node in await async_scan(hass):
            discovery_flow.async_create_flow(
                hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data=node.as_dict(),
            )

    hass.data[_BACKGROUND_KEY] = [
        async_call_later(hass, 30, _discover),
        async_track_time_interval(
            hass, _discover, timedelta(minutes=DISCOVERY_INTERVAL_MIN), cancel_on_shutdown=True
        ),
    ]
