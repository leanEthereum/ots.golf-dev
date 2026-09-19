"""One-host verifier worker with a durable GitHub result outbox.

Verification checks a proof. A verified head that strictly improves its track's record when its check
finishes becomes the record; GitHub only receives the verdict (a commit status and a comment).
Run with ``.venv/bin/python -m app.worker``; a file lock prevents concurrent workers.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import timedelta

from sqlalchemy import func, select

from . import contract, github
from .config import settings
from .db import GithubReport, SessionLocal, Submission, init_db, local_lock, schedule_report, utcnow

POLL_SECONDS = 3


def _log(msg: str) -> None:
    print(f"[worker {utcnow().isoformat(timespec='seconds')}] {msg}", flush=True)


def _stop_pipeline(proc) -> tuple[str, str]:
    """Let verify.py clean up its sandbox/cgroup, then kill remaining children if necessary."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return proc.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return proc.communicate(timeout=10)


def run_pipeline(sub: Submission) -> tuple[dict, str | None]:
    """Run the trusted verifier and accept only a matching, successful result."""
    cfg = contract.load()
    limit = cfg["limits"]["wall_clock_seconds"]
    work = settings.work_dir / sub.id
    shutil.rmtree(work, ignore_errors=True)
    cmd = [sys.executable, str(settings.repo_root / "verifier" / "verify.py"), sub.track,
           "--source", sub.source_repo, "--commit", sub.commit, "--json", "--keep", "--work", str(work),
           "--hide", str(settings.data_dir)]
    timed_out = False
    proc = subprocess.Popen(cmd, cwd=settings.repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=limit + 600)
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr = _stop_pipeline(proc)
    except BaseException:
        _stop_pipeline(proc)
        raise
    log_dst = settings.data_dir / "logs" / f"{sub.id}.log"
    src_log = work / "verify.log"
    if src_log.is_file():
        shutil.copyfile(src_log, log_dst)
    else:
        log_dst.write_text(stdout + "\n" + stderr, encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    if timed_out:
        with log_dst.open("a", encoding="utf-8") as log:
            log.write("\n[pipeline exceeded its outer time limit]\n")
        return {"status": "timeout", "reason": "pipeline exceeded its outer time limit"}, str(log_dst)
    try:
        result = json.loads(stdout)
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise ValueError("missing status")
        if result["status"] == "verified" and (
            proc.returncode != 0 or result.get("track") != sub.track or result.get("commit") != sub.commit
            or type(result.get("claim")) is not int or not 0 <= result["claim"] <= cfg["limits"]["max_claim"]
        ):
            raise ValueError("verified result does not match the queued head or claim limits")
    except (ValueError, TypeError):
        result = {"status": "failed", "reason": f"verify.py exited {proc.returncode} without a valid matching result"}
    return result, str(log_dst)


def best_record(session, sub: Submission) -> Submission | None:
    """The track's best record other than `sub`. Invented demo rows never count."""
    t = contract.track(sub.track)
    order = Submission.claim.desc() if t["direction"] == "+" else Submission.claim.asc()
    records = session.scalars(select(Submission).where(
        Submission.track == sub.track, Submission.status == "verified", Submission.is_record.is_(True),
        Submission.id != sub.id, Submission.claim.is_not(None)).order_by(order))
    return next((r for r in records if r.current_contract and not r.detail_dict.get("demo")), None)


def beats_record(session, sub: Submission) -> bool:
    """Whether this verified claim strictly improves the track's current record; the first verified
    claim of a track without a record does."""
    t = contract.track(sub.track)
    if t is None or sub.claim is None:
        return False
    best = best_record(session, sub)
    return contract.improves(t["direction"], sub.claim, best.claim if best else None)


def promote(session, sub: Submission, at=None) -> None:
    """Make a verified pull-request head the record if it strictly improves the track's current record
    (or the track has none). Callers hold the results lock, so records are decided one at a time in
    the order verifications finish: a later copy of the same claim never improves. A rebuild passes
    the original finish time as `at`."""
    if sub.status != "verified" or sub.claim is None or sub.is_record or not sub.current_contract:
        return
    if not settings.submissions_repo or (sub.pr_repository or "").lower() != settings.submissions_repo.lower():
        return
    if beats_record(session, sub):
        sub.is_record = True
        sub.record_at = at or sub.finished_at or utcnow()


def verdict_entry(sub: Submission) -> dict:
    """What a rebuild needs to restore one checked head."""
    return {"id": sub.id, "track": sub.track, "commit": sub.commit, "status": sub.status, "claim": sub.claim,
            "duration_s": sub.duration_s,
            "finished_at": sub.finished_at.isoformat(timespec="microseconds") + "Z" if sub.finished_at else None,
            "contract": sub.detail_dict.get("contract"), "record": bool(sub.is_record)}


def report(sub: Submission, history: list[dict] | None = None) -> int | None:
    """Publish a verdict; retain the comment ID so later updates edit the same comment."""
    repo = sub.pr_repository
    if not repo or not settings.submissions_repo or repo.lower() != settings.submissions_repo.lower():
        raise ValueError("the submission does not belong to the configured submissions repository")
    url = f"{settings.base_url}/submissions/{sub.id}"
    if sub.status in {"pending", "verifying"}:
        state, what = "pending", "queued for verification" if sub.status == "pending" else "verification in progress"
        body = f"**ots.golf verifier:** {what}. Details: {url}"
    elif sub.status == "verified":
        what = f"verified: claim {sub.claim}" + (" — new record" if sub.is_record else " (not a record)")
        state, body = "success", f"**ots.golf verifier:** {what}. Details: {url}"
    else:
        failure = (sub.detail_dict.get("failure") or {}).get("message", "")
        what = f"{sub.status}: {failure}"[:140] if failure else sub.status
        state = "error" if sub.status == "failed" else "failure"
        quoted = failure[:600].replace("```", "'''").replace("<!--", "<!​--")
        body = f"**ots.golf verifier:** `{sub.status}`.\n\n```\n{quoted}\n```\n\nDetails: {url}"
    finished = [e for e in (history or [verdict_entry(sub)]) if e["status"] not in {"pending", "verifying"}]
    if finished:
        body += "\n\n" + github.verdict_block(finished)
    if sub.current_contract:
        github.post_status(repo, sub.commit, state, what, url)
    else:
        body = "**Historical contract result; excluded from the current competition.**\n\n" + body
    comment_id = sub.detail_dict.get("github_comment_id")
    if type(comment_id) is int:
        try:
            github.update_comment(repo, comment_id, body)
            return comment_id
        except github.httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            # A maintainer may have deleted the earlier comment. Recreate it on the same PR.
    return github.post_comment(repo, sub.pr_number, body)


def deliver_report(sub_id: str) -> None:
    if not settings.submissions_repo or not settings.github_token:
        return
    with SessionLocal() as session:
        pending = session.get(GithubReport, sub_id)
        sub = session.get(Submission, sub_id)
        if pending is None or sub is None or pending.next_attempt > utcnow():
            return
        if (sub.pr_repository or "").lower() != settings.submissions_repo.lower():
            return
        version = pending.version
        history = [verdict_entry(s) for s in session.scalars(
            select(Submission).where(func.lower(Submission.pr_url) == (sub.pr_url or "").lower())
            .order_by(Submission.created_at))]
    error, comment_id = None, None
    try:
        comment_id = report(sub, history)
    except Exception as exc:  # network failure is retried independently of expensive verification
        error = exc
        _log(f"GitHub report for {sub_id} failed: {type(exc).__name__}; queued for retry")
    with local_lock("results"), SessionLocal() as session:
        pending = session.get(GithubReport, sub_id)
        current = session.get(Submission, sub_id)
        if pending is None or current is None:
            return
        if comment_id is not None:
            detail = current.detail_dict
            detail["github_comment_id"] = comment_id
            current.detail = json.dumps(detail)
        if pending.version == version:
            if error is None:
                session.delete(pending)
            else:
                pending.attempts += 1
                pending.next_attempt = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(pending.attempts, 7)))
        session.commit()


def retry_reports() -> None:
    if not settings.submissions_repo or not settings.github_token:
        return
    # Web processes own GitHub credentials; only one of them delivers the shared outbox at a time.
    try:
        with local_lock("reports", blocking=False):
            with SessionLocal() as session:
                ids = list(session.scalars(select(GithubReport.submission_id).join(Submission).where(
                    GithubReport.next_attempt <= utcnow(),
                    func.lower(Submission.pr_url).startswith(
                        f"https://github.com/{settings.submissions_repo.lower()}/pull/", autoescape=True)
                ).order_by(GithubReport.next_attempt).limit(20)))
            for sub_id in ids:
                deliver_report(sub_id)
    except BlockingIOError:
        return


def next_finish_time(session):
    """Serialize completion timestamps as well as record decisions, including clock rollback."""
    now = utcnow()
    prior = max((s.finished_at for s in session.scalars(select(Submission).where(
        Submission.finished_at.is_not(None))) if not s.detail_dict.get("demo")), default=None)
    return max(now, prior + timedelta(microseconds=1)) if prior else now


def process(sub_id: str) -> None:
    with SessionLocal() as session:
        sub = session.get(Submission, sub_id)
        if sub is None or sub.status != "pending":
            return
        sub.status, sub.started_at = "verifying", utcnow()
        session.commit()
    _log(f"verifying {sub.id} ({sub.track}, {sub.source_repo}@{sub.commit[:10]})")
    run_contract = contract.contract_id()
    try:
        if not sub.current_contract:
            result, log_path = {"status": "failed", "reason": "queued contract changed; resubmit for the current contract"}, None
        else:
            result, log_path = run_pipeline(sub)
    except Exception:
        _log(traceback.format_exc())
        result, log_path = {"status": "failed", "reason": "internal error in the verifier; the operator has the trace"}, None
    with local_lock("results"), SessionLocal() as session:
        sub = session.get(Submission, sub_id)
        if sub is None:
            return
        if result.get("status") == "verified" and contract.contract_id() != run_contract:
            result = {"status": "failed", "reason": "contract changed during verification; resubmit"}
        sub.status = result["status"] if result["status"] in ("verified", "rejected", "policy_rejected", "timeout") else "failed"
        sub.claim = result.get("claim", sub.claim)
        sub.finished_at, sub.duration_s, sub.log_path = next_finish_time(session), result.get("duration_s"), log_path
        failure = None
        if sub.status != "verified":
            msg = result.get("reason") or "; ".join(result.get("errors", [])) or result.get("tail", "")[-600:]
            failure = {"code": sub.status, "message": msg}
        detail = sub.detail_dict  # preserve the durable comment identity
        detail.update(failure=failure, commit=result.get("commit"), comparator_exit=result.get("comparator_exit"),
                      contract=sub.detail_dict.get("contract"))
        notes = result.get("notes")
        if isinstance(notes, str) and notes.strip():
            detail["notes"] = notes[:64 * 1024]
        else:
            detail.pop("notes", None)
        sub.detail = json.dumps(detail)
        promote(session, sub)
        schedule_report(session, sub)
        session.commit()
        _log(f"{sub.id}: {sub.status}" + (f" claim {sub.claim}" + (" RECORD" if sub.is_record else "") if sub.status == "verified" else ""))


def work_loop() -> None:
    # Only the lock holder can reset interrupted jobs. Do this once at startup, never while another
    # worker is actively verifying a proof.
    with SessionLocal() as session:
        for sub in session.scalars(select(Submission).where(Submission.status == "verifying")):
            sub.status = "pending"
        session.commit()
    while True:
        with SessionLocal() as session:
            sub_id = session.scalar(select(Submission.id).where(Submission.status == "pending")
                                    .order_by(Submission.created_at.asc()).limit(1))
        if sub_id:
            process(sub_id)
        else:
            time.sleep(POLL_SECONDS)


def main() -> None:
    if settings.environment == "production" and settings.role != "worker":
        raise SystemExit("the production verifier must run with OTS_ROLE=worker and no GitHub secrets")
    def shutdown(signum, _frame):
        # Raising through run_pipeline triggers its process-group cleanup on a service stop.
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, shutdown)
    init_db()
    _log(f"repo {settings.repo_root}, state {settings.data_dir}")
    try:
        with local_lock("worker", blocking=False):
            work_loop()
    except BlockingIOError:
        raise SystemExit("another verifier worker already holds this data directory") from None


if __name__ == "__main__":
    main()
