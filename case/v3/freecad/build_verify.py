"""Run the native FreeCAD model build, fresh-process edit, and export checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR))

from roba_freecad import (  # noqa: E402
    build_verify_command,
    _run_phase,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("build", "mutate", "finalize"))
    parser.add_argument("--fcstd", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.phase:
        if not args.fcstd or not args.stage or not args.evidence:
            parser.error("--phase requires --fcstd, --stage, and --evidence")
        _run_phase(args.phase, args.fcstd, args.stage, args.evidence)
        return 0
    build_verify_command()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
