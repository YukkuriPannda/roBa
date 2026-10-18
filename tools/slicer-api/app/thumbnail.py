"""Top-down thumbnails of extrusion moves, rendered with Pillow only."""

from __future__ import annotations

import io
import re

from PIL import Image, ImageDraw

_MOVE = re.compile(rb"^G[01](?:\s|$)")
_TOKEN = re.compile(rb"([XYZE])(-?\d+(?:\.\d+)?)")


def extrusion_segments(gcode: bytes) -> list[tuple[float, float, float, float]]:
    """(x0,y0,x1,y1) for G0/G1 moves that extrude (E increases). Absolute mode assumed."""
    segs: list[tuple[float, float, float, float]] = []
    x = y = e = 0.0
    for raw in gcode.splitlines():
        line = raw.split(b";", 1)[0].strip()
        if not _MOVE.match(line):
            continue
        parts = dict((k.decode(), float(v)) for k, v in _TOKEN.findall(line))
        nx, ny = parts.get("X", x), parts.get("Y", y)
        ne = parts.get("E", e)
        if ne > e and (nx != x or ny != y):
            segs.append((x, y, nx, ny))
        x, y, e = nx, ny, ne
    return segs


def _render(gcode: bytes, size: tuple[int, int], pad: int) -> Image.Image:
    img = Image.new("RGB", size, (255, 255, 255))
    segs = extrusion_segments(gcode)
    if not segs:
        return img
    xs = [p for s in segs for p in (s[0], s[2])]
    ys = [p for s in segs for p in (s[1], s[3])]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6)
    w, h = size
    scale = (min(w, h) - 2 * pad) / span

    def tr(px: float, py: float) -> tuple[float, float]:
        # Image y grows downward; print bed y grows upward.
        return (pad + (px - minx) * scale,
                h - pad - (py - miny) * scale)

    draw = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in segs:
        draw.line([tr(x0, y0), tr(x1, y1)], fill=(0, 90, 200), width=1)
    return img


def render_png(gcode: bytes) -> bytes:
    buf = io.BytesIO()
    _render(gcode, (320, 320), 8).save(buf, format="PNG")
    return buf.getvalue()


def render_bmp(gcode: bytes) -> bytes:
    buf = io.BytesIO()
    _render(gcode, (80, 60), 2).save(buf, format="BMP")
    return buf.getvalue()
