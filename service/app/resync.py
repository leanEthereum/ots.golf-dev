"""Rebuild the database from GitHub, so the server holds nothing that cannot be recreated.

    .venv/bin/python -m app.resync

GitHub keeps everything durable: pull requests (author, description, attribution, head commits),
each head's code and NOTES.md under refs/pull/<N>/head, and every verdict in the hidden block of the
verifier's own comment. A rebuild reads them back, decides records by replaying the verified verdicts
in the order their verifications finished, and queues any open head that has no verdict yet. It only
adds what is missing, so running it on a live database is harmless.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import select

from . import auth, contract, github
from .config import settings
from .db import SessionLocal, Submission, init_db, local_lock, pr_submission_id, legacy_pr_submission_id

FINISHED = {"verified", "rejected", "policy_rejected", "timeout", "failed"}


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def resync(queue_open_heads: bool = True) -> dict:
    """Restore every pull request's checked heads. Returns counts for the log."""
    if not settings.github_token or not settings.submissions_repo:
        return {"skipped": "no GitHub token or submissions repository configured"}
    repo = settings.submissions_repo
    bot = (settings.bot_login or github.token_login()).lower()
    restored, queued = 0, []
    for pr in github.list_pulls(repo):
        number, head = pr["number"], pr["head"]["sha"]
        pr_url = f"https://github.com/{repo}/pull/{number}"
        author = pr.get("user") or {}
        if not github.LOGIN_RE.fullmatch(author.get("login") or ""):
            continue
        verdicts, comment_id = [], None
        for c in github.list_comments(repo, number):
            if ((c.get("user") or {}).get("login") or "").lower() == bot:
                found = github.parse_verdicts(c.get("body") or "")
                if found:
                    verdicts, comment_id = found, c.get("id")
        fields = github.parse_pr_body(pr.get("body") or "")
        head_repo = (pr["head"].get("repo") or {}).get("clone_url") or f"https://github.com/{repo}.git"
        with local_lock("results"), SessionLocal() as session:
            user = auth.get_or_create_user(session, author["login"], github_id=author.get("id"),
                                           avatar_url=author.get("avatar_url"))
            for v in verdicts:
                t = contract.track(v["track"])
                if t is None or v["status"] not in FINISHED:
                    continue
                # New comments carry their stable identity; old links retain the legacy identity.
                sid = v.get("id")
                if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
                    sid = legacy_pr_submission_id(repo, number, v["commit"])
                if session.get(Submission, sid) is not None:
                    continue
                detail = {"contract": v.get("contract"), "restored": True}
                if type(comment_id) is int:
                    detail["github_comment_id"] = comment_id
                notes = github.read_file(repo, f'{t["submission_root"]}/NOTES.md', v["commit"])
                if notes and notes.strip():
                    detail["notes"] = notes.strip()
                finished = _time(v.get("finished_at"))
                session.add(Submission(
                    id=sid, track=v["track"], user_id=user.id, source_repo=head_repo, commit=v["commit"],
                    claim=v.get("claim"), status=v["status"], description=fields["description"],
                    co_authors=json.dumps(fields["co_authors"]), assisted_by=fields["assisted_by"],
                    pr_number=number, pr_url=pr_url, created_at=finished or _time(pr.get("created_at")),
                    finished_at=finished, duration_s=v.get("duration_s"), detail=json.dumps(detail)))
                restored += 1
            session.commit()
        if queue_open_heads and pr.get("state") == "open" and head not in {v["commit"] for v in verdicts if v.get("contract") == contract.contract_id()}:
            with SessionLocal() as session:
                known = any(s.current_contract for s in session.scalars(select(Submission).where(
                    Submission.pr_url == pr_url, Submission.commit == head)))
            if not known:
                queued.append((repo, number, head))
    promoted = replay_records()
    if queued:
        from .main import handle_pull_request
        for repo_, number, head in queued:
            try:
                handle_pull_request(repo_, number, head, announce=False)
            except Exception as exc:  # one unreachable pull request must not stop the rebuild
                print(f"resync: #{number} not queued: {type(exc).__name__}", flush=True)
    return {"restored": restored, "promoted": promoted, "queued": len(queued)}


def replay_records() -> int:
    """Decide records as the live worker would have: verified heads in the order their verifications
    finished (ties by pull request, then commit), each one a record if it strictly improves the record
    at that moment. Records already held are kept; demo rows never count."""
    from .worker import promote
    count = 0
    with local_lock("results"), SessionLocal() as session:
        candidates = session.scalars(select(Submission).where(
            Submission.status == "verified", Submission.is_record.is_(False), Submission.claim.is_not(None),
            Submission.finished_at.is_not(None), Submission.pr_number.is_not(None)))
        for sub in sorted(candidates, key=lambda s: (s.finished_at, s.pr_number, s.commit)):
            if sub.detail_dict.get("demo"):
                continue
            promote(session, sub, at=sub.finished_at)
            session.flush()
            count += sub.is_record
        session.commit()
    return count


def main() -> int:
    init_db()
    print(json.dumps(resync(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
