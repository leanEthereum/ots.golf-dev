"""Service integration for immutable source snapshots, never GitHub's moving PR ref.

The verifier parent writes the store. The service validates metadata before attaching it to a
result and validates object bytes before download. Missing archives do not change old verdicts.
"""
from __future__ import annotations

from pathlib import Path
import sys
import io
import zipfile
import os
import subprocess
import tempfile

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
    receipt = sub.detail_dict.get("receipt") or {}
    root = receipt.get("submission_root") if isinstance(receipt, dict) else None
    return archives.validate_metadata(value, commit=sub.commit, track=sub.track,
                                      contract=expected_contract, submission_root=root)


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


# Run the bounded exporter in a separate, credential-free interpreter. It reads Git blobs only;
# no Lean, candidate module, hook or checkout is executed. A process-wide deadline also bounds
# the sum of all individual Git operations, whose process groups are cleaned up by the exporter.
_EXPORT_SCRIPT = """
import signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from verifier.verify import export_submission

def timeout(*_):
    raise TimeoutError("source export time limit")
signal.signal(signal.SIGALRM, timeout)
signal.alarm(600)
try:
    commit = export_submission(sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5]))
    print(commit)
except Exception as exc:
    print(type(exc).__name__, file=sys.stderr)
    raise SystemExit(1)
finally:
    signal.alarm(0)
"""


def _export_exact(source: str, commit: str, root: str, destination: Path) -> None:
    """Never inherit web credentials, credential helpers or user/system Git configuration."""
    empty_home = destination.parent / "git-home"
    empty_home.mkdir()
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(empty_home),
           "XDG_CONFIG_HOME": str(empty_home), "TMPDIR": str(empty_home), "PYTHONDONTWRITEBYTECODE": "1",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "2",
           "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
           "GIT_CONFIG_KEY_1": "core.hooksPath", "GIT_CONFIG_VALUE_1": os.devnull}
    try:
        result = subprocess.run([sys.executable, "-B", "-c", _EXPORT_SCRIPT, _ROOT,
                                 source, commit, root, str(destination)],
                                env=env, capture_output=True, text=True, timeout=615, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveError(f"exact source export failed ({type(exc).__name__})") from exc
    if result.stdout.strip() != commit:
        raise ArchiveError("exported source resolved to a different commit")


def rebuild_cache(sub) -> tuple[dict, bool]:
    """Recreate an optional ZIP from a pinned GitHub commit, without changing its proof verdict.

    Return (descriptor, newly_rebuilt). Historical manifest identity and an expected digest are
    binding. Build and compare in a temporary store before publishing to the permanent cache.
    Legacy verdicts can recover only while their exact commit remains available in the base repo.
    """
    from . import contract, github

    detail = sub.detail_dict
    if detail.get("demo") or not sub.pr_repository or sub.pr_repository.lower() != settings.submissions_repo.lower():
        raise ArchiveError("submission does not belong to the configured submissions repository")
    if not isinstance(sub.commit, str) or not github.SHA_RE.fullmatch(sub.commit):
        raise ArchiveError("source recovery requires an exact GitHub commit")
    if detail.get("source_archive_error"):
        raise ArchiveError("the recorded source archive descriptor is invalid")
    expected = validate_metadata(detail["source_archive"], sub) if detail.get("source_archive") is not None else None
    if expected is not None:
        try:
            archives.read_validated_bytes(directory(), expected)
            return expected, False
        except FileNotFoundError:
            pass
        except ArchiveError:
            # A missing directory can be reconstructed. Existing corrupt objects cannot be
            # overwritten by immutable publication, and are surfaced as an explicit error.
            if directory().exists():
                raise
    else:
        retained = recover_metadata(sub)
        if retained is not None:
            return retained, False
    source_ref = detail.get("source_ref")
    if source_ref is not None:
        try:
            github.verify_source_ref(settings.submissions_repo, sub.id, sub.commit, source_ref)
        except Exception as exc:
            raise ArchiveError(f"pinned source ref unavailable ({type(exc).__name__})") from exc
    receipt = detail.get("receipt") or {}
    track = contract.track(sub.track)
    root = (expected["submission_root"] if expected else receipt.get("submission_root")
            or (track or {}).get("submission_root"))
    identity = {"source_repo": expected["source_repo"] if expected else sub.source_repo,
                "commit": sub.commit, "track": sub.track, "submission_root": root,
                "contract": detail.get("contract")}
    archives.validate_metadata(dict(version=1, sha256="0" * 64, size_bytes=1,
                                     file_count=0, total_bytes=0, **identity))
    # The fetch target is trusted configuration; historical source_repo is manifest metadata
    # only. Never use a URL from a comment as a network destination or pass a token to Git.
    source = f"https://github.com/{settings.submissions_repo}.git"
    with tempfile.TemporaryDirectory(prefix="ots-source-rebuild-", dir=settings.work_dir) as temporary:
        staging = Path(temporary) / "export"
        _export_exact(source, sub.commit, root, staging)
        staged_store = Path(temporary) / "archives"
        rebuilt = archives.save_source(staged_store, sub.id, staging / root, **identity)
        if expected is not None and rebuilt != expected:
            raise ArchiveError("reconstructed source does not match the recorded archive digest")
        published = archives.save_source(directory(), sub.id, staging / root, **identity)
        if published != rebuilt:
            raise ArchiveError("source changed while publishing the recovered archive")
    return published, True
