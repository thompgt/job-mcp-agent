"""Filesystem access, with the guards a network-reachable server needs.

Two separate problems are solved here.

**Reading paths the caller names.** A tool that accepts ``path=`` and reads it
is a file-disclosure primitive if the server is reachable over HTTP. Paths are
resolved (following symlinks) and then checked against an allow-list, and
``path=`` is refused outright under HTTP transport — over stdio the server
already runs as the user, so the allow-list is the meaningful boundary; over
HTTP the caller is not necessarily the user.

**Accepting uploads.** The client-supplied filename is discarded entirely
rather than sanitised, because sanitising is a game you eventually lose.
Uploads land under a generated name with a validated suffix, and are written
in bounded chunks so a large body cannot fill the disk before the size check.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import AsyncIterator, Iterable
from uuid import uuid4

import anyio

from careercraft.core.resume.extract import SUPPORTED_SUFFIXES
from careercraft.errors import AccessDenied, ValidationFailed

_CHUNK = 64 * 1024
_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def validate_suffix(filename: str | None) -> str:
    """Extract a safe extension from an untrusted filename.

    Only the suffix survives; everything else about the name is discarded.
    """
    suffix = Path(filename or "").suffix.lower()
    if not _SUFFIX_RE.match(suffix) or suffix not in SUPPORTED_SUFFIXES:
        raise ValidationFailed(
            f"Unsupported file type {suffix or '(none)'!r}.",
            remedy=f"Upload one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
        )
    return suffix


def resolve_allowed(
    path: str | Path,
    allowed_roots: Iterable[Path],
    *,
    transport: str = "stdio",
) -> Path:
    """Resolve ``path`` and confirm it sits under an allowed root."""
    if transport == "http":
        raise AccessDenied(
            "Reading local paths is disabled when this server is reached over HTTP.",
            remedy="Upload the file instead, or run the server over stdio.",
        )

    try:
        # strict=True so a non-existent path fails here rather than after the
        # containment check, and so symlinks are resolved before comparison.
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationFailed(
            f"Cannot resolve path {path!r}.",
            remedy="Pass an absolute path to an existing file.",
        ) from exc

    roots = [Path(r).expanduser().resolve() for r in allowed_roots]
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise AccessDenied(
            f"{resolved} is outside the allowed directories.",
            remedy=(
                "Move the file under "
                + ", ".join(str(r) for r in roots)
                + ", or add its directory to CAREERCRAFT_ALLOWED_PATHS."
            ),
        )
    if not resolved.is_file():
        raise ValidationFailed(
            f"{resolved} is not a regular file.",
            remedy="Pass the path to a .pdf, .docx or .txt resume.",
        )
    return resolved


async def save_upload(
    stream: AsyncIterator[bytes],
    *,
    filename: str | None,
    upload_dir: Path,
    max_bytes: int,
) -> Path:
    """Stream an upload to disk under a generated name.

    The size limit is enforced as bytes arrive, not after, and a body that
    exceeds it leaves nothing behind.
    """
    suffix = validate_suffix(filename)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid4().hex}{suffix}"

    written = 0
    try:
        async with await anyio.open_file(target, "wb") as handle:
            async for chunk in stream:
                written += len(chunk)
                if written > max_bytes:
                    raise ValidationFailed(
                        f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                        remedy="Upload a smaller file, or raise CAREERCRAFT_MAX_UPLOAD_BYTES.",
                    )
                await handle.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    if written == 0:
        target.unlink(missing_ok=True)
        raise ValidationFailed("The uploaded file is empty.", remedy="Choose a different file.")
    return target


def chunked(data: bytes, size: int = _CHUNK) -> AsyncIterator[bytes]:
    """Adapt an in-memory body to the streaming interface above."""

    async def gen() -> AsyncIterator[bytes]:
        for start in range(0, len(data), size):
            yield data[start : start + size]

    return gen()
