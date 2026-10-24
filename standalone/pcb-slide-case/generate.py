"""Build the standalone 100 x 100 x 50 mm internal PLA slide-lid case.

Run with FreeCAD 1.1's bundled Python from the repository root:
  & "$env:LOCALAPPDATA/Programs/FreeCAD 1.1/bin/python.exe" standalone/pcb-slide-case/generate.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import FreeCAD as App
import Part
import MeshPart


OUT = Path(__file__).resolve().parent
FC_VERSION = App.Version()[0]
DOC = App.newDocument("PcbSlideCase")


def spreadsheet():
    obj = DOC.addObject("Spreadsheet::Sheet", "Parameters")
    obj.Label = "設計寸法 (mm)"
    rows = [
        ("内寸 X", "100 mm", "InnerX"),
        ("内寸 Y", "100 mm", "InnerY"),
        ("内高", "50 mm", "InnerZ"),
        ("壁厚", "3 mm", "Wall"),
        ("床厚", "3 mm", "Floor"),
        ("蓋厚", "3 mm", "LidThickness"),
        ("摺動クリアランス", "0.3 mm", "Clearance"),
        ("開方向の設計ストローク", "50 mm", "Travel"),
    ]
    obj.set("A1", "項目")
    obj.set("B1", "値")
    for i, (label, value, alias) in enumerate(rows, 2):
        cell = f"A{i}"
        val_cell = f"B{i}"
        obj.set(cell, label)
        obj.set(val_cell, value)
        obj.setAlias(val_cell, alias)
    obj.set("A11", "派生外寸 X")
    obj.set("B11", "=B2+2*B5")
    obj.setAlias("B11", "OuterX")
    obj.set("A12", "派生外寸 Y")
    obj.set("B12", "=B3+2*B5")
    obj.setAlias("B12", "OuterY")
    obj.set("A13", "派生本体高さ")
    obj.set("B13", "=B4+B6")
    obj.setAlias("B13", "ShellHeight")
    obj.recompute()
    return obj


P = spreadsheet()
OUTER_X = 106.0
OUTER_Y = 106.0
SHELL_H = 53.0
LID_T = 3.0
LID_GAP = 0.3
RAIL_TOP = 59.6
CAP_BOTTOM = 56.6
TRAVEL = 50.0


def box(name, label, length, width, height, x=0.0, y=0.0, z=0.0):
    obj = DOC.addObject("Part::Box", name)
    obj.Label = label
    obj.Length = length
    obj.Width = width
    obj.Height = height
    obj.Placement.Base = App.Vector(x, y, z)
    return obj


blank = box("OuterBlank", "外殻ブランク", OUTER_X, OUTER_Y, SHELL_H)
void = box("CavityVoid", "内寸 100×100×50", 100.0, 100.0, 50.0, 3.0, 3.0, 3.0)
shell = DOC.addObject("Part::Cut", "HollowShell")
shell.Label = "底・4壁 (各3 mm)"
shell.Base = blank
shell.Tool = void

# The rails start at z=53, above the specified 50 mm clear cavity. The lid
# rides on the wall tops and is held by a 0.3 mm overhead gap in the caps.
rail_parts = [
    box("FrontRailSeat", "前レール下座", 106.0, 5.5, 0.3, 0.0, 0.0, 53.0),
    box("RearRailSeat", "後レール下座", 106.0, 5.5, 0.3, 0.0, 100.5, 53.0),
    box("FrontRailWeb", "前レール支柱", 106.0, 1.2, 6.7, 0.0, 0.0, 52.9),
    box("RearRailWeb", "後レール支柱", 106.0, 1.2, 6.7, 0.0, 104.8, 52.9),
    box("FrontRailCap", "前レール上押さえ", 106.0, 4.4, 3.0, 0.0, 1.1, 56.6),
    box("RearRailCap", "後レール上押さえ", 106.0, 4.4, 3.0, 0.0, 100.5, 56.6),
    box("RearStop", "閉方向ストッパー", 0.5, 103.6, 6.7, 105.5, 1.2, 52.9),
]

base = shell
for idx, feature in enumerate(rail_parts, 1):
    fused = DOC.addObject("Part::Fuse", f"BaseFuse{idx}")
    fused.Label = f"本体・レール結合 {idx}"
    fused.Base = base
    fused.Tool = feature
    fused.Refine = True
    base = fused

lid = box("SlideLid", "摺動蓋 (厚さ3 mm)", 103.0, 103.0, 3.0, 2.5, 1.5, 53.3)
DOC.recompute()

# A preview-friendly exploded pose sits beside the case, at the design travel.
lid_open = DOC.addObject("Part::Feature", "ExplodedLidPreview")
lid_open.Label = "開状態プレビュー (50 mm)"
lid_open.Shape = lid.Shape.copy()
lid_open.Shape.translate(App.Vector(-TRAVEL, 112.0, 8.0))

base.ViewObject.ShapeColor = (0.72, 0.76, 0.82)
lid.ViewObject.ShapeColor = (0.94, 0.58, 0.20)
lid_open.ViewObject.ShapeColor = (0.94, 0.58, 0.20)
for obj in [blank, void, shell, *rail_parts, *[DOC.getObject(f"BaseFuse{i}") for i in range(1, len(rail_parts) + 1)], lid]:
    obj.ViewObject.Visibility = False
DOC.getObject("BaseFuse7").ViewObject.Visibility = True
lid_open.ViewObject.Visibility = True


def bb(shape):
    b = shape.BoundBox
    return [round(v, 4) for v in (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)]


base_shape = base.Shape
lid_shape = lid.Shape
base_shape.exportStep(str(OUT / "base.step"))
lid_shape.exportStep(str(OUT / "lid.step"))
MeshPart.meshFromShape(Shape=base_shape, LinearDeflection=0.15, AngularDeflection=0.35, Relative=False).write(str(OUT / "base.stl"))
MeshPart.meshFromShape(Shape=lid_shape, LinearDeflection=0.15, AngularDeflection=0.35, Relative=False).write(str(OUT / "lid.stl"))
DOC.recompute()
DOC.saveAs(str(OUT / "pcb_slide_case.FCStd"))

record = {
    "freecad_version": FC_VERSION,
    "units": "mm",
    "input_contract": {"cavity_mm": [100, 100, 50], "floor_mm": 3, "wall_mm": 3, "lid_mm": 3},
    "derived_closed_outer_mm": [106, 106, 59.6],
    "planned_slide_travel_mm": TRAVEL,
    "base_bbox_mm": bb(base_shape),
    "lid_bbox_closed_mm": bb(lid_shape),
    "base_valid": bool(base_shape.isValid()),
    "base_solids": len(base_shape.Solids),
    "lid_valid": bool(lid_shape.isValid()),
    "base_volume_mm3": base_shape.Volume,
    "lid_volume_mm3": lid_shape.Volume,
}
(OUT / "build_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(record, ensure_ascii=False, indent=2))
