"""Frozen public results from retired rules, independent of the active contract.

This Git-tracked catalog survives an empty server/database. Its entries describe
historical verdicts; nothing here participates in admission or record promotion.
"""
from datetime import datetime
from pathlib import Path
import json


CATALOG = Path(__file__).resolve().parent.parent / "hall-of-fame.json"


def retirements() -> list[dict]:
    groups = json.loads(CATALOG.read_text())["retirements"]
    for group in groups:
        group["retired_at"] = datetime.fromisoformat(group["date"])
        for track in group["tracks"]:
            for entry in track["entries"]:
                entry["verified_at"] = datetime.fromisoformat(entry["verified_at"])
                entry["source_url"] = (
                    f'{entry["source_repo"]}/tree/{entry["commit"]}/{entry["submission_root"]}')
    return groups


def contains(submission_id: str) -> bool:
    return any(entry["id"] == submission_id for group in retirements()
               for track in group["tracks"] for entry in track["entries"])


def contains_pr_head(pr_url: str, commit: str) -> bool:
    """An unchanged archived head is historical; a new head remains eligible."""
    return any(entry["pr_url"] == pr_url and entry["commit"] == commit
               for group in retirements() for track in group["tracks"]
               for entry in track["entries"])
