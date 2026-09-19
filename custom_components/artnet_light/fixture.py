"""Fixture model: maps Home Assistant light state to DMX channel values.

Kept free of Home Assistant imports so it can be unit tested standalone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import uuid

from .const import (
    CCT_MODE_CW,
    CCT_MODE_IT,
    CCT_MODES,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    FIXTURE_TYPES,
    TYPE_CCT,
    TYPE_DIMMER,
    TYPE_RGB,
    TYPE_RGBW,
    TYPE_RGBWW,
)

# Channel letters:
#   I = intensity, T = colour temperature (0 = warm, full = cold)
#   R/G/B = red/green/blue, W = (warm) white, C = cold white
DEFAULT_ORDER: dict[tuple[str, str | None], str] = {
    (TYPE_DIMMER, None): "I",
    (TYPE_CCT, CCT_MODE_CW): "CW",
    (TYPE_CCT, CCT_MODE_IT): "IT",
    (TYPE_RGB, None): "RGB",
    (TYPE_RGBW, None): "RGBW",
    (TYPE_RGBWW, None): "RGBCW",
}

# Channels that are not scaled by the min/max output limits
_UNLIMITED = {"T"}


def default_order(fixture_type: str, cct_mode: str = CCT_MODE_CW) -> str:
    return DEFAULT_ORDER[(fixture_type, cct_mode if fixture_type == TYPE_CCT else None)]


def normalize_order(fixture_type: str, cct_mode: str, order: str | None) -> str | None:
    """Return a validated channel order, the default if empty, or None if invalid."""
    default = default_order(fixture_type, cct_mode)
    order = (order or "").strip().upper()
    if not order:
        return default
    if len(order) != len(default) or sorted(order) != sorted(default):
        return None
    return order


@dataclass
class Fixture:
    """One light fixture patched into a universe."""

    id: str
    name: str
    type: str
    universe: int = 0
    start_channel: int = 1
    bits: int = 8
    channel_order: str = ""
    cct_mode: str = CCT_MODE_CW
    min_kelvin: int = DEFAULT_MIN_KELVIN
    max_kelvin: int = DEFAULT_MAX_KELVIN
    min_output: int = 0
    max_output: int = 255

    def __post_init__(self) -> None:
        if self.type not in FIXTURE_TYPES:
            raise ValueError(f"unknown fixture type {self.type}")
        if self.cct_mode not in CCT_MODES:
            self.cct_mode = CCT_MODE_CW
        self.bits = 16 if int(self.bits) == 16 else 8
        self.channel_order = normalize_order(self.type, self.cct_mode, self.channel_order) or default_order(
            self.type, self.cct_mode
        )

    @classmethod
    def from_dict(cls, data: dict) -> Fixture:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.setdefault("id", uuid.uuid4().hex)
        return cls(**known)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def components(self) -> str:
        return self.channel_order

    @property
    def bytes_per_component(self) -> int:
        return self.bits // 8

    @property
    def channel_count(self) -> int:
        return len(self.components) * self.bytes_per_component

    @property
    def end_channel(self) -> int:
        return self.start_channel + self.channel_count - 1

    def overlaps(self, other: Fixture) -> bool:
        return (
            self.universe == other.universe
            and self.start_channel <= other.end_channel
            and other.start_channel <= self.end_channel
        )

    # ------------------------------------------------------------------ levels

    def _cold_fraction(self, kelvin: int | None) -> float:
        span = self.max_kelvin - self.min_kelvin
        if kelvin is None or span <= 0:
            return 0.5
        return min(max((kelvin - self.min_kelvin) / span, 0.0), 1.0)

    def compute_levels(
        self,
        *,
        is_on: bool,
        brightness: int = 255,
        rgb: tuple[int, int, int] | None = None,
        rgbw: tuple[int, int, int, int] | None = None,
        rgbww: tuple[int, int, int, int, int] | None = None,
        kelvin: int | None = None,
    ) -> list[float]:
        """Return one level (0.0-1.0 of full scale) per component, in output order."""
        if not is_on:
            return [0.0] * len(self.components)

        bri = min(max(brightness, 0), 255) / 255
        comp: dict[str, float] = {}

        if self.type == TYPE_DIMMER:
            comp["I"] = bri
        elif self.type == TYPE_CCT:
            cold = self._cold_fraction(kelvin)
            if self.cct_mode == CCT_MODE_IT:
                comp["I"] = bri
                comp["T"] = cold
            else:
                comp["C"] = bri * cold
                comp["W"] = bri * (1 - cold)
        elif self.type == TYPE_RGB:
            r, g, b = rgb or (255, 255, 255)
            comp.update(R=r / 255 * bri, G=g / 255 * bri, B=b / 255 * bri)
        elif self.type == TYPE_RGBW:
            r, g, b, w = rgbw or (0, 0, 0, 255)
            comp.update(R=r / 255 * bri, G=g / 255 * bri, B=b / 255 * bri, W=w / 255 * bri)
        elif self.type == TYPE_RGBWW:
            r, g, b, c, w = rgbww or (0, 0, 0, 255, 255)
            comp.update(
                R=r / 255 * bri, G=g / 255 * bri, B=b / 255 * bri, C=c / 255 * bri, W=w / 255 * bri
            )

        lo = self.min_output / 255
        hi = self.max_output / 255
        levels = []
        for letter in self.components:
            value = comp.get(letter, 0.0)
            if letter not in _UNLIMITED and value > 0:
                value = lo + value * (hi - lo)
            levels.append(min(max(value, 0.0), 1.0))
        return levels

    def encode(self, levels: list[float]) -> bytes:
        """Encode levels to raw DMX bytes (16-bit = coarse byte then fine byte)."""
        out = bytearray()
        for level in levels:
            level = min(max(level, 0.0), 1.0)
            if self.bits == 16:
                value = round(level * 0xFFFF)
                out += bytes((value >> 8, value & 0xFF))
            else:
                out.append(round(level * 0xFF))
        return bytes(out)


def find_overlap(fixtures: list[Fixture], candidate: Fixture) -> Fixture | None:
    """Return the first existing fixture whose channels collide with candidate."""
    for other in fixtures:
        if other.id != candidate.id and candidate.overlaps(other):
            return other
    return None
