"""Durable, content-addressed copies of the exact flat root checked by the verifier.

Only the trusted verifier parent writes this store, before running candidate code. ZIPs are
uncompressed, deterministic, bounded, and never extracted using ZipFile.extract().
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

MAX_FILES = 200
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MIN_FREE_BYTES = 64 * 1024 * 1024  # leave space to record an infrastructure failure
MANIFEST = "OTS-SOURCE.json"
HEX64 = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})")
SUBMISSION_ID = re.compile(r"[a-f0-9]{32}")
ROOT = re.compile(r"formal/Submissions/[A-Za-z][A-Za-z0-9_]*")
TRACK = re.compile(r"[a-z][a-z0-9-]{0,63}")
LEAN_FILE = re.compile(r"[A-Za-z][A-Za-z0-9_]*\.lean")
IDENTITY = ("source_repo", "commit", "track", "submission_root", "contract")
META_KEYS = ("version", "sha256", "size_bytes", "file_count", "total_bytes", *IDENTITY)


class ArchiveError(Exception):
    """Retention or integrity failed; this is never a proof verdict."""


def _name(name: str) -> bool:
    return bool(LEAN_FILE.fullmatch(name)) or name in {"claim.txt", "README.md", "NOTES.md"}


def _read(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ArchiveError("archive input is not a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ArchiveError("archive input exceeds its size limit")
    return data


def _json(data: bytes) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out
    try:
        value = json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise ArchiveError("invalid archive metadata") from exc
    if not isinstance(value, dict):
        raise ArchiveError("archive metadata must be an object")
    return value


def _bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate_metadata(value: object, *, commit: str | None = None, track: str | None = None,
                      contract: str | None = None, submission_root: str | None = None) -> dict:
    if not isinstance(value, dict) or any(k not in value for k in META_KEYS):
        raise ArchiveError("incomplete source archive metadata")
    out = {k: value[k] for k in META_KEYS}
    for key, regex in (("sha256", HEX64), ("commit", COMMIT), ("contract", HEX64),
                       ("track", TRACK), ("submission_root", ROOT)):
        if not isinstance(out[key], str) or not regex.fullmatch(out[key]):
            raise ArchiveError(f"invalid source archive {key}")
    if not isinstance(out["source_repo"], str) or not 1 <= len(out["source_repo"]) <= 4096:
        raise ArchiveError("invalid source archive repository")
    for key, low, high in (("version", 1, 1), ("size_bytes", 1, MAX_ARCHIVE_BYTES),
                           ("file_count", 0, MAX_FILES), ("total_bytes", 0, MAX_TOTAL_BYTES)):
        if type(out[key]) is not int or not low <= out[key] <= high:
            raise ArchiveError(f"invalid source archive {key}")
    for key, expected in (("commit", commit), ("track", track), ("contract", contract),
                          ("submission_root", submission_root)):
        if expected is not None and out[key] != expected:
            raise ArchiveError(f"source archive {key} does not match the submission")
    return out


def _store(store: Path, *, create: bool = False) -> Path:
    store = Path(store)
    if store.is_symlink():
        raise ArchiveError("source archive directory must not be a symbolic link")
    if create:
        store.mkdir(parents=True, exist_ok=True, mode=0o750)
    if not store.is_dir() or store.is_symlink():
        raise ArchiveError("source archive directory is unavailable")
    return store


def _index(store: Path, submission_id: str) -> Path:
    if not isinstance(submission_id, str) or not SUBMISSION_ID.fullmatch(submission_id):
        raise ArchiveError("invalid source archive submission id")
    return store / f"{submission_id}.json"


def read_metadata(store: Path, submission_id: str) -> dict | None:
    """Recover the durable binding even if verification timed out before printing JSON."""
    path = _index(Path(store), submission_id)
    if not path.exists() and not path.is_symlink():
        return None
    _store(store)
    record = _json(_read(path, MAX_MANIFEST_BYTES))
    if record.get("submission_id") != submission_id:
        raise ArchiveError("source archive sidecar belongs to another submission")
    return validate_metadata(record.get("archive"))


def object_path(store: Path, metadata: dict) -> Path:
    meta = validate_metadata(metadata)
    return _store(store) / f"{meta['sha256']}.zip"


def _publish(path: Path, data: bytes) -> None:
    """Publish once; retries may reuse identical bytes, never replace an old object."""
    fd, temporary = tempfile.mkstemp(prefix=".archive-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o640)
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read(path, len(data)) != data:
                raise ArchiveError("refusing to overwrite an immutable source archive")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def _zip_entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o644) << 16
    return entry


def save_source(store: Path, submission_id: str, root: Path, *, source_repo: str, commit: str,
                track: str, submission_root: str, contract: str) -> dict:
    """Snapshot a staged root and commit its binding before untrusted compilation starts."""
    identity = dict(source_repo=source_repo, commit=commit, track=track,
                    submission_root=submission_root, contract=contract)
    # Validate every identity before creating files, including caller-controlled CLI inputs.
    validate_metadata(dict(version=1, sha256="0" * 64, size_bytes=1, file_count=0,
                           total_bytes=0, **identity))
    _index(Path(store), submission_id)
    if root.is_symlink() or not root.is_dir():
        raise ArchiveError("source archive requires a regular submission directory")
    entries = sorted(root.iterdir())
    if len(entries) > MAX_FILES:
        raise ArchiveError("too many source archive files")
    files, total = [], 0
    for path in entries:
        if not _name(path.name):
            raise ArchiveError("invalid source archive filename")
        data = _read(path, MAX_FILE_BYTES)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ArchiveError("source archive exceeds its total size limit")
        files.append((path.name, data))
    manifest = dict(version=1, **identity, file_count=len(files), total_bytes=total,
                    files=[dict(name=name, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                           for name, data in files])
    manifest_bytes = _bytes(manifest)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ArchiveError("source archive manifest is too large")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_zip_entry(MANIFEST), manifest_bytes)
        for name, data in files:
            archive.writestr(_zip_entry(f"{submission_root}/{name}"), data)
    data = buffer.getvalue()
    metadata = validate_metadata(dict(version=1, sha256=hashlib.sha256(data).hexdigest(),
                                      size_bytes=len(data), file_count=len(files), total_bytes=total, **identity))
    store = _store(store, create=True)
    old = read_metadata(store, submission_id)
    if old is not None and old != metadata:
        raise ArchiveError("submission already has a different immutable source archive")
    if shutil.disk_usage(store).free < len(data) + MIN_FREE_BYTES:
        raise ArchiveError("insufficient free space to retain source and record the verdict")
    _publish(store / f"{metadata['sha256']}.zip", data)
    _publish(_index(store, submission_id), _bytes(dict(submission_id=submission_id, archive=metadata)))
    return metadata


def _contents(store: Path, metadata: dict) -> tuple[bytes, list[tuple[str, bytes]]]:
    meta = validate_metadata(metadata)
    raw = _read(object_path(store, meta), MAX_ARCHIVE_BYTES)
    if len(raw) != meta["size_bytes"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
        raise ArchiveError("source archive digest or size does not match")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (len(entries) != meta["file_count"] + 1 or len({i.filename for i in entries}) != len(entries)
                    or any(i.compress_type != zipfile.ZIP_STORED or i.flag_bits & 1
                           or not stat.S_ISREG(i.external_attr >> 16) for i in entries)):
                raise ArchiveError("invalid source archive entries")
            manifest_info = archive.getinfo(MANIFEST)
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise ArchiveError("source archive manifest is too large")
            manifest = _json(archive.read(MANIFEST))
            for key in ("version", "file_count", "total_bytes", *IDENTITY):
                if manifest.get(key) != meta[key]:
                    raise ArchiveError("source archive manifest does not match its metadata")
            rows = manifest.get("files")
            if not isinstance(rows, list) or len(rows) != meta["file_count"]:
                raise ArchiveError("invalid source archive file manifest")
            files, names, total = [], set(), 0
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not _name(row["name"]):
                    raise ArchiveError("invalid source archive filename")
                name = row["name"]
                if name in names or type(row.get("size_bytes")) is not int or not 0 <= row["size_bytes"] <= MAX_FILE_BYTES:
                    raise ArchiveError("invalid source archive file size or duplicate name")
                names.add(name)
                info = archive.getinfo(f"{meta['submission_root']}/{name}")
                if info.file_size != row["size_bytes"]:
                    raise ArchiveError("source archive file size mismatch")
                data = archive.read(info)
                if hashlib.sha256(data).hexdigest() != row.get("sha256"):
                    raise ArchiveError("source archive file digest mismatch")
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise ArchiveError("source archive total size exceeded")
                files.append((name, data))
            if total != meta["total_bytes"]:
                raise ArchiveError("source archive total size mismatch")
            return raw, files
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise ArchiveError("invalid source archive ZIP") from exc


def read_validated_bytes(store: Path, metadata: dict) -> bytes:
    """Read at most MAX_ARCHIVE_BYTES and return exactly the digest- and layout-checked bytes."""
    raw, _ = _contents(store, metadata)
    return raw


def validated_path(store: Path, metadata: dict) -> Path:
    """Check current object integrity; downloads must use read_validated_bytes, not reopen this path."""
    _contents(store, metadata)
    return object_path(store, metadata)


def restore_source(store: Path, metadata: dict, destination: Path, *, commit: str, track: str,
                   contract: str, submission_root: str) -> str:
    """Reconstruct a retry from retained bytes, without fetching a moving Git reference."""
    meta = validate_metadata(metadata, commit=commit, track=track, contract=contract,
                             submission_root=submission_root)
    _, files = _contents(store, meta)
    target = destination / submission_root
    target.mkdir(parents=True, exist_ok=False)
    for name, data in files:
        with (target / name).open("xb") as stream:
            stream.write(data)
    return meta["commit"]
