"""Optional owner drawings, pinned to checked submissions and fetched from GitHub main."""
from __future__ import annotations

import json
import asyncio
import hashlib
import logging
import re
from pathlib import Path

import httpx

from . import github
from .config import settings
from .signature_diagram_format import (REGISTRY_PATH, MAX_REGISTRY_BYTES, MAX_IMAGE_BYTES,
                                       MAX_TOTAL_BYTES, parse_registry, validate_svg)

FIXTURES = Path(__file__).resolve().parents[1] / "demo" / "signature-diagrams"
log = logging.getLogger(__name__)


def _read(client, url, limit, *, params=None):
    with client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > limit:
                raise ValueError("GitHub diagram response exceeds its size limit")
        return bytes(raw)


def _image(entry, raw):
    width, height = validate_svg(raw)
    return {**entry, "data": raw, "width": width, "height": height,
            "digest": hashlib.sha256(raw).hexdigest()}


class DiagramCache:
    """Atomic, bounded in-memory snapshots; pages never make GitHub requests."""
    def __init__(self):
        self.snapshot = ("", {})
        self.revision = None

    def refresh(self):
        repo = settings.submissions_repo
        if not repo or not github.REPO_RE.fullmatch(repo):
            return
        if self.snapshot[0] != repo:
            self.snapshot, self.revision = (repo, {}), None
        revision = None
        try:
            # Resolve main once. The registry and all images come from that same immutable commit.
            with httpx.Client(timeout=10, follow_redirects=False, headers=github._headers()) as client:
                ref = json.loads(_read(client, f"{github.API}/repos/{repo}/git/ref/heads/main", 65536))
                revision = ref.get("object", {}).get("sha")
                if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                    raise ValueError("invalid GitHub main revision")
                if revision == self.revision:
                    return
                client.headers["Accept"] = "application/vnd.github.raw+json"
                base = f"{github.API}/repos/{repo}/contents/"
                try:
                    raw = _read(client, base + REGISTRY_PATH, MAX_REGISTRY_BYTES, params={"ref": revision})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    self.snapshot, self.revision = (repo, {}), revision
                    return
                entries, errors = parse_registry(raw)
                for sid, error in errors.items():
                    log.warning("Ignoring invalid signature diagram %r: %s", sid, error)
                diagrams, images, total = {}, {}, 0
                for sid, entry in entries.items():
                    try:
                        path = entry["image"]
                        if path not in images:
                            image = _read(client, base + path, MAX_IMAGE_BYTES, params={"ref": revision})
                            total += len(image)
                            if total > MAX_TOTAL_BYTES:
                                raise ValueError("diagram snapshot exceeds 16 MiB")
                            images[path] = _image({}, image)
                        diagrams[sid] = {**entry, **images[path]}
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        log.warning("Ignoring missing signature diagram image for %s", sid)
                    except ValueError as exc:
                        log.warning("Ignoring invalid signature diagram image for %s: %s", sid, exc)
                self.snapshot, self.revision = (repo, diagrams), revision
        except httpx.HTTPError:
            log.warning("Could not refresh signature diagrams; retaining cached drawings")
        except (ValueError, TypeError, AttributeError) as exc:
            self.snapshot, self.revision = (repo, {}), revision
            log.warning("Ignoring invalid signature diagram registry: %s", exc)


cache = DiagramCache()


async def refresh_loop():
    while True:
        await asyncio.to_thread(cache.refresh)
        await asyncio.sleep(60)


def public_preview(sub_id: str) -> dict | None:
    """Read-only drawing previews, separate from local admission/leaderboard data."""
    if not settings.phony or settings.environment != "development":
        return None
    entries = json.loads((FIXTURES / "public-previews.json").read_text())
    entry = entries.get(sub_id)
    if entry is None:
        return None
    path = (FIXTURES / entry["image"]).resolve()
    if not path.is_relative_to(FIXTURES.resolve()) or path.suffix != ".svg" or not path.is_file():
        return None
    return _image(entry, path.read_bytes())


def for_submission(sub) -> dict | None:
    if sub.track not in {"upper-compressions", "upper-riscv"}:
        return None
    if not sub.detail_dict.get("demo"):
        repo, diagrams = cache.snapshot
        if (sub.status != "verified" or not repo or repo != settings.submissions_repo
                or (sub.pr_repository or "").lower() != repo.lower()):
            return None
        entry = diagrams.get(sub.id)
        if (not entry or entry["commit"] != sub.commit
                or entry["contract"] != sub.detail_dict.get("contract")):
            return None
        return entry
    if not settings.phony or settings.environment != "development":
        return None
    entries = json.loads((FIXTURES / "index.json").read_text())["diagrams"]
    entry = entries.get(sub.detail_dict.get("fixture_id"))
    if not entry or entry["track"] != sub.track:
        return None
    # Paths are selected by the local fixture, never the request or a proof PR.
    path = (FIXTURES / entry["image"]).resolve()
    if not path.is_relative_to(FIXTURES.resolve()) or path.suffix != ".svg" or not path.is_file():
        return None
    return _image(entry, path.read_bytes())
