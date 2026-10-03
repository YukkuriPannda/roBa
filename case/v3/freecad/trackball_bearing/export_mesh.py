"""Export a BRep as a locally repaired, round-trip-verified STL.

All geometry is in millimetres. The mesh starts from the unchanged BRep
tessellation at the repository's 0.08 mm deflection. Repairs only collapse
short shared edges adjacent to reported self-intersections; no global remesh,
surface smoothing, BRep Boolean, or whole-case reconstruction is performed.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import tempfile

import FreeCAD as App
import Mesh
import numpy as np
from scipy.spatial import cKDTree


_TESSELLATION_DEFLECTION_MM = 0.08
_MAX_COLLAPSE_EDGE_MM = 1.00
_MAX_REPAIR_STEPS = 50
_ZONE_MIN = np.array([-10.0, -15.0, 1.9], dtype=float)
_ZONE_MAX = np.array([25.0, 15.0, 5.9], dtype=float)
_ZONE_MAX_DEVIATION_MM = 0.01


def _mesh_data(mesh):
    points, faces = mesh.Topology
    xyz = np.asarray([[point.x, point.y, point.z] for point in points], dtype=float)
    face_ids = np.asarray(faces, dtype=np.int64)
    triangles = xyz[face_ids]
    return xyz, face_ids, triangles


def _mesh_status(mesh):
    intersections = mesh.getSelfIntersections()
    return {
        "facets": int(mesh.CountFacets),
        "components": int(mesh.countComponents()),
        "closed": bool(mesh.isSolid()),
        "non_manifold": bool(mesh.hasNonManifolds()),
        "self_intersections": int(len(intersections)),
    }, intersections


def _aabb_intersects_zone(triangle):
    low = triangle.min(axis=0)
    high = triangle.max(axis=0)
    return bool(np.all(high >= _ZONE_MIN) and np.all(low <= _ZONE_MAX))


def _candidate_edges(mesh, intersections):
    """Return short, local collapses ordered by edge length.

    The full 1-ring around both edge endpoints is excluded if any of its
    triangles touches the protected lower mounting/sensor box. This keeps a
    collapse from moving a shared vertex that also belongs to that region.
    """
    points, faces, triangles = _mesh_data(mesh)
    edge_faces = {}
    vertex_faces = [[] for _ in range(len(points))]
    for face_index, face in enumerate(faces):
        ids = [int(value) for value in face]
        for vertex_id in ids:
            vertex_faces[vertex_id].append(face_index)
        for index in range(3):
            edge = tuple(sorted((ids[index], ids[(index + 1) % 3])))
            edge_faces.setdefault(edge, []).append(face_index)

    bad_faces = {int(face_index) for row in intersections for face_index in row[:2]}
    candidates = {}
    for face_index in bad_faces:
        face = faces[face_index]
        ids = [int(value) for value in face]
        for index in range(3):
            edge = tuple(sorted((ids[index], ids[(index + 1) % 3])))
            adjacent = edge_faces.get(edge, [])
            if len(adjacent) != 2 or adjacent[0] == adjacent[1]:
                continue
            length = float(np.linalg.norm(points[edge[0]] - points[edge[1]]))
            if length > _MAX_COLLAPSE_EDGE_MM:
                continue

            # collapseEdge affects the edge endpoints and their incident
            # triangle rings. Record whether the ring touches the protected
            # zone so those candidates are attempted only after every safer
            # candidate and are checked against the 0.01 mm zone bound.
            affected_faces = set(vertex_faces[edge[0]]) | set(vertex_faces[edge[1]])
            touches_zone = any(_aabb_intersects_zone(triangles[face_id]) for face_id in affected_faces)

            adjacent_pair = tuple(sorted(map(int, adjacent)))
            candidates[edge] = (length, touches_zone, adjacent_pair)

    return sorted(
        ((length, touches_zone, adjacent, edge)
         for edge, (length, touches_zone, adjacent) in candidates.items()),
        key=lambda item: (item[1], item[0], item[2], item[3]),
    )


def _write_reload(mesh, path):
    path = Path(path)
    path.unlink(missing_ok=True)
    mesh.write(str(path))
    return Mesh.Mesh(str(path))


def _collapse_until_clean(mesh, raw_mesh, work_path, initial_path):
    status, intersections = _mesh_status(mesh)
    operations = []
    round_trip_path = Path(initial_path)
    if not status["closed"] or status["non_manifold"] or status["components"] != 1:
        raise RuntimeError("initial STL round-trip is not one closed manifold component")

    for step in range(_MAX_REPAIR_STEPS):
        if status["self_intersections"] == 0:
            return mesh, operations, status, round_trip_path

        before_count = status["self_intersections"]
        candidates = _candidate_edges(mesh, intersections)
        accepted = None
        for edge_length, touches_zone, adjacent, edge in candidates:
            trial = Mesh.Mesh(mesh)
            try:
                trial.collapseEdge(*adjacent)
            except Exception:
                continue

            # Avoid serializing candidates that do not improve even before
            # STL float32 rounding. The accepted candidate is always checked
            # again after a save/reload, where rounding can restore flags.
            trial_intersections = trial.getSelfIntersections()
            if len(trial_intersections) >= before_count:
                continue
            if not trial.isSolid() or trial.hasNonManifolds() or trial.countComponents() != 1:
                continue

            reloaded = _write_reload(trial, work_path)
            reloaded_status, reloaded_intersections = _mesh_status(reloaded)
            if (
                reloaded_status["closed"]
                and not reloaded_status["non_manifold"]
                and reloaded_status["components"] == 1
                and reloaded_status["self_intersections"] < before_count
            ):
                zone_deviation = None
                if touches_zone:
                    zone_deviation = _bidirectional_deviation(raw_mesh, reloaded, zone_only=True)
                    if zone_deviation["max_distance_upper_bound_mm"] > _ZONE_MAX_DEVIATION_MM:
                        continue
                accepted = (
                    reloaded,
                    reloaded_status,
                    reloaded_intersections,
                    edge_length,
                    touches_zone,
                    zone_deviation,
                    adjacent,
                    edge,
                )
                break

        if accepted is None:
            raise RuntimeError(
                "no protected-zone-safe shared edge collapse reduced the "
                f"{before_count} self-intersections after STL round-trip"
            )

        mesh, status, intersections, edge_length, touches_zone, zone_deviation, adjacent, edge = accepted
        round_trip_path = Path(work_path)
        operations.append(
            {
                "step": int(step + 1),
                "edge_length_mm": float(edge_length),
                "edge_neighborhood_touches_protected_zone": bool(touches_zone),
                "edge_vertex_indices_before_collapse": [int(edge[0]), int(edge[1])],
                "adjacent_facets_before_collapse": [int(adjacent[0]), int(adjacent[1])],
                "intersections_before": int(before_count),
                "intersections_after_stl_round_trip": int(status["self_intersections"]),
                "facets_after_stl_round_trip": int(status["facets"]),
                "protected_zone_deviation_after_step_upper_bound_mm": (
                    None if zone_deviation is None else float(zone_deviation["max_distance_upper_bound_mm"])
                ),
            }
        )

    if status["self_intersections"]:
        raise RuntimeError(
            f"self-intersections remain after the fixed {_MAX_REPAIR_STEPS}-step repair bound"
        )
    return mesh, operations, status


def _point_to_triangles(point, triangles):
    """Exact Euclidean distances from one point to a batch of triangles."""
    a = triangles[:, 0]
    b = triangles[:, 1]
    c = triangles[:, 2]
    ab = b - a
    ac = c - a
    ap = point - a
    d00 = np.einsum("ij,ij->i", ab, ab)
    d11 = np.einsum("ij,ij->i", ac, ac)
    d01 = np.einsum("ij,ij->i", ab, ac)
    d20 = np.einsum("ij,ij->i", ap, ab)
    d21 = np.einsum("ij,ij->i", ap, ac)
    denominator = d00 * d11 - d01 * d01
    good = denominator > 1e-24
    safe_denominator = np.where(good, denominator, 1.0)
    u = (d11 * d20 - d01 * d21) / safe_denominator
    v = (d00 * d21 - d01 * d20) / safe_denominator
    projection = a + u[:, None] * ab + v[:, None] * ac
    plane = np.linalg.norm(point - projection, axis=1)

    edge_distances = []
    for start, end in ((a, b), (b, c), (c, a)):
        direction = end - start
        length_sq = np.einsum("ij,ij->i", direction, direction)
        scale = np.clip(
            np.einsum("ij,ij->i", point - start, direction)
            / np.where(length_sq > 0, length_sq, 1.0),
            0.0,
            1.0,
        )
        edge_distances.append(np.linalg.norm(point - start - scale[:, None] * direction, axis=1))
    boundary = np.minimum.reduce(edge_distances)
    inside = good & (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1.0 + 1e-10)
    return np.where(inside, plane, boundary)


def _surface_samples(triangles, zone_only=False):
    selected = triangles
    if zone_only:
        low = triangles.min(axis=1)
        high = triangles.max(axis=1)
        relevant = np.all(high >= _ZONE_MIN, axis=1) & np.all(low <= _ZONE_MAX, axis=1)
        selected = triangles[relevant]
    if not len(selected):
        return np.empty((0, 3), dtype=float)
    vertices_and_centroids = np.concatenate(
        (selected.reshape(-1, 3), selected.mean(axis=1)), axis=0
    )
    return np.unique(vertices_and_centroids, axis=0)


def _directed_sample_distance(source_samples, target_triangles, shortcut_bound_mm):
    """Return a conservative upper bound for all sampled point-to-surface distances.

    A target vertex or triangle centroid is itself on the target surface, so a
    sample within shortcut_bound_mm of one has a proven surface-distance upper
    bound. Remaining samples use exact point-to-triangle distances over a
    centroid-tree candidate set whose radius is guaranteed to include the
    closest target triangle.
    """
    if not len(source_samples):
        return {"sample_count": 0, "max_distance_upper_bound_mm": 0.0, "exact_triangle_queries": 0}
    if not len(target_triangles):
        return {"sample_count": int(len(source_samples)), "max_distance_upper_bound_mm": math.inf, "exact_triangle_queries": 0}

    target_vertices = np.unique(target_triangles.reshape(-1, 3), axis=0)
    target_centroids = target_triangles.mean(axis=1)
    target_samples = np.concatenate((target_vertices, target_centroids), axis=0)
    sample_tree = cKDTree(target_samples)
    shortcut_distances, _ = sample_tree.query(source_samples, k=1)
    shortcut = shortcut_distances <= shortcut_bound_mm
    maximum = float(shortcut_distances[shortcut].max()) if np.any(shortcut) else 0.0
    unresolved = source_samples[~shortcut]
    if not len(unresolved):
        return {
            "sample_count": int(len(source_samples)),
            "max_distance_upper_bound_mm": maximum,
            "exact_triangle_queries": 0,
        }

    vertex_tree = cKDTree(target_vertices)
    centroid_tree = cKDTree(target_centroids)
    centroid_radius = float(
        np.linalg.norm(target_triangles - target_centroids[:, None, :], axis=2).max()
    )
    upper_bounds, _ = vertex_tree.query(unresolved, k=1)
    radii = upper_bounds + centroid_radius + 1e-10
    candidate_lists = centroid_tree.query_ball_point(unresolved, radii)
    exact_queries = 0
    for point, upper_bound, candidate_ids in zip(unresolved, upper_bounds, candidate_lists):
        if not candidate_ids:
            # The nearest target vertex belongs to at least one target facet;
            # its centroid must be within the radius above. Treat a broken
            # spatial-index bound as a hard failure rather than understating it.
            raise RuntimeError("surface-distance spatial index produced no candidate triangle")
        distances = _point_to_triangles(point, target_triangles[np.asarray(candidate_ids, dtype=np.int64)])
        exact_distance = float(distances.min())
        if exact_distance > float(upper_bound) + 1e-8:
            raise RuntimeError("computed triangle distance exceeded the known vertex upper bound")
        maximum = max(maximum, exact_distance)
        exact_queries += 1

    return {
        "sample_count": int(len(source_samples)),
        "max_distance_upper_bound_mm": float(maximum),
        "exact_triangle_queries": int(exact_queries),
    }


def _bidirectional_deviation(source_mesh, target_mesh, zone_only=False):
    _, _, source_triangles = _mesh_data(source_mesh)
    _, _, target_triangles = _mesh_data(target_mesh)
    source_samples = _surface_samples(source_triangles, zone_only=zone_only)
    target_samples = _surface_samples(target_triangles, zone_only=zone_only)
    shortcut_bound = 1e-5
    forward = _directed_sample_distance(source_samples, target_triangles, shortcut_bound)
    reverse = _directed_sample_distance(target_samples, source_triangles, shortcut_bound)
    return {
        "raw_shape_to_final_mesh": forward,
        "final_mesh_to_raw_shape": reverse,
        "max_distance_upper_bound_mm": float(
            max(forward["max_distance_upper_bound_mm"], reverse["max_distance_upper_bound_mm"])
        ),
        "source_samples_are_vertices_and_face_centroids": True,
        "protected_zone_samples_include_triangles_whose_bounds_touch_zone": bool(zone_only),
        "shortcut_surface_upper_bound_mm": float(shortcut_bound),
    }


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_verified_stl(shape, output_path, max_surface_deviation=0.08):
    """Export a verified STL and return JSON-serializable geometry evidence.

    Args:
        shape: A valid FreeCAD BRep containing exactly one solid.
        output_path: Destination for the derived STL; the source shape is never
            modified.
        max_surface_deviation: Maximum allowed bidirectional sampled surface
            distance from the raw 0.08 mm shape triangulation, in mm.

    Raises:
        ValueError: For an invalid shape, path, or limit.
        RuntimeError: If bounded local cleanup, STL round-trip checks, or
            geometry-deviation checks fail.
    """
    limit = float(max_surface_deviation)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("max_surface_deviation must be a positive finite millimetre value")
    if shape is None or shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
        raise ValueError("input BRep must be valid and contain exactly one solid")

    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".stl":
        raise ValueError("output_path must end in .stl")
    output.parent.mkdir(parents=True, exist_ok=True)

    raw_mesh = Mesh.Mesh(shape.tessellate(_TESSELLATION_DEFLECTION_MM))
    if raw_mesh.CountFacets <= 0:
        raise RuntimeError("BRep tessellation produced no facets")

    # Keep trial and final files in the destination directory so the final
    # publish is an atomic replace on the same volume. Temporary files are
    # always removed when the call returns or raises.
    created_paths = []
    def temporary_path(prefix):
        descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".stl", dir=str(output.parent))
        os.close(descriptor)
        path = Path(name)
        created_paths.append(path)
        path.unlink(missing_ok=True)
        return path

    initial_path = temporary_path(".mesh-export-initial-")
    trial_path = temporary_path(".mesh-export-trial-")
    final_path = temporary_path(".mesh-export-final-")
    try:
        initial_mesh = _write_reload(raw_mesh, initial_path)
        first_round_trip_status, _ = _mesh_status(initial_mesh)
        if not first_round_trip_status["closed"] or first_round_trip_status["non_manifold"] or first_round_trip_status["components"] != 1:
            raise RuntimeError("initial STL save/reload is not one closed manifold component")
        # Apply one more identical STL serialization cycle before editing. This
        # settles float32 coordinate rounding; the exact bytes then used as the
        # repair baseline must themselves be closed and manifold.
        repair_input_mesh = _write_reload(initial_mesh, trial_path)
        initial_status, _ = _mesh_status(repair_input_mesh)
        if not initial_status["closed"] or initial_status["non_manifold"] or initial_status["components"] != 1:
            raise RuntimeError("second STL save/reload is not one closed manifold component")

        mesh, operations, final_status, accepted_round_trip_path = _collapse_until_clean(repair_input_mesh, raw_mesh, trial_path, trial_path)
        # Publish the exact STL bytes which already passed a save/reload check.
        # Re-serializing the same in-memory mesh can accumulate float32 rounding
        # and reintroduce a self-intersection at one nearly coincident edge.
        shutil.copyfile(accepted_round_trip_path, final_path)
        final_mesh = Mesh.Mesh(str(final_path))
        final_status, _ = _mesh_status(final_mesh)
        if (
            not final_status["closed"]
            or final_status["non_manifold"]
            or final_status["self_intersections"] != 0
            or final_status["components"] != 1
        ):
            raise RuntimeError("final STL save/reload failed clean single-component mesh checks: " + json.dumps(final_status))

        deviation = _bidirectional_deviation(raw_mesh, final_mesh)
        zone_deviation = _bidirectional_deviation(raw_mesh, final_mesh, zone_only=True)
        if deviation["max_distance_upper_bound_mm"] > limit:
            raise RuntimeError(
                "final STL sampled surface deviation exceeds the fixed limit: "
                f"{deviation['max_distance_upper_bound_mm']:.9f} mm > {limit:.9f} mm"
            )
        if zone_deviation["max_distance_upper_bound_mm"] > _ZONE_MAX_DEVIATION_MM:
            raise RuntimeError(
                "protected lower-zone sampled surface deviation exceeds "
                f"{_ZONE_MAX_DEVIATION_MM:.9f} mm: "
                f"{zone_deviation['max_distance_upper_bound_mm']:.9f} mm"
            )

        os.replace(str(final_path), str(output))
        # Verify the actual published bytes, not only the temporary candidate.
        published_mesh = Mesh.Mesh(str(output))
        published_status, _ = _mesh_status(published_mesh)
        if (
            not published_status["closed"]
            or published_status["non_manifold"]
            or published_status["self_intersections"] != 0
            or published_status["components"] != 1
        ):
            output.unlink(missing_ok=True)
            raise RuntimeError("published STL failed its save/reload integrity check")

        raw_shape_volume = float(raw_mesh.Volume)
        final_mesh_volume = float(published_mesh.Volume)
        return {
            "status": "PASS",
            "units": "mm",
            "output_path": str(output),
            "output_sha256": _sha256(output),
            "input_brep": {
                "valid": bool(shape.isValid()),
                "solid_count": int(len(shape.Solids)),
                "volume_mm3": float(shape.Volume),
            },
            "raw_shape_triangulation": {
                "deflection_mm": float(_TESSELLATION_DEFLECTION_MM),
                "facets": int(raw_mesh.CountFacets),
                "volume_mm3": raw_shape_volume,
            },
            "initial_stl_round_trip": first_round_trip_status,
            "repair_input_second_stl_round_trip": initial_status,
            "final_stl_round_trip": published_status,
            "repair_policy": {
                "method": "collapse only short shared edges adjacent to reported self-intersection facets",
                "max_edge_length_mm": float(_MAX_COLLAPSE_EDGE_MM),
                "max_steps": int(_MAX_REPAIR_STEPS),
                "protected_zone_mm": {
                    "x": [float(_ZONE_MIN[0]), float(_ZONE_MAX[0])],
                    "y": [float(_ZONE_MIN[1]), float(_ZONE_MAX[1])],
                    "z": [float(_ZONE_MIN[2]), float(_ZONE_MAX[2])],
                },
                "operations": operations,
            },
            "geometry_deviation": {
                "max_allowed_mm": limit,
                "raw_to_final_bidirectional_sampled_distance": deviation,
                "protected_zone_max_allowed_mm": float(_ZONE_MAX_DEVIATION_MM),
                "protected_zone_bidirectional_sampled_distance": zone_deviation,
            },
            "mesh_volume_delta_mm3": float(final_mesh_volume - raw_shape_volume),
        }
    finally:
        for path in created_paths:
            path.unlink(missing_ok=True)



