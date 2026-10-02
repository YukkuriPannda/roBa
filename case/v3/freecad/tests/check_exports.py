"""Independent acceptance: exported defaults match inherited geometry."""
import hashlib
import json
import pathlib
import sys
import FreeCAD as App
import Part
import Mesh
from collections import Counter

root = pathlib.Path(sys.argv[1])
generated = root / 'case/v3/freecad/generated'
legacy = root / 'case/v3/tenting/output'
results = {}
sys.path.insert(0, str(root / 'case/v3/freecad'))
import roba_freecad
native_document = App.openDocument(str(generated / 'roba_v3_folding_tenting.FCStd'))
for name in ('folding_tenting_stand', 'bottom_L_tenting', 'bottom_R_tenting'):
    output = generated / (name + '.stp')
    if not output.exists():
        output = generated / (name + '.step')
    actual = Part.read(str(output))
    expected = Part.read(str(legacy / (name + '.stp')))
    object_name = 'FoldingStand' if name == 'folding_tenting_stand' else 'Bottom'+name.split('_')[1]+'Tenting'
    native = native_document.getObject(object_name).Shape
    assert actual.isValid() and len(actual.Solids) == 1, name
    historical = json.loads((legacy / (name+'.verified.json')).read_text())['result']['volume']
    delta = abs(native.Volume - historical)
    assert delta < 0.1, (name, delta)
    legacy_step_delta = abs(native.Volume - expected.Volume)
    assert legacy_step_delta < max(.05,native.Volume*.0002), (name, legacy_step_delta)
    roundtrip_volume_delta = abs(actual.Volume-native.Volume)
    assert roundtrip_volume_delta < max(.05, native.Volume*.0002), (name, roundtrip_volume_delta)
    actual_bounds = actual.optimalBoundingBox(False, False)
    expected_bounds = expected.optimalBoundingBox(False, False)
    for dimension in ('XLength', 'YLength', 'ZLength'):
        assert abs(getattr(actual_bounds, dimension)-getattr(expected_bounds, dimension)) < 0.02, (name, dimension)
    if name.startswith('bottom_'):
        source = root / 'case/v3' / ('bottom_' + name.split('_')[1] + '.stp')
        original = Part.read(str(source))
        assert original.cut(native).Volume < 1e-5, name
    samples = native.Vertexes[::max(1, len(native.Vertexes)//24)]
    max_surface_distance = max(actual.distToShape(Part.Vertex(v.Point))[0] for v in samples)
    assert max_surface_distance < .005, (name, max_surface_distance)
    legacy_distances = []
    for source_shape, target_shape in ((native, expected), (expected, native)):
        points, facets = source_shape.tessellate(.1)
        legacy_distances.extend(target_shape.distToShape(Part.Vertex(p))[0]
                                for p in points[::max(1,len(points)//80)])
    legacy_distance = max(legacy_distances)
    assert legacy_distance < .005, (name, legacy_distance)
    results[name] = {'valid': True, 'solid_count': 1,
                     'volume_mm3': actual.Volume,
                     'legacy_volume_difference_mm3': delta,
                     'legacy_step_volume_difference_mm3': legacy_step_delta,
                     'legacy_bidirectional_sampled_distance_mm': legacy_distance,
                     'step_roundtrip_volume_difference_mm3': roundtrip_volume_delta,
                     'sampled_vertex_surface_distance_mm': max_surface_distance,
                     'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    mesh = Mesh.Mesh(str(generated / (name + '.stl')))
    vertices, facets = mesh.Topology
    edge_count, edge_direction = Counter(), Counter()
    degenerate = 0
    for a, b, c in facets:
        if len({a, b, c}) < 3 or (vertices[b]-vertices[a]).cross(vertices[c]-vertices[a]).Length < 1e-10:
            degenerate += 1
        for u, v in ((a, b), (b, c), (c, a)):
            edge = tuple(sorted((u, v)))
            edge_count[edge] += 1
            edge_direction[edge] += 1 if u < v else -1
    assert degenerate == 0, (name, 'degenerate', degenerate)
    assert all(n == 2 for n in edge_count.values()), (name, 'nonmanifold or open')
    assert all(n == 0 for n in edge_direction.values()), (name, 'orientation')
    assert mesh.Volume > 0, (name, 'negative mesh volume')
    results[name]['mesh'] = {'facets': len(facets), 'closed': True,
                            'manifold_edges': True, 'consistent_orientation': True}
serialized = json.dumps(results, indent=2)
if len(sys.argv) > 2:
    pathlib.Path(sys.argv[2]).write_text(serialized+'\n', encoding='utf-8')
print(serialized)
