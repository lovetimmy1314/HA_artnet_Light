"""Render the integration's brand icon (custom_components/artnet_light/brand/).

A DMX 5-pin connector face with RGBWA pins on an indigo tile. Needs Pillow, which
is not a project dependency; run it in a throwaway container, e.g.
    docker run --rm -v $PWD:/src -w /src python:3.14 sh -c "pip install -q pillow && python tools/make_icon.py"
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 2048  # supersampled canvas, scaled down at the end
OUT = Path(__file__).resolve().parent.parent / "custom_components" / "artnet_light" / "brand"

TILE_TOP = (99, 102, 241)  # indigo-500
TILE_BOTTOM = (30, 27, 75)  # indigo-950
RING = (241, 245, 249)
FACE = (15, 13, 46)
# clockwise from the upper left; the key notch sits in the gap at the top
PINS = [
    (239, 68, 68),  # red
    (34, 197, 94),  # green
    (248, 250, 252),  # white
    (59, 130, 246),  # blue
    (245, 158, 11),  # amber
]


def _tile() -> Image.Image:
    gradient = Image.new("RGBA", (S, S))
    px = gradient.load()
    for y in range(S):
        for x in range(S):
            t = min(1.0, (0.35 * x + 0.65 * y) / S)
            px[x, y] = (*(round(a + (b - a) * t) for a, b in zip(TILE_TOP, TILE_BOTTOM)), 255)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.22), fill=255)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(gradient, mask=mask)
    return tile


def _circle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, **kwargs) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), **kwargs)


def render() -> Image.Image:
    img = _tile()
    c = S / 2
    ring_r, ring_w = S * 0.34, S * 0.045

    face = ImageDraw.Draw(img)
    _circle(face, c, c, ring_r, fill=FACE, outline=RING, width=int(ring_w))
    # key notch at the top of the ring
    notch_w, notch_h = S * 0.09, S * 0.075
    top = c - ring_r + ring_w * 0.5
    face.rounded_rectangle(
        (c - notch_w / 2, top, c + notch_w / 2, top + notch_h), radius=int(S * 0.02), fill=RING
    )

    pin_orbit, pin_r = S * 0.19, S * 0.058
    centres = []
    for i, colour in enumerate(PINS):
        angle = math.radians(210 - 60 * i)  # 210, 150, 90, 30, -30 (0 = right, y down)
        centres.append((c + pin_orbit * math.cos(angle), c + pin_orbit * math.sin(angle), colour))

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for x, y, colour in centres:
        _circle(glow_draw, x, y, pin_r * 1.9, fill=(*colour, 150))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.03))
    # keep the glow inside the connector face
    mask = Image.new("L", (S, S), 0)
    _circle(ImageDraw.Draw(mask), c, c, ring_r - ring_w / 2, fill=255)
    glow.putalpha(Image.composite(glow.getchannel("A"), Image.new("L", (S, S), 0), mask))
    img = Image.alpha_composite(img, glow)

    pins = ImageDraw.Draw(img)
    for x, y, colour in centres:
        _circle(pins, x, y, pin_r, fill=(*colour, 255))
        _circle(pins, x - pin_r * 0.3, y - pin_r * 0.3, pin_r * 0.28, fill=(255, 255, 255, 110))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img = render()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        img.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
