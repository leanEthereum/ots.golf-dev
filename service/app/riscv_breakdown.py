"""Optional owner profiles from submissions main; GitHub is the sole durable store."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from . import github, riscv_program_size
from .config import settings
from .riscv_profile_format import MAX_BYTES, REGISTRY_PATH, parse_registry, validate_profile

FIXTURE = Path(__file__).resolve().parents[1] / "demo" / "riscv-profile.json"
REFRESH_SECONDS = 60
log = logging.getLogger(__name__)


class ProfileCache:
    """Atomic in-memory snapshots. Rendering never performs a network request."""
    def __init__(self):
        self.snapshot = ("", {})
        self.etag = None

    def refresh(self) -> None:
        repo = settings.submissions_repo
        if not repo or not github.REPO_RE.fullmatch(repo):
            return
        if self.snapshot[0] != repo:
            self.snapshot, self.etag = (repo, {}), None
        headers = {**github._headers(), "Accept": "application/vnd.github.raw+json"}
        if self.etag:
            headers["If-None-Match"] = self.etag
        # Only the configured upstream's main is authoritative, never a PR branch or fork.
        url = f"{github.API}/repos/{repo}/contents/{REGISTRY_PATH}"
        try:
            with httpx.Client(timeout=10) as client, client.stream(
                    "GET", url, params={"ref": "main"}, headers=headers) as response:
                if response.status_code == 304:
                    return
                if response.status_code == 404:
                    self.snapshot, self.etag = (repo, {}), None
                    return
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("profile registry exceeds 1 MiB")
                profiles, errors = parse_registry(bytes(raw))
                for sid, error in errors.items():
                    log.warning("Ignoring invalid RISC-V profile %r: %s", sid, error)
                self.snapshot, self.etag = (repo, profiles), response.headers.get("ETag")
        except httpx.HTTPError:
            # A temporary outage leaves the last known good snapshot usable.
            log.warning("Could not refresh RISC-V profiles from GitHub; retaining cached profiles")
        except ValueError as exc:
            # A successful but malformed owner edit must not leave an obsolete table visible.
            self.snapshot, self.etag = (repo, {}), None
            log.warning("Ignoring invalid RISC-V profile registry: %s", exc)


cache = ProfileCache()


async def refresh_loop() -> None:
    while True:
        await asyncio.to_thread(cache.refresh)
        await asyncio.sleep(REFRESH_SECONDS)


def for_submission(sub) -> dict | None:
    if sub.track not in riscv_program_size.IMAGE_TRACKS:
        return None
    if sub.detail_dict.get("demo"):
        if (sub.track != "upper-riscv" or not settings.phony
                or sub.detail_dict.get("fixture_id") != "upper-riscv-satoshi-nakamoto-2"):
            return None
        return validate_profile(json.loads(FIXTURE.read_text())["profile"])
    repo, profiles = cache.snapshot
    if (sub.status != "verified" or not repo or repo != settings.submissions_repo
            or (sub.pr_repository or "").lower() != repo.lower()):
        return None
    profile = profiles.get(sub.id)
    if (not profile or profile["commit"] != sub.commit
            or profile["contract"] != sub.detail_dict.get("contract")
            or type(sub.claim) is not int):
        return None
    # The hinted certificate bounds accepting runs only. A measured rejection may cost more.
    if (sub.track == "upper-riscv" or profile["accepted"]) and profile["cycles"] > sub.claim:
        return None
    return profile
