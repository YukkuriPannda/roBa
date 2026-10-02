import hashlib
import json
import pathlib
import sys
import FreeCAD as App

root = pathlib.Path(sys.argv[1])
scratch = pathlib.Path(__file__).parent / 'custom-check'
scratch.mkdir(exist_ok=True)
sys.path.insert(0, str(root / 'case/v3/freecad'))
import roba_freecad as r
r.GENERATED_DIR = scratch / 'generated'
doc = App.openDocument(str(root / 'case/v3/freecad/generated/roba_v3_folding_tenting.FCStd'))
doc.saveAs(str(scratch / 'custom.FCStd'))
p = doc.getObject('TentingParameters')
before = doc.getObject('FoldingStand').Shape.Volume
p.StandLength = 21
doc.recompute()
assert doc.getObject('FoldingStand').Shape.Volume > before
record = r.export_current_document(doc)
assert not record['geometry']['legacy_default_regression_applied']
assert record['native_document_sha256'] == hashlib.sha256(pathlib.Path(doc.FileName).read_bytes()).hexdigest()
export_path = r.GENERATED_DIR / 'folding_tenting_stand.stp'
accepted_hash = hashlib.sha256(export_path.read_bytes()).hexdigest()
p.PinRadius = 2
doc.recompute()
try:
    r.export_current_document(doc)
except (ValueError, RuntimeError):
    pass
else:
    raise AssertionError('invalid axle/bore relationship was exported')
assert hashlib.sha256(export_path.read_bytes()).hexdigest() == accepted_hash
assert json.loads((r.GENERATED_DIR / 'latest_run_status.json').read_text())['status'] == 'FAIL'
saved_path = doc.FileName
App.closeDocument(doc.Name)
reopened = App.openDocument(saved_path)
assert float(reopened.getObject('TentingParameters').StandLength.Value) == 21
assert float(reopened.getObject('TentingParameters').PinRadius.Value) == 1.5
serialized = json.dumps({'custom_dimension_export': 'PASS', 'invalid_dimensions_rejected': 'PASS',
                         'previous_outputs_preserved': 'PASS', 'saved_native_hash_matches': 'PASS'}, indent=2)
if len(sys.argv) > 2:
    pathlib.Path(sys.argv[2]).write_text(serialized+'\n', encoding='utf-8')
print(serialized)
