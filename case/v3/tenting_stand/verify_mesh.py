"""Check generated binary STL files for holes, non-manifold edges and degeneracy."""

from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent


def quantized(vertex: np.ndarray) -> tuple[int, int, int]:
    return tuple(np.rint(vertex * 1_000_000).astype(np.int64))


def inspect(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"{path} is too short to be a binary STL")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    expected_size = 84 + triangle_count * 50
    if len(data) != expected_size:
        raise ValueError(f"{path} has {len(data)} bytes, expected {expected_size}")

    vertices: list[np.ndarray] = []
    edges: Counter[tuple[tuple[int, int, int], tuple[int, int, int]]] = Counter()
    directed_edges: Counter[
        tuple[tuple[int, int, int], tuple[int, int, int]]
    ] = Counter()
    degenerate_triangles = 0
    signed_volume = 0.0

    for index in range(triangle_count):
        offset = 84 + index * 50 + 12
        triangle = np.array(struct.unpack_from("<9f", data, offset), dtype=float).reshape(3, 3)
        vertices.extend(triangle)
        cross = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        if np.linalg.norm(cross) <= 1e-9:
            degenerate_triangles += 1
        signed_volume += float(np.dot(triangle[0], np.cross(triangle[1], triangle[2]))) / 6

        keys = [quantized(vertex) for vertex in triangle]
        for start, end in zip(keys, keys[1:] + keys[:1]):
            edges[tuple(sorted((start, end)))] += 1
            directed_edges[(start, end)] += 1

    boundary_edges = sum(count == 1 for count in edges.values())
    non_manifold_edges = sum(count > 2 for count in edges.values())
    orientation_errors = sum(
        count != 1 or directed_edges[(end, start)] != 1
        for (start, end), count in directed_edges.items()
    )
    points = np.array(vertices)
    bounds = points.max(axis=0) - points.min(axis=0)

    result = {
        "file": str(path.relative_to(HERE)),
        "triangles": triangle_count,
        "degenerate_triangles": degenerate_triangles,
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "orientation_errors": orientation_errors,
        "signed_volume_mm3": signed_volume,
        "bbox_mm": bounds.tolist(),
    }
    if any(
        result[key]
        for key in (
            "degenerate_triangles",
            "boundary_edges",
            "non_manifold_edges",
            "orientation_errors",
        )
    ) or signed_volume <= 0:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    results = [inspect(path) for path in sorted((HERE / "generated").glob("*.stl"))]
    print(json.dumps(results, indent=2))
