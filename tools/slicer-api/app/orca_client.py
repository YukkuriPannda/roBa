"""HTTP client for the internal upstream orca-slicer-api container."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx


class OrcaError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class SliceOutput:
    data: bytes
    filename: str
    headers: dict[str, str] = field(default_factory=dict)


class OrcaClient:
    def __init__(self, base_url: str, timeout: float = 900.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout,
                                       transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=5.0)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def slice(self, *, model: bytes, model_name: str, machine: bytes,
                    process: bytes, filament: bytes, export_type: str) -> SliceOutput:
        """POST /slice with uploaded profiles.

        Upstream merges inherited profiles (resolveProfileInheritance=true); uploaded
        profiles without an `inherits` key are used unchanged.
        """
        files = {
            "file": (model_name, model, model_mime(model_name)),
            "printerProfile": ("machine.json", machine, "application/json"),
            "presetProfile": ("process.json", process, "application/json"),
            "filamentProfile": ("filament.json", filament, "application/json"),
        }
        data = {
            "exportType": export_type,
            "resolveProfileInheritance": "true",
            "plate": "1",
        }
        try:
            resp = await self._http.post("/slice", files=files, data=data)
        except httpx.HTTPError as exc:
            raise OrcaError(f"orca request failed: {exc}") from exc
        if resp.status_code != 200:
            detail = resp.text[:500]
            raise OrcaError(f"orca returned HTTP {resp.status_code}: {detail}", resp.status_code)
        headers = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-")}
        filename = _filename_from_disposition(resp.headers.get("content-disposition", ""))
        return SliceOutput(data=resp.content, filename=filename or model_name, headers=headers)


# Upstream checks both the extension and the MIME type of the model part.
_MODEL_MIME = {".stl": "model/stl", ".step": "application/step", ".stp": "application/step",
               ".3mf": "model/3mf"}


def model_mime(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext not in _MODEL_MIME:
        raise OrcaError(f"unsupported model extension: {ext or '(none)'}")
    return _MODEL_MIME[ext]


def _filename_from_disposition(value: str) -> str | None:
    marker = "filename="
    if marker not in value:
        return None
    return value.split(marker, 1)[1].strip().strip('"')
