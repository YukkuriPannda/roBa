#!/usr/bin/env python3
"""Build the CAD visual report HTML from a report.json (stdlib only).

Usage (from repo root): python -I .claude/skills/cad-visual-report/make_report.py solidcraft/<part>/report.json
Paths inside report.json are relative to the repo root (3 levels above this file).
"""
import base64
import datetime
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CLI = (
    r"C:\Users\Pannda\AppData\Local\Programs\SolidCraft"
    r"\solidcraft-0.13.1-windows-x64-portable\solidcraft-cli.exe"
)
FALLBACK_VERSION = "0.13.1"
VIEWS = ("iso", "front", "top")
HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
TEMPLATE = HERE / "template.html"


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=None):
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def fmt_num(value, digits=3):
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def fmt_volume(value):
    text = f"{value:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def esc(value):
    return html.escape(str(value), quote=True)


def image_data_uri(path):
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def git_branch():
    try:
        result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO)
        branch = result.stdout.strip()
        if result.returncode == 0 and branch:
            return branch
    except OSError:
        pass
    return "unknown"


def cli_version(cli):
    try:
        result = run([cli, "--version"], cwd=REPO)
    except OSError:
        return FALLBACK_VERSION
    if result.returncode != 0:
        return FALLBACK_VERSION
    match = re.search(r"\d+\.\d+\.\d+", result.stdout + result.stderr)
    return match.group(0) if match else FALLBACK_VERSION


def take_snapshots(cli, script, generated):
    views_dir = generated / "views"
    views_dir.mkdir(parents=True, exist_ok=True)
    for view in VIEWS:
        out = views_dir / f"{view}.png"
        cmd = [
            cli, "snapshot", script,
            "--out", str(out), "--view", view,
            "--width", "900", "--height", "675", "--no-grid",
        ]
        try:
            result = run(cmd, cwd=REPO)
        except OSError as exc:
            fail(f"cannot run SolidCraft CLI '{cli}': {exc}")
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
            fail(f"snapshot failed for view '{view}' (exit {result.returncode})")


def dimension_rows(eval_data, expected, labels, tolerance):
    rows = []
    for body in eval_data.get("bodies", []):
        name = body["name"]
        lo, hi = body["bbox"]["min"], body["bbox"]["max"]
        size = [round(hi[i] - lo[i], 3) for i in range(3)]
        size_text = " × ".join(fmt_num(v) for v in size)
        label = labels.get(name, name)
        exp = expected.get(name)
        if exp is None:
            expected_text = "—"
            verdict = '<span class="pill hold">期待値なし</span>'
        else:
            expected_text = " × ".join(fmt_num(v) for v in exp)
            matched = len(exp) == 3 and all(
                abs(size[i] - exp[i]) <= tolerance for i in range(3)
            )
            if matched:
                verdict = '<span class="pill ok">一致</span>'
            else:
                verdict = '<span class="pill hold">不一致</span>'
                print(
                    f"warning: {name} size {size_text} differs from expected {expected_text}"
                    f" (tolerance {tolerance} mm)",
                    file=sys.stderr,
                )
        volume = body.get("volume_mm3")
        volume_text = fmt_volume(volume) if isinstance(volume, (int, float)) else "—"
        rows.append(
            f"    <tr><td>{esc(label)}</td><td class=\"n\">{esc(expected_text)}</td>"
            f"<td class=\"n\">{esc(size_text)}</td><td class=\"n\">{esc(volume_text)}</td>"
            f"<td>{verdict}</td></tr>"
        )
    return "\n".join(rows)


def param_rows(eval_data):
    rows = []
    for param in eval_data.get("params", []):
        value = param.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value_text = fmt_num(value, 4)
        else:
            value_text = str(value)
        unit = param.get("unit") or ""
        if unit:
            value_text = f"{value_text} {unit}"
        comment = param.get("comment") or "—"
        rows.append(
            f"    <tr><td><code>{esc(param.get('name', ''))}</code></td>"
            f"<td class=\"n\">{esc(value_text)}</td><td>{esc(comment)}</td></tr>"
        )
    return "\n".join(rows)


def check_items(checks):
    items = []
    for check in checks:
        if check.get("status") == "done":
            pill = '<span class="pill ok">済</span>'
        else:
            pill = '<span class="pill hold">未</span>'
        items.append(f"    <li>{pill}{esc(check.get('text', ''))}</li>")
    return "\n".join(items)


def file_rows(files):
    rows = []
    for item in files:
        rows.append(
            f"    <tr><td><code>{esc(item.get('path', ''))}</code></td>"
            f"<td>{esc(item.get('note', ''))}</td></tr>"
        )
    return "\n".join(rows)


def main():
    if len(sys.argv) != 2:
        fail("usage: make_report.py <report.json>")

    report_path = Path(sys.argv[1])
    if not report_path.is_absolute():
        report_path = REPO / report_path
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read report '{report_path}': {exc}")

    cli = os.environ.get("SOLIDCRAFT_CLI", DEFAULT_CLI)
    script = report["script"]
    eval_path = REPO / report["eval"]
    generated = eval_path.parent
    expected = report.get("expected", {})
    labels = report.get("labels", {})
    tolerance = float(report.get("tolerance_mm", 0.01))

    take_snapshots(cli, script, generated)

    try:
        eval_data = json.loads(eval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read eval JSON '{eval_path}': {exc}")

    today = datetime.date.today().isoformat()
    eyebrow = f"roBa-case · {git_branch()} · SolidCraft {cli_version(cli)} · {today}"

    template = TEMPLATE.read_text(encoding="utf-8")
    values = {
        "title": esc(report["title"]),
        "eyebrow": esc(eyebrow),
        "summary": esc(report.get("summary", "")),
        "iso_src": image_data_uri(generated / "views" / "iso.png"),
        "front_src": image_data_uri(generated / "views" / "front.png"),
        "top_src": image_data_uri(generated / "views" / "top.png"),
        "dimension_rows": dimension_rows(eval_data, expected, labels, tolerance),
        "param_rows": param_rows(eval_data),
        "check_items": check_items(report.get("checks", [])),
        "file_rows": file_rows(report.get("files", [])),
    }

    def substitute(match):
        key = match.group(1)
        if key not in values:
            fail(f"template placeholder '{{{{{key}}}}}' has no value")
        return values[key]

    page = re.sub(r"\{\{(\w+)\}\}", substitute, template)

    out_path = generated / "report.html"
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(page)
    print(out_path)


if __name__ == "__main__":
    main()
