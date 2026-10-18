"""Gateway API: accepts model uploads, runs slicing jobs via the internal orca container."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .jobs import JobService, JobStore
from .orca_client import OrcaClient
from .presets import PRINTERS, PrinterSpec, get_printer

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PROFILE_BYTES = 1024 * 1024
ENVELOPE_SLACK = 1024 * 1024  # multipart overhead allowed beyond the file limit
MODEL_EXTENSIONS = {".stl", ".step", ".stp", ".3mf"}
CHUNK = 1024 * 1024
PROFILE_KINDS = ("machine", "process", "filament")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def create_app(*, orca: OrcaClient | None = None, data_dir: Path | None = None,
               max_upload_bytes: int = MAX_UPLOAD_BYTES, api_key: str | None = None,
               max_queued: int | None = None, slice_timeout: float | None = None) -> FastAPI:
    data_dir = data_dir or Path(os.environ.get("DATA_DIR", "/data"))
    orca = orca or OrcaClient(os.environ.get("ORCA_URL", "http://orca:3000"))
    api_key = api_key if api_key is not None else (os.environ.get("API_KEY") or None)
    max_queued = max_queued if max_queued is not None else _env_int("MAX_QUEUED_JOBS", 20)
    slice_timeout = slice_timeout if slice_timeout is not None else _env_float("SLICE_TIMEOUT_S", 900.0)
    service = JobService(
        JobStore(data_dir / "jobs"),
        orca,
        max_concurrent=_env_int("MAX_CONCURRENT_JOBS", 1),
        retention_hours=_env_float("JOB_RETENTION_HOURS", 24.0),
        cleanup_interval_secs=_env_float("CLEANUP_INTERVAL_SECONDS", 3600.0),
        slice_timeout_s=slice_timeout,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.start()
        try:
            yield
        finally:
            await service.stop()
            await orca.aclose()

    app = FastAPI(title="slicer-api", version="1.0.0", lifespan=lifespan)
    app.state.service = service

    @app.middleware("http")
    async def gate(request: Request, call_next):
        # Runs before the body is parsed, so rejected uploads cost no disk or memory.
        if request.url.path != "/health" and api_key is not None:
            given = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(given.encode(), api_key.encode()):
                return JSONResponse({"detail": "invalid or missing X-API-Key"}, status_code=401)
        if request.method == "POST" and request.url.path == "/jobs":
            length = request.headers.get("content-length")
            if length is not None and length.isdigit() and int(length) > max_upload_bytes + ENVELOPE_SLACK:
                return JSONResponse({"detail": "file exceeds 100 MB limit"}, status_code=413)
            if service.store.queued_count() >= max_queued:
                return JSONResponse({"detail": "job queue is full, retry later"}, status_code=429)
        return await call_next(request)

    @app.get("/health")
    async def health() -> JSONResponse:
        ok = await orca.health()
        return JSONResponse({"status": "ok" if ok else "degraded", "orca": ok},
                            status_code=200 if ok else 503)

    @app.get("/printers")
    async def printers() -> list[dict[str, Any]]:
        return [{"id": p.id, "name": p.name, "outputs": list(p.outputs)}
                for p in PRINTERS.values()]

    @app.post("/jobs", status_code=202)
    async def create_job(
        file: UploadFile = File(...),
        printer: str = Form(...),
        outputs: str | None = Form(None),
        machine_profile: UploadFile | None = File(None),
        process_profile: UploadFile | None = File(None),
        filament_profile: UploadFile | None = File(None),
    ) -> dict[str, str]:
        spec = get_printer(printer)
        if spec is None:
            raise HTTPException(400, f"unknown printer '{printer}'")
        wanted = _parse_outputs(outputs, spec)
        original = Path(file.filename or "").name
        ext = Path(original).suffix.lower()
        if ext not in MODEL_EXTENSIONS:
            raise HTTPException(400, "file must be .stl, .step, .stp or .3mf")

        uploads = {"machine": machine_profile, "process": process_profile,
                   "filament": filament_profile}
        profile_bytes: dict[str, bytes] = {}
        for kind, upload in uploads.items():
            if upload is None:
                continue
            raw = await upload.read(MAX_PROFILE_BYTES + 1)
            profile_bytes[kind] = await asyncio.to_thread(_normalize_profile, spec, kind, raw)

        job_id = uuid.uuid4().hex
        store = service.store
        job_dir = store.job_dir(job_id)
        try:
            input_dir = job_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            stored_name = f"model{ext}"
            size = 0
            with open(input_dir / stored_name, "wb") as out:
                while True:
                    chunk = await file.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_upload_bytes:
                        raise HTTPException(413, "file exceeds 100 MB limit")
                    await asyncio.to_thread(out.write, chunk)
            if size == 0:
                raise HTTPException(400, "file is empty")
            if profile_bytes:
                (job_dir / "profiles").mkdir(exist_ok=True)
                for kind, data in profile_bytes.items():
                    await asyncio.to_thread((job_dir / "profiles" / f"{kind}.json").write_bytes, data)
            service.create(job_id=job_id, printer=spec, outputs=wanted, original_name=original,
                           stored_name=stored_name, input_size=size,
                           profile_overrides=sorted(profile_bytes))
        except BaseException:
            # Any failure (client abort, 413, I/O) leaves no partial job behind.
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        service.enqueue(job_id)
        return {"job_id": job_id, "status": "queued"}

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        return _job_or_404(service, job_id)

    @app.get("/jobs/{job_id}/files/{name}")
    async def get_file(job_id: str, name: str) -> FileResponse:
        job = _job_or_404(service, job_id)
        if job["status"] != "succeeded":
            raise HTTPException(409, f"job is {job['status']}, files are not available")
        path = service.file_path(job, name)
        if path is None:
            raise HTTPException(404, "file not found in job")
        entry = next(f for f in job["files"] if f["name"] == name)
        return FileResponse(path, media_type=entry["content_type"], filename=name)

    return app


def _job_or_404(service: JobService, job_id: str) -> dict[str, Any]:
    job = service.store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _parse_outputs(raw: str | None, spec: PrinterSpec) -> list[str]:
    if raw is None or not raw.strip():
        return list(spec.outputs)
    requested: list[str] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if item not in spec.outputs:
            raise HTTPException(400, f"output '{item}' not allowed for printer '{spec.id}' "
                                     f"(allowed: {', '.join(spec.outputs)})")
        if item not in requested:
            requested.append(item)
    if not requested:
        raise HTTPException(400, "outputs is empty")
    return requested


def _normalize_profile(spec: PrinterSpec, kind: str, data: bytes) -> bytes:
    """Validate an uploaded profile and force the server-side fields.

    - `type` is set from the kind; `from` is forced to "User" (upstream requires it);
      `setting_id` is dropped.
    - `inherits` is forced to the printer's system parent. A different value is a 400.
    """
    if len(data) > MAX_PROFILE_BYTES:
        raise HTTPException(400, f"{kind} profile is too large (max 1 MB)")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, f"{kind} profile is not valid JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(400, f"{kind} profile must be a JSON object")
    if not isinstance(parsed.get("name"), str) or not parsed["name"].strip():
        raise HTTPException(400, f"{kind} profile needs a non-empty name")

    parent = spec.parents.get(kind)
    given = parsed.get("inherits")
    if given not in (None, "") and given != parent:
        if parent is None:
            raise HTTPException(400, f"{kind} profile for '{spec.id}' may not set inherits")
        raise HTTPException(400, f"{kind} profile inherits '{given}', but '{spec.id}' requires "
                                 f"'{parent}'")

    normalized = {k: v for k, v in parsed.items() if k not in ("from", "setting_id", "inherits")}
    normalized["type"] = kind
    normalized["from"] = "User"
    if parent is not None:
        normalized["inherits"] = parent
    return json.dumps(normalized, ensure_ascii=False).encode("utf-8")
