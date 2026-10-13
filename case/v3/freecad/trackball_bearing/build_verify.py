"""Stage each run; publish generated artifacts only after checks pass."""
import os,sys,json,subprocess,shutil
from datetime import datetime
from pathlib import Path
H=Path(__file__).resolve().parent
stamp=datetime.now().strftime('%Y%m%d-%H%M%S');stage=H/'runs'/stamp;stage.mkdir(parents=True)
env=os.environ.copy();env['ROBA_BEARING_OUTPUT']=str(stage)
status={'status':'RUNNING','run_directory':str(stage)}
def save_status(): (H/'latest_run_status.json').write_text(json.dumps(status,indent=2))
save_status()
try:
 for name in ('source.brep','source.sha256'):
  if (H/'generated'/name).exists():shutil.copy2(H/'generated'/name,stage/name)
 for script in ('repair_source.py','bearing_case.py','export_case_mesh.py','verify_case.py','render_case.py','render_six_view.py','export_print.py','publish_verified.py'):
  with (stage/(script+'.stdout.txt')).open('w',encoding='utf-8') as log:
   result=subprocess.run([sys.executable,str(H/script)],env=env,stdout=log,stderr=subprocess.STDOUT)
  if result.returncode:raise RuntimeError(script+' failed; inspect its run log')
  if script=='repair_source.py':
   for evidence in ('repair.json','repaired_source.bms'):
    shutil.copy2(H/'inspect'/'logs'/evidence,stage/evidence)
 status['status']='CAD_CHECKS_PASS_PHYSICAL_UNVERIFIED';save_status();print(json.dumps(status))
except Exception as exc:
 status.update(status='FAIL_NOT_PRINT_READY',error=str(exc));save_status();print(json.dumps(status));raise SystemExit(1)
