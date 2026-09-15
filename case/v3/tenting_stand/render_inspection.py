import os
from pathlib import Path

import cadquery as cq
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


ROOT = Path(__file__).resolve().parents[3]


def add_shape(axes, shape, elevation: float, azimuth: float, title: str) -> None:
    vertices, triangles = shape.tessellate(0.4, 0.2)
    points = [vertex.toTuple() for vertex in vertices]
    faces = [[points[index] for index in triangle] for triangle in triangles]
    bounds = shape.BoundingBox()
    axes.add_collection3d(
        Poly3DCollection(
            faces,
            facecolor="#8db6d9",
            edgecolor="#333333",
            linewidth=0.05,
        )
    )
    axes.set_xlim(bounds.xmin, bounds.xmax)
    axes.set_ylim(bounds.ymin, bounds.ymax)
    axes.set_zlim(bounds.zmin, bounds.zmax + 0.01)
    axes.set_box_aspect((bounds.xlen, bounds.ylen, max(bounds.zlen, 20)))
    axes.view_init(elevation, azimuth)
    axes.set_title(title)
    axes.set_axis_off()


def render(output: Path) -> None:
    figure = plt.figure(figsize=(12, 8))
    generated = ROOT / "case" / "v3" / "tenting_stand" / "generated"
    stand = cq.importers.importStep(
        str(generated / "roBa_v3_tenting_stand_7deg.step")
    ).val()
    left = cq.importers.importStep(
        str(generated / "roBa_v3_bottom_L_dovetail.step")
    ).val()
    right = cq.importers.importStep(
        str(generated / "roBa_v3_bottom_R_dovetail.step")
    ).val()

    add_shape(
        figure.add_subplot(2, 2, 1, projection="3d"),
        stand,
        25,
        -55,
        "stand: dovetail grooves",
    )
    add_shape(
        figure.add_subplot(2, 2, 2, projection="3d"),
        stand,
        0,
        -90,
        "stand: 7 degree profile",
    )
    add_shape(
        figure.add_subplot(2, 2, 3, projection="3d"),
        left,
        -25,
        -55,
        "bottom L: male rails",
    )
    add_shape(
        figure.add_subplot(2, 2, 4, projection="3d"),
        right,
        -25,
        -125,
        "bottom R: male rails",
    )

    figure.tight_layout()
    figure.savefig(output, dpi=180)
    plt.close(figure)


if __name__ == "__main__":
    render(ROOT / "case" / "v3" / "tenting_stand" / "preview.png")
    os._exit(0)
