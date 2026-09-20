"""Reviewed supplemental bounds, pinned to the exact checked RISC-V source.

This trusted display catalog is maintained alongside the website. A maintainer must
check the theorem's all-input cost bound and its connection to submission.scheme
before adding an entry. It neither changes a verdict nor adds an intake requirement.
Measured profiles and submitter-provided prose never supply these bounds.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import settings


@lru_cache(maxsize=4)
def _load(path: Path) -> tuple[dict, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("unsupported RISC-V compression bound catalog")
    return tuple(data["entries"])


def for_submission(sub) -> dict | None:
    if (sub.track != "upper-riscv" or sub.status != "verified"
            or sub.detail_dict.get("demo")):
        return None
    for entry in _load(settings.repo_root / "service" / "riscv-compression-bounds.json"):
        if (sub.id == entry["id"] and sub.commit == entry["commit"]
                and sub.pr_repository == entry["repository"]
                and sub.detail_dict.get("contract") == entry["contract"]
                and sub.claim == entry["cycles"]):
            return {**entry, "proof_url": (
                f'https://github.com/{entry["repository"]}/blob/{entry["commit"]}/'
                f'formal/Submissions/UpperRiscv/{entry["module"]}.lean#L{entry["line"]}')}
    return None
