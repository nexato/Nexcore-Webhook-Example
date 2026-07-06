"""Download exported files from their pre-signed Azure URLs and store them.

The URLs in the payload are pre-signed Azure SAS URLs: read-only, valid ~24h,
fetched with a plain ``GET`` and no extra auth. The download goes **directly to
Azure** (not back through any tunnel/proxy in front of this service).

Files are named deterministically from the event's ``entityId`` — the SAS blob
name is a random UUID, so we deliberately do not reuse it::

    OUTPUT_DIR/<tenantId>/<YYYY-MM-DD>/<entityId>_<index>.<ext>

A single event may yield multiple files (e.g. a ResourceAssignment export
produces a ZIP **and** a PDF), so ``download_files`` always handles a list.

Hardening notes:

- ``tenantId`` comes from the (unsigned) ``x-nx-tenant-id`` header and ``entityId``
  from the body; both are sanitized to a safe filename charset and the final path
  is asserted to stay inside ``OUTPUT_DIR`` (defense against path traversal).
- Redirects are not followed (SAS URLs are direct; this avoids a redirect-pivot
  SSRF). Downloads are size-capped. Only retriable HTTP statuses are retried.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import time
from datetime import date
from pathlib import Path

import httpx

from .models import ExportFile

logger = logging.getLogger("nexcore_webhook")

#: Explicit MIME → extension map for the types Nexcore exports. Anything else
#: falls back to the stdlib guess, then ``.bin``.
MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/octet-stream": ".bin",
}

#: HTTP statuses worth retrying. Other 4xx (e.g. 403/404 from an expired/deleted
#: SAS URL) are permanent for that URL — retrying cannot succeed.
RETRIABLE_STATUS = {408, 429, 500, 502, 503, 504}

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class DownloadError(RuntimeError):
    """Raised when a file cannot be downloaded (after retries, too large, etc.)."""


def safe_path_component(value: str | None, fallback: str) -> str:
    """Sanitize a string for safe use as a single path segment.

    Replaces anything outside ``[A-Za-z0-9._-]`` (notably ``/``, ``\\`` and ``:``)
    and strips leading/trailing dots/spaces so values like ``..``, ``/etc`` or
    ``../../x`` cannot act as path separators or directory traversal.
    """
    if not value:
        return fallback
    cleaned = _UNSAFE_CHARS.sub("_", value).strip(". ")
    return cleaned or fallback


def extension_for_mime(mime_type: str | None) -> str:
    """Return a file extension (incl. leading dot) for a MIME type."""
    mt = (mime_type or "").split(";")[0].strip().lower()
    if not mt:
        return ".bin"
    if mt in MIME_EXTENSIONS:
        return MIME_EXTENSIONS[mt]
    return mimetypes.guess_extension(mt) or ".bin"


def build_target_path(
    output_dir: Path | str,
    tenant_id: str | None,
    entity_id: str | None,
    index: int,
    mime_type: str | None,
) -> Path:
    """Build the deterministic destination path for one file.

    Both ``tenant_id`` and ``entity_id`` are sanitized, and the resolved result is
    asserted to stay within ``output_dir`` (raises ``DownloadError`` otherwise).
    """
    tenant = safe_path_component(tenant_id, "unknown-tenant")
    entity = safe_path_component(entity_id, "unknown")
    ext = extension_for_mime(mime_type)
    base = Path(output_dir)
    dest = base / tenant / date.today().isoformat() / f"{entity}_{index}{ext}"
    if not dest.resolve().is_relative_to(base.resolve()):
        raise DownloadError(f"refusing to write outside OUTPUT_DIR: {dest}")
    return dest


def _download_one(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    timeout: float,
    max_attempts: int,
    retry_backoff_seconds: float,
    max_bytes: int,
) -> None:
    """Download ``url`` to ``dest`` with retries; write atomically via a .part file."""
    part = dest.parent / (dest.name + ".part")
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with client.stream("GET", url, timeout=timeout) as resp:
                resp.raise_for_status()
                written = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        written += len(chunk)
                        if max_bytes and written > max_bytes:
                            raise DownloadError(
                                f"{dest.name} exceeds max size {max_bytes} bytes"
                            )
                        fh.write(chunk)
            part.replace(dest)  # atomic on the same filesystem
            return
        except DownloadError:
            part.unlink(missing_ok=True)
            raise  # size cap exceeded — not retriable
        except httpx.HTTPStatusError as exc:
            part.unlink(missing_ok=True)
            status = exc.response.status_code
            if status not in RETRIABLE_STATUS:
                raise DownloadError(
                    f"non-retriable HTTP {status} downloading {dest.name}"
                ) from exc
            last_exc = exc
        except httpx.HTTPError as exc:  # transport errors (connect/read/timeout)
            part.unlink(missing_ok=True)
            last_exc = exc

        if attempt < max_attempts:
            backoff = retry_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "download attempt %d/%d failed for %s: %s — retrying in %.2fs",
                attempt,
                max_attempts,
                dest.name,
                last_exc,
                backoff,
            )
            time.sleep(backoff)
    raise DownloadError(
        f"failed to download {dest.name} after {max_attempts} attempt(s)"
    ) from last_exc


def download_files(
    files: list[ExportFile],
    *,
    output_dir: Path | str,
    tenant_id: str | None,
    entity_id: str | None,
    timeout: float = 60.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
    max_bytes: int = 0,
    client: httpx.Client | None = None,
) -> list[Path]:
    """Download every file in ``files`` and return the stored paths.

    ``max_retries`` is the number of retries after the first attempt
    (total attempts = ``max_retries + 1``). ``max_bytes`` of 0 means unlimited.
    Pass a pre-built ``client`` to reuse a connection pool (or inject one in tests).
    """
    max_attempts = max(1, max_retries + 1)
    own_client = client is None
    client = client or httpx.Client(follow_redirects=False)
    stored: list[Path] = []
    try:
        for index, file in enumerate(files):
            dest = build_target_path(output_dir, tenant_id, entity_id, index, file.mime_type)
            _download_one(
                client,
                file.url,
                dest,
                timeout=timeout,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
                max_bytes=max_bytes,
            )
            logger.info("stored %s", dest)
            stored.append(dest)
    finally:
        if own_client:
            client.close()
    return stored
