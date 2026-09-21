"""Maintainer-approved proof ports preserve the original achievement and attribution.

This trusted catalog is committed only after the replacement certificate passes the official
verifier. It binds both immutable sources and both contracts; it is not submission metadata.
Receipts, authors and original dates are never edited. GitHub recovery uses the same catalog.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import contract, riscv_program_size
from .config import settings


@lru_cache(maxsize=4)
def _load(path: Path) -> tuple[dict, ...]:
    if not path.is_file():
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("unsupported record revalidation catalog")
    return tuple(data["entries"])


def entries() -> tuple[dict, ...]:
    return _load(settings.repo_root / "service" / "record-revalidations.json")


def _match(sub, side: str) -> dict | None:
    if sub.detail_dict.get("demo"):
        return None
    for entry in entries():
        if ((side == "check" or entry["check_contract"] == contract.contract_id()
             or contract.compatible_result(entry["track"], entry["check_contract"])
             or (entry["track"] == "upper-riscv" and riscv_program_size.compatible_image_source(
                 entry["check_id"], entry["check_commit"], entry["check_contract"])))
                and sub.id == entry[side + "_id"]
                and sub.commit == entry[side + "_commit"]
                and sub.pr_url == entry[side + "_pr_url"]
                and sub.detail_dict.get("contract") == entry[side + "_contract"]
                and sub.track == entry["track"] and sub.claim == entry["claim"]):
            return entry
    return None


def for_original(sub) -> dict | None:
    return _match(sub, "original") if sub.status == "verified" else None


def for_check(sub) -> dict | None:
    return _match(sub, "check")


def is_check(sub) -> bool:
    return for_check(sub) is not None


def proof_url(entry: dict) -> str:
    repository_url = entry["check_pr_url"].split("/pull/", 1)[0]
    return f'{repository_url}/tree/{entry["check_commit"]}/{entry["submission_root"]}'
