"""Render third-angle orthographic views of the verified case mesh."""
from pathlib import Path
import numpy as np
import FreeCAD as App
import Mesh
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

import bearing_case as model
from mesh_checks import triangles

OUTPUT = model.OUT
SOURCE = Mesh.Mesh(str(OUTPUT / "trackball_bearing.stl"))
FACES = triangles(SOURCE)
POINTS = FACES.reshape((-1, 3))
MINIMUM = POINTS.min(axis=0)
MAXIMUM = POINTS.max(axis=0)
SPANS = MAXIMUM - MINIMUM
PAD = max(SPANS) * 0.055

NORMALS = np.cross(FACES[:, 1] - FACES[:, 0], FACES[:, 2] - FACES[:, 0])
NORMALS /= np.maximum(np.linalg.norm(NORMALS, axis=1, keepdims=True), 1e-15)
LIGHT = np.array([0.45, -0.55, 0.70], dtype=float)
LIGHT /= np.linalg.norm(LIGHT)
SHADE = 0.62 + 0.33 * np.clip(NORMALS @ LIGHT, 0, 1)
BASE = np.array([0.60, 0.70, 0.78])
FACE_COLORS = np.column_stack((BASE[None, :] * SHADE[:, None], np.ones(len(SHADE))))

X, Y, Z = SPANS
VIEWS = (
    {"name": "TOP (+Z)", "position": (0, 1), "elev": 90, "azim": 0, "size": f"X × Y   {X:.1f} × {Y:.1f} mm"},
    {"name": "FRONT (+Y)", "position": (1, 1), "elev": 0, "azim": 90, "size": f"X × Z   {X:.1f} × {Z:.1f} mm"},
    {"name": "BOTTOM (−Z)", "position": (2, 1), "elev": -90, "azim": 0, "size": f"X × Y   {X:.1f} × {Y:.1f} mm"},
    {"name": "LEFT (−X)", "position": (1, 0), "elev": 0, "azim": 180, "size": f"Y × Z   {Y:.1f} × {Z:.1f} mm"},
    {"name": "RIGHT (+X)", "position": (1, 2), "elev": 0, "azim": 0, "size": f"Y × Z   {Y:.1f} × {Z:.1f} mm"},
    {"name": "REAR (−Y)", "position": (1, 3), "elev": 0, "azim": 270, "size": f"X × Z   {X:.1f} × {Z:.1f} mm"},
)


def main():
    fig = plt.figure(figsize=(16.5, 11.7), facecolor="white")
    grid = fig.add_gridspec(
        3,
        4,
        width_ratios=(1.0, 1.25, 1.25, 1.0),
        height_ratios=(1.0, 1.25, 1.0),
        left=0.04,
        right=0.96,
        bottom=0.07,
        top=0.91,
        wspace=0.06,
        hspace=0.12,
    )
    for view in VIEWS:
        ax = fig.add_subplot(grid[view["position"]], projection="3d")
        ax.set_proj_type("ortho")
        ax.add_collection3d(
            Poly3DCollection(
                FACES,
                facecolors=FACE_COLORS,
                edgecolors="none",
                linewidths=0,
                zsort="average",
                rasterized=True,
            )
        )
        ax.set_xlim(MINIMUM[0] - PAD, MAXIMUM[0] + PAD)
        ax.set_ylim(MINIMUM[1] - PAD, MAXIMUM[1] + PAD)
        ax.set_zlim(MINIMUM[2] - PAD, MAXIMUM[2] + PAD)
        ax.set_box_aspect(SPANS + 2 * PAD)
        ax.view_init(elev=view["elev"], azim=view["azim"])
        ax.set_axis_off()
        ax.set_title(view["name"] + "\n" + view["size"], fontsize=11, pad=4)

    fig.suptitle("34mm Trackball Bearing Case — Six Orthographic Views", fontsize=17, y=0.965)
    fig.text(
        0.5,
        0.035,
        "Third-angle projection  |  units: mm  |  overall extents only; no manufacturing tolerances specified",
        ha="center",
        fontsize=10,
        color="#444444",
    )
    fig.savefig(OUTPUT / "six_view.png", dpi=240, facecolor="white")
    fig.savefig(OUTPUT / "six_view.pdf", dpi=240, facecolor="white", metadata={"Title": "34mm Trackball Bearing Case — Six Orthographic Views"})
    plt.close(fig)
    print(
        "Rendered six views",
        OUTPUT,
        "overall_mm=",
        [round(float(v), 3) for v in SPANS],
        flush=True,
    )


if __name__ == "__main__":
    main()
