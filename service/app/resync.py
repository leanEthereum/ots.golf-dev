"""Restore durable GitHub receipts and verdicts without compiling historical submissions.

Startup restores metadata only. ``python -m app.rebuild --sources`` also reconstructs the
optional local source ZIP cache from exact commits; original verification logs are disposable.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select

from . import auth, contract, git_authors, github, hall_of_fame, riscv_program_size, source_archive
from .config import settings
from .db import SessionLocal, Submission, init_db, local_lock, legacy_pr_submission_id, schedule_report

FINISHED = {"verified", "rejected", "policy_rejected", "timeout", "failed"}
RECEIPT_KEYS = ("created_at", "author", "description", "co_authors", "assisted_by",
                "contract_commit", "submission_root")


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def latest_verdicts(comments: list[dict], bot: str) -> list[tuple[dict, int | None]]:
    """Merge receipts and terminal history by event time, then comment edit time.

    A retry has a fresh receipt time; a copied old receipt cannot erase a later verdict.
    Contract epochs remain independent histories.
    """
    latest = {}
    for comment in comments:
        if ((comment.get("user") or {}).get("login") or "").lower() != bot.lower():
            continue
        cid = comment.get("id")
        cid = cid if type(cid) is int else None
        edited = _time(comment.get("updated_at")) or _time(comment.get("created_at")) or datetime.min
        for verdict in github.parse_verdicts(comment.get("body") or ""):
            if verdict["status"] not in FINISHED | {"pending"}:
                continue
            epoch = verdict.get("contract")
            if epoch is not None and not isinstance(epoch, str):
                continue
            key = verdict["track"], verdict["commit"], epoch
            event = verdict.get("finished_at") if verdict["status"] in FINISHED else verdict.get("created_at")
            order = (_time(event) or datetime.min, verdict["status"] in FINISHED, edited, cid or 0)
            if key not in latest or order > latest[key][0]:
                latest[key] = (order, verdict, cid)
    return [(v, cid) for _, v, cid in latest.values()]


def _receipt(verdict: dict) -> dict | None:
    """A pinned admission requires all frozen fields; legacy verdicts use the PR fallback."""
    if not verdict.get("source_ref"):
        return None
    receipt = {key: verdict.get(key) for key in RECEIPT_KEYS}
    author = receipt["author"]
    if (not _time(receipt["created_at"]) or not isinstance(author, dict)
            or not isinstance(author.get("login"), str) or not github.LOGIN_RE.fullmatch(author["login"])
            or type(author.get("id")) is not int or author["id"] <= 0
            or (author.get("avatar_url") is not None and not isinstance(author["avatar_url"], str))
            or (receipt["description"] is not None and not isinstance(receipt["description"], str))
            or not isinstance(receipt["co_authors"], list)
            or any(not isinstance(name, str) for name in receipt["co_authors"])
            or (receipt["assisted_by"] is not None and not isinstance(receipt["assisted_by"], str))
            or not isinstance(receipt["contract_commit"], str)
            or not github.SHA_RE.fullmatch(receipt["contract_commit"])
            or not isinstance(receipt["submission_root"], str)
            or not source_archive.archives.ROOT.fullmatch(receipt["submission_root"])
            or not isinstance(verdict.get("contract"), str)
            or not source_archive.archives.HEX64.fullmatch(verdict["contract"])):
        raise ValueError("invalid frozen admission receipt")
    # Optional only for receipts predating Git attribution. Preserve this durable
    # list so rebuilding on a fresh host never substitutes a newer PR revision.
    if verdict.get("git_authors") is not None:
        receipt["git_authors"] = git_authors.validate(verdict["git_authors"])
    return receipt


def resync(queue_open_heads: bool = True) -> dict:
    """Restore the complete frontier before allowing new proofs or public verdicts.

    An error or interruption leaves a persistent barrier. Only a successful metadata restore
    clears it; restarting a service cannot publish against a partially restored database.
    """
    if not settings.github_token or not settings.submissions_repo:
        return {"skipped": "no GitHub token or submissions repository configured"}
    with local_lock("recovery"):
        marker = settings.data_dir / "recovery.incomplete"
        marker.touch()
        result = _resync(queue_open_heads=queue_open_heads)
        if not result.get("errors") and not result.get("skipped"):
            reconcile_record_snapshots()
            marker.unlink()
        return result


def reconcile_record_snapshots() -> None:
    """Rebuild the optional main-branch publication outbox from durable record verdicts."""
    from . import records
    with local_lock("results"), SessionLocal() as session:
        for track in contract.tracks():
            sub = records.current_record(session, track["slug"])
            if (sub is not None and sub.current_contract and sub.detail_dict.get("source_ref")
                    and not sub.detail_dict.get("record_snapshot")):
                schedule_report(session, sub)
        session.commit()


def _resync(queue_open_heads: bool = True) -> dict:
    """Restore receipts and checked heads; caller holds the recovery barrier."""
    if not settings.github_token or not settings.submissions_repo:
        return {"skipped": "no GitHub token or submissions repository configured"}
    repo = settings.submissions_repo
    bot = (settings.bot_login or github.token_login()).lower()
    restored, pending, queued, errors, warnings = 0, 0, [], [], []
    for pr in github.list_pulls(repo):
        number, head = pr["number"], pr["head"]["sha"]
        pr_url = f"https://github.com/{repo}/pull/{number}"
        try:
            history = latest_verdicts(github.list_comments(repo, number), bot)
        except Exception as exc:
            errors.append(f"#{number}: comments unavailable ({type(exc).__name__})")
            continue
        verdicts = [v for v, _ in history]
        fields = github.parse_pr_body(pr.get("body") or "")
        head_repo = (pr["head"].get("repo") or {}).get("clone_url") or f"https://github.com/{repo}.git"
        for v, comment_id in history:
            t = contract.track(v["track"])
            if t is None:
                continue
            sid = v.get("id")
            pinned = bool(v.get("source_ref"))
            if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
                if pinned or v["status"] == "pending":
                    errors.append(f"#{number}: receipt has no valid submission id")
                    continue
                sid = legacy_pr_submission_id(repo, number, v["commit"])
            try:
                receipt = _receipt(v)
                if v["status"] == "pending" and receipt is None:
                    raise ValueError("pending entry has no durable source receipt")
                if pinned and v["source_ref"] != f"refs/tags/ots-source/{sid}":
                    raise ValueError("source ref belongs to another submission")
                if v["status"] == "pending":
                    github.verify_source_ref(repo, sid, v["commit"], v["source_ref"])
            except Exception as exc:
                errors.append(f"#{number} {sid}: receipt unavailable ({type(exc).__name__})")
                continue
            author = receipt["author"] if receipt else (pr.get("user") or {})
            if not isinstance(author.get("login"), str) or not github.LOGIN_RE.fullmatch(author["login"]):
                errors.append(f"#{number} {sid}: author unavailable")
                continue
            finished = _time(v.get("finished_at"))
            with local_lock("results"), SessionLocal() as session:
                existing = session.get(Submission, sid)
                if existing is not None:
                    if (existing.track != v["track"] or existing.commit != v["commit"]
                            or existing.pr_url != pr_url):
                        errors.append(f"#{number} {sid}: submission identity conflict")
                        continue
                    # GitHub was read before taking the results lock. An old comment
                    # must never roll a newer retry back, even before its receipt publishes.
                    old_receipt = existing.detail_dict.get("receipt") or {}
                    current_admission = _time(old_receipt.get("created_at"))
                    incoming_admission = _time(receipt["created_at"]) if receipt else None
                    if current_admission and (not incoming_admission or incoming_admission < current_admission):
                        continue
                    if (current_admission and v["status"] in FINISHED and
                            (not finished or finished < current_admission or
                             (existing.finished_at and finished < existing.finished_at))):
                        continue
                    # Running jobs stay put. Reconcile a strictly newer durable event,
                    # including a retry receipt or an admission stranded after publication.
                    if v["status"] == "pending":
                        if existing.status not in FINISHED | {"admitting"}:
                            continue
                        if existing.status in FINISHED and (not existing.finished_at or
                                _time(receipt["created_at"]) <= existing.finished_at):
                            continue
                    elif existing.status in FINISHED:
                        if not finished or (existing.finished_at and finished <= existing.finished_at):
                            continue
                    elif existing.status not in {"pending", "admitting", "publishing"}:
                        continue
                detail = {"contract": v.get("contract"), "restored": True,
                          "recorded_record": v.get("record") is True}
                if v["track"] == "upper-riscv" and v["status"] == "verified":
                    size = riscv_program_size.validate(v.get("riscv_program_size"), v["commit"], v.get("contract"))
                    if size:
                        detail["riscv_program_size"] = size
                if receipt:
                    detail.update(source_ref=v["source_ref"], receipt=receipt)
                if type(comment_id) is int:
                    detail["github_comment_id"] = comment_id
                failure = v.get("failure")
                if (v["status"] in FINISHED - {"verified"} and isinstance(failure, dict)
                        and isinstance(failure.get("code"), str) and isinstance(failure.get("message"), str)):
                    detail["failure"] = {"code": failure["code"][:120], "message": failure["message"][:4000]}
                if v.get("source_archive") is not None:
                    probe = Submission(track=v["track"], commit=v["commit"], detail=json.dumps(detail))
                    try:
                        detail["source_archive"] = source_archive.validate_metadata(v["source_archive"], probe)
                    except source_archive.ArchiveError:
                        detail["source_archive_error"] = True
                        warnings.append(f"#{number} {sid}: invalid source archive metadata")
                probe = Submission(track=v["track"], commit=v["commit"], detail=json.dumps(detail))
                notes = source_archive.read_notes(probe)
                if notes is None and v["status"] in FINISHED:
                    root = receipt["submission_root"] if receipt else t["submission_root"]
                    try:
                        notes = github.read_file(repo, f"{root}/NOTES.md", v["commit"])
                    except Exception as exc:
                        warnings.append(f"#{number} {sid}: notes unavailable ({type(exc).__name__})")
                if notes and notes.strip():
                    detail["notes"] = notes.strip()
                user = auth.get_or_create_user(session, author["login"], github_id=author.get("id"),
                                               avatar_url=author.get("avatar_url"))
                attribution = receipt or fields
                created = _time(receipt["created_at"]) if receipt else finished or _time(pr.get("created_at"))
                values = dict(
                    track=v["track"], user_id=user.id,
                    source_repo=f"https://github.com/{repo}.git" if pinned else head_repo,
                    commit=v["commit"], claim=v.get("claim") if v["status"] in FINISHED else None,
                    status=v["status"], description=attribution["description"],
                    co_authors=json.dumps(attribution["co_authors"]), assisted_by=attribution["assisted_by"],
                    pr_number=number, pr_url=pr_url, created_at=created,
                    finished_at=finished if v["status"] in FINISHED else None,
                    duration_s=v.get("duration_s") if v["status"] in FINISHED else None, detail=json.dumps(detail))
                if existing is None:
                    session.add(Submission(id=sid, **values))
                    restored += 1
                    pending += int(v["status"] == "pending")
                else:
                    for name, value in values.items():
                        setattr(existing, name, value)
                    existing.is_record, existing.record_at = False, None
                    # A new durable event must never inherit a different attempt's log.
                    existing.started_at, existing.log_path = None, None
                    pending += int(v["status"] == "pending")
                session.commit()
        if (queue_open_heads and pr.get("state") == "open"
                and not hall_of_fame.contains_pr_head(pr_url, head)) and head not in {
                v["commit"] for v in verdicts if v.get("contract") == contract.contract_id()}:
            with SessionLocal() as session:
                known = any(s.current_contract for s in session.scalars(select(Submission).where(
                    Submission.pr_url == pr_url, Submission.commit == head)))
            if not known:
                queued.append((repo, number, head))
    promoted = replay_records()
    admitted = pending
    if queued:
        from .main import handle_pull_request
        for repo_, number, head in queued:
            try:
                handle_pull_request(repo_, number, head, announce=False)
                admitted += 1
            except Exception as exc:
                errors.append(f"#{number}: not queued ({type(exc).__name__})")
    result = {"restored": restored, "promoted": promoted, "queued": admitted}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    return result


def replay_records() -> int:
    """Recompute the complete current frontier, including older verdicts found on a later sync.

    New verdicts retain unique microsecond completion times. For legacy second-resolution ties,
    keep the bot's recorded winner where available; PR/commit order is only a final fallback.
    """
    from .worker import promote
    with local_lock("results"), SessionLocal() as session:
        candidates = [s for s in session.scalars(select(Submission).where(
            Submission.status == "verified", Submission.claim.is_not(None),
            Submission.finished_at.is_not(None), Submission.pr_number.is_not(None)))
            if contract.track(s.track) is not None and s.current_contract and not s.detail_dict.get("demo")
            and (s.pr_repository or "").lower() == settings.submissions_repo.lower()]
        previous = {s.id for s in candidates if s.is_record}
        def order(sub):
            known_record = sub.detail_dict.get("recorded_record") or sub.is_record
            # Several original improvements can share a legacy rounded timestamp. Their
            # strict improvement order is recoverable from scores even when PR order differs.
            progress = sub.claim if contract.track(sub.track)["direction"] == "+" else -sub.claim
            return sub.finished_at, not known_record, progress if known_record else 0, sub.pr_number, sub.commit
        candidates.sort(key=order)
        for sub in candidates:
            sub.is_record, sub.record_at = False, None
        session.flush()
        for sub in candidates:
            promote(session, sub, at=sub.finished_at)
            session.flush()
        count = sum(s.is_record and s.id not in previous for s in candidates)
        session.commit()
    return count


def main() -> int:
    init_db()
    print(json.dumps(resync(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
