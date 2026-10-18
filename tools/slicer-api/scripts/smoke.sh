#!/usr/bin/env bash
# Integration smoke test: slice one STL for each printer through the gateway.
# Usage: scripts/smoke.sh [STL_PATH] [OUT_DIR]
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8080}"
STL="${1:-/d/OtherProjects/roBa-case/case/v3/freecad/trackball_bearing/generated/print/fit_coupon_print.stl}"
OUT="${2:-$(dirname "$0")/../smoke-out}"
mkdir -p "$OUT"

# Python on Windows prints CRLF; strip CRs so values compare cleanly.
jget() { python -c "import sys,json; print(json.load(sys.stdin)$1)" | tr -d '\r'; }

echo "== health"
curl -fsS "$BASE/health"; echo

fail=0
for printer in ad4 ad5mpro; do
  echo "== $printer: submit $(basename "$STL")"
  resp=$(curl -fsS -F "file=@$STL" -F "printer=$printer" "$BASE/jobs")
  job_id=$(echo "$resp" | jget '["job_id"]')
  echo "job_id=$job_id"

  while :; do
    job=$(curl -fsS "$BASE/jobs/$job_id")
    status=$(echo "$job" | jget '["status"]')
    case "$status" in queued|running) sleep 2 ;; *) break ;; esac
  done
  echo "$job" > "$OUT/$printer.job.json"
  echo "status=$status"

  if [ "$status" != "succeeded" ]; then
    echo "error: $(echo "$job" | jget '.get("error")')"
    fail=1
    continue
  fi
  passed=$(echo "$job" | jget '["validation"]["passed"]')
  echo "validation.passed=$passed"
  [ "$passed" = "True" ] || fail=1

  # One line per file: url, name, sha256 (tab-separated, no spaces in any field).
  listing=$(echo "$job" | python -c '
import sys, json
for f in json.load(sys.stdin)["files"]:
    print("\t".join([f["url"], f["name"], f["sha256"]]))
' | tr -d '\r')
  while IFS=$'\t' read -r url name sha; do
    [ -n "$url" ] || continue
    curl -fsS -o "$OUT/$printer-$name" "$BASE$url"
    got=$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$OUT/$printer-$name" | tr -d '\r')
    if [ "$got" = "$sha" ]; then
      echo "downloaded $name sha256 OK"
    else
      echo "sha256 MISMATCH $name"
      fail=1
    fi
  done <<< "$listing"
done

if [ "$fail" -ne 0 ]; then
  echo "SMOKE FAILED"
  exit 1
fi
echo "SMOKE PASSED (outputs in $OUT)"
