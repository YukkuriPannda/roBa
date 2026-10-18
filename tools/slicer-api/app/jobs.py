"""Job persistence, background worker queue, and the slice pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .gx import write_gx
from .orca_client import OrcaClient, OrcaError
from .presets import PRINTERS, PrinterSpec, default_profile_bytes
from .validate import (ValidationError, gcode_info, validate_3mf, validate_gcode,
                       validate_gx)

log = logging.getLogger("slicer-api")

TERMINAL = ("succeeded", "failed")
CONTENT_TYPES = {"gcode": "text/plain", "gx": "application/octet-stream",
                 "3mf": "model/3mf"}
EXTENSION = {"gcode": ".gcode", "gx": ".gx", "3mf": ".3mf"}
ORPHAN_AGE_SECS = 3600.0
MAX_ERROR_CHARS = 200


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return (stem or "model")[:60]


def _truncate(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


class JobStore:
    """Job records, one JSON file per job under <root>/<id>/job.json."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict[str, Any]] = {}

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def save(self, job: dict[str, Any]) -> None:
        d = self.job_dir(job["job_id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / "job.json")
        self._jobs[job["job_id"]] = job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    def queued_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j["status"] == "queued")

    def load_all(self) -> list[dict[str, Any]]:
        loaded = []
        for path in sorted(self.root.glob("*/job.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("skipping unreadable job record %s", path)
                continue
            self._jobs[job["job_id"]] = job
            loaded.append(job)
        return loaded

    def remove_dir(self, dir_name: str) -> None:
        """Delete a job directory by its name (not by anything inside it)."""
        self._jobs.pop(dir_name, None)
        shutil.rmtree(self.root / dir_name, ignore_errors=True)


class JobService:
    def __init__(self, store: JobStore, orca: OrcaClient, *,
                 max_concurrent: int = 1, retention_hours: float = 24.0,
                 cleanup_interval_secs: float = 3600.0, slice_timeout_s: float = 900.0):
        self.store = store
        self.orca = orca
        self.max_concurrent = max(1, max_concurrent)
        self.retention = timedelta(hours=retention_hours)
        self.cleanup_interval_secs = cleanup_interval_secs
        self.slice_timeout_s = slice_timeout_s
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    # lifecycle -------------------------------------------------------------
    def recover(self) -> None:
        """Mark jobs interrupted by a restart; re-queue unstarted jobs in created_at order."""
        jobs = sorted(self.store.load_all(), key=lambda j: j.get("created_at") or "")
        for job in jobs:
            if job["status"] == "running":
                job["status"] = "failed"
                job["error"] = "interrupted"
                job["finished_at"] = utcnow()
                self._save_best_effort(job)
            elif job["status"] == "queued":
                self.queue.put_nowait(job["job_id"])

    async def start(self) -> None:
        self.recover()
        for _ in range(self.max_concurrent):
            self._tasks.append(asyncio.create_task(self._worker()))
        self._tasks.append(asyncio.create_task(self._cleanup_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    # submission ------------------------------------------------------------
    def create(self, *, job_id: str, printer: PrinterSpec, outputs: list[str],
               original_name: str, stored_name: str, input_size: int,
               profile_overrides: list[str]) -> dict[str, Any]:
        job = {
            "job_id": job_id,
            "status": "queued",
            "printer": printer.id,
            "outputs": outputs,
            "input": {"name": stored_name, "original_name": original_name, "size": input_size},
            "profile_overrides": profile_overrides,
            "created_at": utcnow(),
            "finished_at": None,
            "error": None,
            "files": [],
            "validation": {},
            "metadata": {},
        }
        (self.store.job_dir(job_id) / "input").mkdir(parents=True, exist_ok=True)
        self.store.save(job)
        return job

    def enqueue(self, job_id: str) -> None:
        """Call only after the job's input files are fully written."""
        self.queue.put_nowait(job_id)

    # cleanup ---------------------------------------------------------------
    def cleanup_expired(self, now: datetime | None = None) -> list[str]:
        """Remove finished jobs past retention, and orphan dirs (no record, older than 1h).

        Works from directory names; each directory is handled in its own try block.
        """
        now = now or datetime.now(timezone.utc)
        removed: list[str] = []
        for entry in list(self.store.root.iterdir()):
            name = entry.name
            try:
                if not entry.is_dir():
                    continue
                record = entry / "job.json"
                if not record.exists():
                    if time.time() - entry.stat().st_mtime > ORPHAN_AGE_SECS:
                        self.store.remove_dir(name)
                        removed.append(name)
                    continue
                job = json.loads(record.read_text(encoding="utf-8"))
                if job.get("status") not in TERMINAL or not job.get("finished_at"):
                    continue
                finished = datetime.fromisoformat(job["finished_at"])
                if now - finished > self.retention:
                    self.store.remove_dir(name)
                    removed.append(name)
            except Exception:
                log.exception("cleanup skipped job dir %s", name)
        return removed

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval_secs)
            try:
                await asyncio.to_thread(self.cleanup_expired)
            except Exception:  # keep the loop alive
                log.exception("cleanup failed")

    # worker ----------------------------------------------------------------
    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self.run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # run() handles pipeline errors itself; this only guards the worker loop.
                log.exception("worker error on job %s", job_id)
                self._mark_failed_best_effort(job_id, "internal error: worker")
            finally:
                self.queue.task_done()

    def _save_best_effort(self, job: dict[str, Any]) -> None:
        try:
            self.store.save(job)
        except Exception:
            log.exception("could not save job %s", job.get("job_id"))

    def _mark_failed_best_effort(self, job_id: str, error: str) -> None:
        job = self.store.get(job_id)
        if job is None or job["status"] in TERMINAL:
            return
        job["status"] = "failed"
        job["error"] = _truncate(error)
        job["finished_at"] = utcnow()
        self._save_best_effort(job)

    async def run(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None or job["status"] != "queued":
            return
        job["status"] = "running"
        await asyncio.to_thread(self.store.save, job)
        try:
            await self._pipeline(job)
            job["status"] = "succeeded"
        except asyncio.CancelledError:
            raise
        except (ValidationError, OrcaError, ValueError, OSError, asyncio.TimeoutError) as exc:
            log.warning("job %s failed: %s", job_id, exc)
            await asyncio.to_thread(self._discard_outputs, job)
            job["status"] = "failed"
            job["error"] = _truncate(str(exc) or type(exc).__name__)
        except Exception as exc:  # unexpected: record and keep the worker alive
            log.exception("job %s crashed", job_id)
            await asyncio.to_thread(self._discard_outputs, job)
            job["status"] = "failed"
            job["error"] = _truncate(f"internal error: {type(exc).__name__}")
        job["finished_at"] = utcnow()
        self._save_best_effort(job)

    def _discard_outputs(self, job: dict[str, Any]) -> None:
        shutil.rmtree(self.store.job_dir(job["job_id"]) / "output", ignore_errors=True)
        job["files"] = []
        job["validation"] = {}

    async def _slice(self, **kwargs: Any):
        try:
            return await asyncio.wait_for(self.orca.slice(**kwargs), timeout=self.slice_timeout_s)
        except asyncio.TimeoutError as exc:
            raise OrcaError(f"slice timed out after {self.slice_timeout_s:g}s") from exc

    async def _pipeline(self, job: dict[str, Any]) -> None:
        spec = PRINTERS[job["printer"]]
        job_dir = self.store.job_dir(job["job_id"])
        model = await asyncio.to_thread((job_dir / "input" / job["input"]["name"]).read_bytes)
        profiles = default_profile_bytes(spec)
        for kind in job["profile_overrides"]:
            profiles[kind] = await asyncio.to_thread(
                (job_dir / "profiles" / f"{kind}.json").read_bytes)
        out_dir = job_dir / "output"
        await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        stem = safe_stem(job["input"]["original_name"])
        outputs = job["outputs"]
        validation: dict[str, Any] = {}
        metadata: dict[str, Any] = {}
        produced: list[tuple[str, bytes]] = []

        def slice_args(export_type: str) -> dict[str, Any]:
            return dict(model=model, model_name=job["input"]["name"],
                        machine=profiles["machine"], process=profiles["process"],
                        filament=profiles["filament"], export_type=export_type)

        gcode = b""
        if "gcode" in outputs or "gx" in outputs:
            out = await self._slice(**slice_args("gcode"))
            gcode = out.data
            validation["gcode"] = await asyncio.to_thread(validate_gcode, gcode, spec.bounds)
            metadata = _metadata_from_headers(out.headers) or _metadata_from_gcode(gcode)
            if "gcode" in outputs:
                produced.append(("gcode", gcode))
        if "gx" in outputs:
            gx = await asyncio.to_thread(write_gx, gcode, _gx_meta(gcode))
            validation["gx"] = await asyncio.to_thread(validate_gx, gx, gcode)
            produced.append(("gx", gx))
        if "3mf" in outputs:
            out = await self._slice(**slice_args("3mf"))
            validation["3mf"] = await asyncio.to_thread(validate_3mf, out.data, spec.bounds)
            produced.append(("3mf", out.data))

        files = []
        for kind, data in produced:
            name = f"{stem}{EXTENSION[kind]}"
            await asyncio.to_thread((out_dir / name).write_bytes, data)
            files.append({
                "name": name,
                "kind": kind,
                "content_type": CONTENT_TYPES[kind],
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "url": f"/jobs/{job['job_id']}/files/{name}",
            })
        job["files"] = files
        job["validation"] = {"passed": True, **validation}
        job["metadata"] = metadata

    # download helpers ------------------------------------------------------
    def file_path(self, job: dict[str, Any], name: str) -> Path | None:
        """Path of a file listed in the job; None for anything else (no traversal)."""
        if name not in {f["name"] for f in job["files"]}:
            return None
        base = (self.store.job_dir(job["job_id"]) / "output").resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file():
            return None
        return path


def _metadata_from_headers(headers: dict[str, str]) -> dict[str, Any]:
    def num(key: str) -> float | None:
        raw = headers.get(key.lower())
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    values = {
        "print_time_secs": num("X-Print-Time-Seconds"),
        "filament_used_g": num("X-Filament-Used-g"),
        "filament_used_mm": num("X-Filament-Used-mm"),
    }
    return {k: v for k, v in values.items() if v is not None}


def _metadata_from_gcode(gcode: bytes) -> dict[str, Any]:
    info = gcode_info(gcode)
    return {"print_time_secs": info["print_time_secs"],
            "filament_used_g": info["filament_g"],
            "filament_used_mm": info["filament_mm"]}


_CONFIG_KEYS = {
    "layer_height": re.compile(rb"^; layer_height = ([\d.]+)", re.M),
    "wall_loops": re.compile(rb"^; wall_loops = (\d+)", re.M),
    "nozzle_temperature": re.compile(rb"^; nozzle_temperature = (\d+)", re.M),
    "bed_temperature": re.compile(rb"^; (?:bed_temperature|hot_plate_temp) = (\d+)", re.M),
}


def _gx_meta(gcode: bytes) -> dict[str, int]:
    """Header values for .gx, taken from OrcaSlicer's comments when present."""
    meta: dict[str, int] = {}
    info = gcode_info(gcode)
    if info["print_time_secs"] is not None:
        meta["print_time_secs"] = int(info["print_time_secs"])
    if info["filament_mm"] is not None:
        meta["filament_mm_right"] = int(round(info["filament_mm"]))
    m = _CONFIG_KEYS["layer_height"].search(gcode)
    if m:
        meta["layer_height_microns"] = int(round(float(m.group(1)) * 1000))
    m = _CONFIG_KEYS["wall_loops"].search(gcode)
    if m:
        meta["perimeter_shells"] = int(m.group(1))
    m = _CONFIG_KEYS["nozzle_temperature"].search(gcode)
    if m:
        meta["extruder_temp_right"] = int(m.group(1))
    m = _CONFIG_KEYS["bed_temperature"].search(gcode)
    if m:
        meta["bed_temp"] = int(m.group(1))
    return meta
