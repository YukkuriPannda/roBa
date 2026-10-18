"""Printer presets: allowed outputs, default profile files, system parents, print volume."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .validate import Bounds

PROFILE_DIR = Path(os.environ.get("PROFILE_DIR", Path(__file__).resolve().parent.parent / "profiles"))

PROFILE_KINDS = ("machine", "process", "filament")
# OrcaSlicer "type" value written into each profile kind.
PROFILE_TYPE = {"machine": "machine", "process": "process", "filament": "filament"}


@dataclass(frozen=True)
class PrinterSpec:
    id: str
    name: str
    outputs: tuple[str, ...]
    bounds: Bounds | None
    profile_dir: Path
    # System parent per kind (None = no parent; uploads may not set inherits).
    parents: dict[str, str | None] = field(default_factory=dict)


PRINTERS: dict[str, PrinterSpec] = {
    "ad4": PrinterSpec(
        id="ad4",
        name="FlashForge Adventurer 4 (custom profile, UNVERIFIED on hardware)",
        outputs=("gx", "gcode"),
        # Center-origin bed, as in the custom machine profile (see README).
        bounds=Bounds(x_min=-110.0, x_max=110.0, y_min=-100.0, y_max=100.0, z_max=250.0),
        profile_dir=PROFILE_DIR / "ad4",
        parents={"machine": "Flashforge Adventurer 4 Series 0.4 Nozzle",
                 "process": "0.20mm Standard @Flashforge AD4 0.4 Nozzle",
                 "filament": None},
    ),
    "ad5mpro": PrinterSpec(
        id="ad5mpro",
        name="FlashForge Adventurer 5M Pro (OrcaSlicer system profile inheritance)",
        outputs=("gcode", "3mf"),
        bounds=None,
        profile_dir=PROFILE_DIR / "ad5mpro",
        parents={"machine": "Flashforge Adventurer 5M Pro 0.4 Nozzle",
                 "process": "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle",
                 "filament": "Flashforge Generic PLA"},
    ),
}


def get_printer(printer_id: str) -> PrinterSpec | None:
    return PRINTERS.get(printer_id)


def default_profile_bytes(spec: PrinterSpec) -> dict[str, bytes]:
    return {kind: (spec.profile_dir / f"{kind}.json").read_bytes() for kind in PROFILE_KINDS}
