"""Service integration for immutable source snapshots, never GitHub's moving PR ref.

The verifier parent writes the store. The service validates metadata before attaching it to a
result and validates object bytes before download. Missing archives do not change old verdicts.
"""
from __future__ import annotations

from pathlib import Path
import sys
import io
import zipfile

from fastapi import HTTPException
from fastapi.responses import Response

from .config import settings

# The helper belongs to the same trusted checkout as this service; no submission module is imported.
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from verifier import source_archive as archives  # noqa: E402

ArchiveError = archives.ArchiveError


def directory() -> Path:
    return settings.data_dir / "sources"


def validate_metadata(value: object, sub) -> dict:
    """Bind a descriptor to the queued head, track and frozen contract."""
    expected_contract = sub.detail_dict.get("contract")
    if not isinstance(expected_contract, str) or not archives.HEX64.fullmatch(expected_contract):
        raise ArchiveError("submission has no valid frozen source archive contract")
    return archives.validate_metadata(value, commit=sub.commit, track=sub.track, contract=expected_contract)


def metadata_for_submission(sub) -> dict | None:
    value = sub.detail_dict.get("source_archive")
    if value is None:
        return None
    try:
        return validate_metadata(value, sub)
    except ArchiveError:
        return None


def recover_metadata(sub) -> dict | None:
    """Use after process exit, including timeout, before recording the result or deleting work."""
    meta = archives.read_metadata(directory(), sub.id)
    if meta is None:
        return None
    meta = validate_metadata(meta, sub)
    expected = metadata_for_submission(sub)
    if expected is not None and expected != meta:
        raise ArchiveError("retained source differs from the submission's recorded archive")
    archives.validated_path(directory(), meta)
    return meta


def validated_path(sub) -> Path | None:
    """Return only a complete, hash-checked regular archive of this exact submission."""
    meta = metadata_for_submission(sub)
    if meta is None:
        return None
    return archives.validated_path(directory(), meta)


def is_available(sub) -> bool:
    """A cheap presence check for page rendering; downloads verify the full digest and layout."""
    meta = metadata_for_submission(sub)
    if meta is None:
        return False
    try:
        path = archives.object_path(directory(), meta)
        return not path.is_symlink() and path.is_file() and path.stat().st_size == meta["size_bytes"]
    except (ArchiveError, OSError):
        return False


def read_notes(sub) -> str | None:
    """Recover the checked notes from retained bytes even after the GitHub head disappears."""
    meta = metadata_for_submission(sub)
    if meta is None:
        return None
    try:
        raw = archives.read_validated_bytes(directory(), meta)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            data = archive.read(meta["submission_root"] + "/NOTES.md")
        return data[:64 * 1024].decode("utf-8", errors="replace").strip() or None
    except (ArchiveError, OSError, KeyError):
        return None


def download_response(sub) -> Response:
    try:
        meta = metadata_for_submission(sub)
        if meta is None:
            raise ArchiveError("source archive unavailable")
        body = archives.read_validated_bytes(directory(), meta)
    except (ArchiveError, OSError):
        raise HTTPException(404, "source archive unavailable") from None
    # Hold the checked bytes in the response: reopening a validated path would introduce a race.
    filename = f"ots-golf-{meta['track']}-{meta['commit'][:12]}.zip"
    return Response(body, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-Type-Options": "nosniff", "ETag": f'"{meta["sha256"]}"',
                 "Cache-Control": "public, max-age=31536000, immutable"})
