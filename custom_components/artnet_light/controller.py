"""Art-Net output controller: universe buffers, send loop and fades.

Pure asyncio, no Home Assistant imports.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time

from .artnet import DMX_UNIVERSE_SIZE, build_artdmx
from .const import SEND_MODE_CONTINUOUS
from .fixture import Fixture

_LOGGER = logging.getLogger(__name__)

FADE_STEP = 0.025  # seconds between fade frames


class ArtNetController:
    """Owns the UDP socket and DMX buffers for one Art-Net node."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        send_mode: str,
        keepalive: float = 1.0,
        fps: float = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.send_mode = send_mode
        self.keepalive = max(float(keepalive), 0.1)
        self.fps = min(max(float(fps), 1.0), 44.0)

        self._buffers: dict[int, bytearray] = {}
        self._sequence: dict[int, int] = {}
        self._dirty: set[int] = set()
        self._wake = asyncio.Event()
        self._transport: asyncio.DatagramTransport | None = None
        self._sender: asyncio.Task | None = None
        self._levels: dict[str, list[float]] = {}
        self._fades: dict[str, asyncio.Task] = {}

    # ---------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Open the UDP socket. Sending starts with async_start_sending()."""
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        sock.bind(("0.0.0.0", 0))
        self._transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, sock=sock)

    def async_start_sending(self) -> None:
        """Start the send loop (called once entities have restored their state)."""
        if self._sender is None:
            self._sender = asyncio.get_running_loop().create_task(self._run())

    async def async_stop(self) -> None:
        tasks = [*self._fades.values()]
        if self._sender:
            tasks.append(self._sender)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._fades.clear()
        self._sender = None
        if self._transport:
            self._transport.close()
            self._transport = None

    # ------------------------------------------------------------------ buffers

    def set_channels(self, universe: int, start_channel: int, data: bytes) -> None:
        """Write raw bytes at a 1-based start channel."""
        is_new = universe not in self._buffers
        buf = self._buffers.setdefault(universe, bytearray(DMX_UNIVERSE_SIZE))
        offset = start_channel - 1
        data = data[: DMX_UNIVERSE_SIZE - offset]
        if not is_new and buf[offset : offset + len(data)] == data:
            return
        buf[offset : offset + len(data)] = data
        self._dirty.add(universe)
        self._wake.set()

    def universe_data(self, universe: int) -> bytes:
        return bytes(self._buffers.get(universe, bytearray(DMX_UNIVERSE_SIZE)))

    # -------------------------------------------------------------------- fades

    def apply(self, fixture: Fixture, levels: list[float], transition: float = 0.0) -> None:
        """Move a fixture to target levels, optionally fading over `transition` seconds."""
        if task := self._fades.pop(fixture.id, None):
            task.cancel()

        current = self._levels.get(fixture.id)
        if transition <= 0 or current is None or len(current) != len(levels):
            self._write(fixture, levels)
            return

        self._fades[fixture.id] = asyncio.get_running_loop().create_task(
            self._fade(fixture, list(current), list(levels), transition)
        )

    def _write(self, fixture: Fixture, levels: list[float]) -> None:
        self._levels[fixture.id] = list(levels)
        self.set_channels(fixture.universe, fixture.start_channel, fixture.encode(levels))

    async def _fade(self, fixture: Fixture, start: list[float], end: list[float], duration: float) -> None:
        loop_start = time.monotonic()
        try:
            while True:
                progress = min((time.monotonic() - loop_start) / duration, 1.0)
                self._write(fixture, [a + (b - a) * progress for a, b in zip(start, end)])
                if progress >= 1.0:
                    break
                await asyncio.sleep(FADE_STEP)
        finally:
            if self._fades.get(fixture.id) is asyncio.current_task():
                del self._fades[fixture.id]

    # --------------------------------------------------------------------- send

    def _send(self, universe: int) -> None:
        if self._transport is None:
            return
        seq = self._sequence.get(universe, 0) % 255 + 1
        self._sequence[universe] = seq
        try:
            self._transport.sendto(build_artdmx(universe, seq, self._buffers[universe]), (self.host, self.port))
        except OSError as err:
            _LOGGER.debug("Art-Net send to %s failed: %s", self.host, err)

    async def _run(self) -> None:
        if self.send_mode == SEND_MODE_CONTINUOUS:
            interval = 1 / self.fps
            while True:
                self._dirty.clear()
                self._wake.clear()
                for universe in list(self._buffers):
                    self._send(universe)
                await asyncio.sleep(interval)

        last_full = time.monotonic()
        while True:
            timeout = self.keepalive - (time.monotonic() - last_full)
            if timeout > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout)
                except TimeoutError:
                    pass
            self._wake.clear()
            if time.monotonic() - last_full >= self.keepalive:
                self._dirty.clear()
                for universe in list(self._buffers):
                    self._send(universe)
                last_full = time.monotonic()
            else:
                dirty, self._dirty = self._dirty, set()
                for universe in dirty:
                    self._send(universe)
