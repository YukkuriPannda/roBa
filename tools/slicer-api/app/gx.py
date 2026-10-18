"""FlashPrint-compatible .gx writer/reader (frozen format, little-endian).

Header (58 bytes, struct '<16s6L8H2B'):
  0x00 16s magic b"xgcode 1.0\n\0\0\0\0\0"
  0x10 L offset_bmp (=58)
  0x14 L offset_png (=58+len(bmp))
  0x18 L offset_gcode (=offset_png+len(png))
  0x1C L print_time_secs
  0x20 L filament_mm_right
  0x24 L filament_mm_left
  0x28 H print_flags
  0x2A H layer_height_microns
  0x2C H reserved (0)
  0x2E H perimeter_shells
  0x30 H print_speed_mm_s
  0x32 H bed_temp
  0x34 H extruder_temp_right
  0x36 H extruder_temp_left
  0x38 B material_right
  0x39 B material_left
Then BMP (80x60 24-bit), PNG (320x320), then gcode text.
"""

from __future__ import annotations

import struct
from typing import Any, Mapping

HEADER_FORMAT = "<16s6L8H2B"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 58
MAGIC = b"xgcode 1.0\n\x00\x00\x00\x00\x00"
assert len(MAGIC) == 16
assert HEADER_SIZE == 58

DEFAULT_META: dict[str, int] = {
    "print_time_secs": 0,
    "filament_mm_right": 0,
    "filament_mm_left": 0,
    "print_flags": 1,
    "layer_height_microns": 200,
    "perimeter_shells": 3,
    "print_speed_mm_s": 50,
    "bed_temp": 50,
    "extruder_temp_right": 210,
    "extruder_temp_left": 210,
    "material_right": 1,
    "material_left": 255,
}


# Field widths from the struct: L = uint32, H = uint16, B = uint8.
_LIMITS = {"print_time_secs": 2**32 - 1, "filament_mm_right": 2**32 - 1,
           "filament_mm_left": 2**32 - 1, "print_flags": 65535,
           "layer_height_microns": 65535, "perimeter_shells": 65535,
           "print_speed_mm_s": 65535, "bed_temp": 65535,
           "extruder_temp_right": 65535, "extruder_temp_left": 65535,
           "material_right": 255, "material_left": 255}


def _clamp(value: int, key: str) -> int:
    return max(0, min(int(value), _LIMITS[key]))


def write_gx(gcode: bytes, meta: Mapping[str, int] | None = None,
             bmp: bytes | None = None, png: bytes | None = None) -> bytes:
    """Build a .gx file. bmp/png are rendered from gcode when not given."""
    from .thumbnail import render_bmp, render_png

    values = dict(DEFAULT_META)
    if meta:
        values.update({k: int(v) for k, v in meta.items() if k in DEFAULT_META})
    for key, value in list(values.items()):
        values[key] = _clamp(value, key)
    if bmp is None:
        bmp = render_bmp(gcode)
    if png is None:
        png = render_png(gcode)

    offset_bmp = HEADER_SIZE
    offset_png = offset_bmp + len(bmp)
    offset_gcode = offset_png + len(png)
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        offset_bmp,
        offset_png,
        offset_gcode,
        values["print_time_secs"],
        values["filament_mm_right"],
        values["filament_mm_left"],
        values["print_flags"],
        values["layer_height_microns"],
        0,
        values["perimeter_shells"],
        values["print_speed_mm_s"],
        values["bed_temp"],
        values["extruder_temp_right"],
        values["extruder_temp_left"],
        values["material_right"],
        values["material_left"],
    )
    return header + bmp + png + gcode


def read_gx(data: bytes) -> dict[str, Any]:
    """Parse a .gx file. Raises ValueError on structural problems."""
    if len(data) < HEADER_SIZE:
        raise ValueError("gx: file shorter than header")
    (magic, off_bmp, off_png, off_gcode, print_time, fil_r, fil_l,
     print_flags, layer_um, _reserved, shells, speed, bed_temp,
     ext_r, ext_l, mat_r, mat_l) = struct.unpack_from(HEADER_FORMAT, data, 0)
    if magic != MAGIC:
        raise ValueError("gx: bad magic")
    if not (HEADER_SIZE <= off_bmp <= off_png <= off_gcode <= len(data)):
        raise ValueError("gx: offsets out of order or out of range")
    return {
        "magic": magic,
        "offset_bmp": off_bmp,
        "offset_png": off_png,
        "offset_gcode": off_gcode,
        "print_time_secs": print_time,
        "filament_mm_right": fil_r,
        "filament_mm_left": fil_l,
        "print_flags": print_flags,
        "layer_height_microns": layer_um,
        "perimeter_shells": shells,
        "print_speed_mm_s": speed,
        "bed_temp": bed_temp,
        "extruder_temp_right": ext_r,
        "extruder_temp_left": ext_l,
        "material_right": mat_r,
        "material_left": mat_l,
        "bmp": data[off_bmp:off_png],
        "png": data[off_png:off_gcode],
        "gcode": data[off_gcode:],
    }
