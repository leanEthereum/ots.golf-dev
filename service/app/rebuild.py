"""Rebuild disposable service state from GitHub, preserving every existing proof verdict.

    python -m app.rebuild               # receipts, attribution and verdicts
    python -m app.rebuild --sources     # also regenerate downloadable source ZIPs

Use the configured web environment so GitHub API reads can authenticate. Source fetching runs
in a separate credential-free process. No candidate is compiled and no verification log is
fabricated. Stop the worker during a fresh-server rebuild if restored queue entries should wait
until source recovery completes. This command never drops or replaces an existing database.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from . import resync, source_archive
from .config import settings
from .db import SessionLocal, Submission, init_db, local_lock


def rebuild_sources(limit: int | None = None) -> dict:
    result = {"restored": 0, "cached": 0, "skipped": 0, "errors": []}
    with SessionLocal() as session:
        rows = session.scalars(select(Submission).order_by(Submission.created_at, Submission.id)).all()
    attempted = 0
    for sub in rows:
        if (sub.detail_dict.get("demo") or not sub.pr_repository
                or sub.pr_repository.lower() != settings.submissions_repo.lower()
                or sub.status not in resync.FINISHED | {"pending"}):
            result["skipped"] += 1
            continue
        missing = not source_archive.is_available(sub)
        if missing and limit is not None and attempted >= limit:
            result["skipped"] += 1
            continue
        attempted += int(missing)
        try:
            metadata, rebuilt = source_archive.rebuild_cache(sub)
            with local_lock("results"), SessionLocal() as session:
                current = session.get(Submission, sub.id)
                if current is None or (current.commit, current.track, current.detail_dict.get("contract")) != (
                        sub.commit, sub.track, sub.detail_dict.get("contract")):
                    raise source_archive.ArchiveError("submission identity changed during cache recovery")
                detail = current.detail_dict
                expected = detail.get("source_archive")
                if expected is not None and source_archive.validate_metadata(expected, current) != metadata:
                    raise source_archive.ArchiveError("submission archive changed during cache recovery")
                detail["source_archive"] = metadata
                current.detail = json.dumps(detail)
                notes = source_archive.read_notes(current)
                if notes:
                    detail["notes"] = notes
                    current.detail = json.dumps(detail)
                session.commit()
            result["restored" if rebuilt else "cached"] += 1
        except Exception as exc:
            # The source cache is optional. An unavailable source cannot revise a proof verdict.
            message = str(exc) if isinstance(exc, source_archive.ArchiveError) else type(exc).__name__
            result["errors"].append({"id": sub.id, "error": message})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", action="store_true", help="reconstruct source ZIPs from exact GitHub commits")
    parser.add_argument("--limit", type=int, help="attempt at most this many missing source caches in this run")
    parser.add_argument("--queue-open-heads", action="store_true",
                        help="also admit current open PR heads with no existing durable receipt")
    args = parser.parse_args(argv)
    if args.limit is not None and (args.limit < 1 or not args.sources):
        parser.error("--limit requires --sources and a positive integer")
    init_db()
    try:
        result = {"database": resync.resync(queue_open_heads=args.queue_open_heads)}
    except Exception as exc:
        result = {"database": {"errors": [f"GitHub restore failed ({type(exc).__name__})"]}}
    if args.sources:
        result["sources"] = rebuild_sources(args.limit)
    result["logs"] = "Original verification logs are not restored; missing logs remain unavailable."
    print(json.dumps(result, indent=2))
    return int(bool(result["database"].get("errors") or result["database"].get("skipped")
                    or result.get("sources", {}).get("errors")))


if __name__ == "__main__":
    raise SystemExit(main())
