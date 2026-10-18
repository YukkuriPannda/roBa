"""Output validation for produced files. Any ValidationError fails the job."""

from __future__ import annotations

import io
import math
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError

from .gx import read_gx


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class Bounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_max: float


# Z below this is rejected for every printer (a real print never goes under the bed).
Z_FLOOR = -1.0

_TIME = re.compile(rb";\s*estimated printing time \(normal mode\)\s*=\s*(.+)", re.I)
_FIL_MM = re.compile(rb";\s*filament used \[mm\]\s*=\s*([\d.]+)", re.I)
_FIL_G = re.compile(rb";\s*filament used \[g\]\s*=\s*([\d.]+)", re.I)
_LAYERS = re.compile(rb";\s*total layer number\s*:\s*(\d+)", re.I)

# Word = letter + number. Accepts 1, 1., .5, -1.25, +2 (case handled by upper()).
_WORD = re.compile(rb"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_LINE_NO = re.compile(rb"^N\s*\d+\s*")
_AXES = ("X", "Y", "Z")


def parse_duration_secs(text: str) -> int | None:
    total = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*([dhms])", text):
        found = True
        total += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total if found else None


def gcode_info(gcode: bytes) -> dict[str, Any]:
    """Values OrcaSlicer writes as comments (missing ones are None)."""
    info: dict[str, Any] = {"layers": None, "print_time_secs": None,
                            "filament_mm": None, "filament_g": None}
    m = _LAYERS.search(gcode)
    if m:
        info["layers"] = int(m.group(1))
    m = _TIME.search(gcode)
    if m:
        info["print_time_secs"] = parse_duration_secs(m.group(1).decode("utf-8", "replace"))
    m = _FIL_MM.search(gcode)
    if m:
        info["filament_mm"] = float(m.group(1))
    m = _FIL_G.search(gcode)
    if m:
        info["filament_g"] = float(m.group(1))
    return info


def _parse_line(raw: bytes) -> tuple[int | None, dict[str, float]]:
    """(G-code number or None, {letter: value}) for one line. Comments removed."""
    code = _LINE_NO.sub(b"", raw.split(b";", 1)[0].upper().strip())
    gcode: int | None = None
    args: dict[str, float] = {}
    for m in _WORD.finditer(code):
        letter = m.group(1).decode()
        value = float(m.group(2))
        if letter == "G" and gcode is None:
            gcode = int(value)
        elif letter in "XYZEIJ":
            args[letter] = value
    return gcode, args


def validate_gcode(gcode: bytes, bounds: Bounds | None = None) -> dict[str, Any]:
    if not gcode.strip():
        raise ValidationError("gcode is empty")
    g1_moves = 0
    max_z: float | None = None
    problems: list[str] = []
    absolute = True
    pos: dict[str, float | None] = {"X": None, "Y": None, "Z": None}  # None = unknown

    def check_point(lineno: int, axis: str, value: float) -> None:
        if axis == "Z" and value < Z_FLOOR:
            problems.append(f"line {lineno}: Z={value:g} below {Z_FLOOR:g}")
        if bounds is None:
            return
        if axis == "Z" and value > bounds.z_max + 1e-6:
            problems.append(f"line {lineno}: Z={value:g} > {bounds.z_max:g}")
        if axis == "X" and not (bounds.x_min - 1e-6 <= value <= bounds.x_max + 1e-6):
            problems.append(f"line {lineno}: X={value:g} outside [{bounds.x_min:g},{bounds.x_max:g}]")
        if axis == "Y" and not (bounds.y_min - 1e-6 <= value <= bounds.y_max + 1e-6):
            problems.append(f"line {lineno}: Y={value:g} outside [{bounds.y_min:g},{bounds.y_max:g}]")

    for lineno, raw in enumerate(gcode.splitlines(), 1):
        g, args = _parse_line(raw)
        if g is None:
            continue
        if g == 90:
            absolute = True
            continue
        if g == 91:
            absolute = False
            continue
        if g == 92:  # set position; axes not given are left unchanged
            for ax in _AXES:
                if ax in args:
                    pos[ax] = args[ax]
            continue
        if g == 28:  # homing: final position is printer-defined, so treat as unknown
            pos = {"X": None, "Y": None, "Z": None}
            continue
        if g not in (0, 1, 2, 3):
            continue

        if g == 1:
            g1_moves += 1
        target: dict[str, float | None] = {}
        for ax in _AXES:
            if ax in args:
                if absolute:
                    target[ax] = args[ax]
                else:
                    target[ax] = None if pos[ax] is None else pos[ax] + args[ax]
            else:
                target[ax] = pos[ax]

        if g in (2, 3) and bounds is not None:
            sx, sy = pos["X"], pos["Y"]
            if sx is None or sy is None:
                problems.append(f"line {lineno}: arc with unknown start position")
            elif "I" not in args and "J" not in args:
                problems.append(f"line {lineno}: arc without I/J is not supported")
            else:
                cx = sx + args.get("I", 0.0)
                cy = sy + args.get("J", 0.0)
                r = math.hypot(sx - cx, sy - cy)
                # Conservative: the whole circle's bounding box must fit.
                if cx - r < bounds.x_min - 1e-6 or cx + r > bounds.x_max + 1e-6:
                    problems.append(f"line {lineno}: arc X extent outside bounds")
                if cy - r < bounds.y_min - 1e-6 or cy + r > bounds.y_max + 1e-6:
                    problems.append(f"line {lineno}: arc Y extent outside bounds")

        for ax in _AXES:
            value = target[ax]
            if value is not None:
                check_point(lineno, ax, value)
        if target["Z"] is not None:
            max_z = target["Z"] if max_z is None else max(max_z, target["Z"])
        pos = target
        if len(problems) >= 5:
            break

    if g1_moves == 0:
        raise ValidationError("gcode contains no G1 moves")
    if problems:
        raise ValidationError("moves outside printable volume: " + "; ".join(problems))
    info = gcode_info(gcode)
    info.update({"g1_moves": g1_moves, "max_z": max_z, "bytes": len(gcode),
                 "bounds_checked": bounds is not None})
    return info


def validate_3mf(data: bytes, bounds: Bounds | None = None) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"3mf is not a valid zip: {exc}") from exc
    if zf.testzip() is not None:
        raise ValidationError("3mf zip has a corrupt member")
    names = zf.namelist()
    if "3D/3dmodel.model" not in names:
        raise ValidationError("3mf is missing 3D/3dmodel.model")
    gcodes = [n for n in names if n.lower().endswith(".gcode")]
    if not gcodes:
        raise ValidationError("3mf contains no .gcode member")
    name = "Metadata/plate_1.gcode" if "Metadata/plate_1.gcode" in gcodes else sorted(gcodes)[0]
    info = validate_gcode(zf.read(name), bounds)
    info.update({"members": len(names), "gcode_member": name})
    return info


def _image_check(data: bytes, fmt: str, size: tuple[int, int], mode: str | None, label: str) -> None:
    try:
        img = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(f"gx: {label} is not a readable image: {exc}") from exc
    if img.format != fmt or img.size != size or (mode is not None and img.mode != mode):
        raise ValidationError(f"gx: {label} must be {fmt} {size[0]}x{size[1]} {mode or ''}".strip()
                              + f", got {img.format} {img.size[0]}x{img.size[1]} {img.mode}")


def validate_gx(data: bytes, source_gcode: bytes) -> dict[str, Any]:
    try:
        parsed = read_gx(data)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if parsed["offset_bmp"] != 58:
        raise ValidationError("gx: bmp offset must be 58")
    _image_check(parsed["bmp"], "BMP", (80, 60), "RGB", "bmp (24-bit)")
    _image_check(parsed["png"], "PNG", (320, 320), None, "png thumbnail")
    if parsed["gcode"] != source_gcode:
        raise ValidationError("gx: embedded gcode differs from source gcode")
    return {"offset_bmp": parsed["offset_bmp"], "offset_png": parsed["offset_png"],
            "offset_gcode": parsed["offset_gcode"], "bytes": len(data),
            "gcode_identical": True}
