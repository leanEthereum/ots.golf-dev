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

from . import contract, github, record_snapshot, revalidations, riscv_program_size, source_archive
from .config import settings
from .db import GithubReport, SessionLocal, Submission, init_db, local_lock, schedule_report, utcnow

POLL_SECONDS = 3
TERMINAL_STATUSES = {"verified", "rejected", "policy_rejected", "timeout", "failed"}
RECEIPT_FIELDS = ("source_ref", "created_at", "author", "description", "co_authors",
                  "assisted_by", "contract_commit", "submission_root", "git_authors")


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
           "--hide", str(settings.data_dir), "--archive-dir", str(source_archive.directory()),
           "--archive-id", sub.id]
    timed_out = False
    proc = subprocess.Popen(cmd, cwd=settings.repo_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        # Preserve the existing proof/fetch allowance when the optional RISC-V
        # collector uses its full five-minute budget, including sandbox teardown.
        metadata_allowance = 330 if sub.track == "upper-riscv" else 0
        stdout, stderr = proc.communicate(timeout=limit + 600 + metadata_allowance)
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
    archive, archive_error = None, None
    try:
        archive = source_archive.recover_metadata(sub)
    except (source_archive.ArchiveError, OSError) as exc:
        archive_error = str(exc)
    shutil.rmtree(work, ignore_errors=True)
    if archive_error:
        return {"status": "failed", "reason": "source archive integrity failure: " + archive_error}, str(log_dst)
    if timed_out:
        with log_dst.open("a", encoding="utf-8") as log:
            log.write("\n[pipeline exceeded its outer time limit]\n")
        return {"status": "timeout", "reason": "pipeline exceeded its outer time limit",
                "source_archive": archive}, str(log_dst)
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
    if result["status"] == "verified" and archive is None:
        result = {"status": "failed", "reason": "verified result has no retained source archive"}
    # Only trusted durable metadata, never the subprocess's claimed archive descriptor.
    result["source_archive"] = archive
    return result, str(log_dst)


def best_record(session, sub: Submission) -> Submission | None:
    """The track's best record other than `sub`. Invented demo rows never count."""
    t = contract.track(sub.track)
    order = Submission.claim.desc() if t["direction"] == "+" else Submission.claim.asc()
    records = session.scalars(select(Submission).where(
        Submission.track == sub.track, Submission.status == "verified", Submission.is_record.is_(True),
        Submission.id != sub.id, Submission.claim.is_not(None)).order_by(order))
    return next((r for r in records if r.current_contract
                 and not r.detail_dict.get("demo") and not revalidations.is_check(r)), None)


def beats_record(session, sub: Submission) -> bool:
    """Whether this verified claim strictly improves the track's current record; the first verified
    claim of a track without a record does."""
    t = contract.track(sub.track)
    if t is None or sub.claim is None or revalidations.is_check(sub):
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


def reported_status(sub: Submission) -> str:
    if sub.status == "admitting":
        return "pending"
    if sub.status == "publishing":
        status = sub.detail_dict.get("publication_status")
        if status not in TERMINAL_STATUSES:
            raise ValueError("publishing submission has no terminal verdict")
        return status
    return sub.status


def verdict_entry(sub: Submission) -> dict:
    """The frozen receipt and verdict needed to rebuild this checked head."""
    detail = sub.detail_dict
    receipt = detail.get("receipt")
    entry = {key: receipt[key] for key in RECEIPT_FIELDS if isinstance(receipt, dict) and key in receipt}
    if detail.get("source_ref"):
        entry["source_ref"] = detail["source_ref"]
        entry.setdefault("created_at", sub.created_at.isoformat(timespec="microseconds") + "Z"
                         if sub.created_at else None)
    failure = detail.get("failure")
    failure = ({"code": str(failure.get("code", ""))[:32],
                "message": str(failure.get("message", ""))[:1200]}
               if isinstance(failure, dict) else None)
    status = reported_status(sub)
    # Retrying a supplementary commit status must not erase a running job's durable receipt.
    if detail.get("source_ref") and status == "verifying":
        status = "pending"
    entry.update(id=sub.id, track=sub.track, commit=sub.commit, status=status, claim=sub.claim,
                 duration_s=sub.duration_s,
                 finished_at=sub.finished_at.isoformat(timespec="microseconds") + "Z" if sub.finished_at else None,
                 contract=detail.get("contract"), record=bool(sub.is_record),
                 source_archive=detail.get("source_archive"), failure=failure)
    if sub.track == "upper-riscv" and status == "verified":
        size = riscv_program_size.validate(detail.get("riscv_program_size"), sub.commit, detail.get("contract"))
        if size:
            entry["riscv_program_size"] = size
    return entry


class CommentPublishedError(Exception):
    """The comment is durable; its record snapshot or supplementary status needs retrying."""
    def __init__(self, comment_id: int, error: Exception):
        self.comment_id = comment_id
        self.error = error
        super().__init__(str(error))


def publish_comment(sub: Submission, body: str) -> int | None:
    comment_id = sub.detail_dict.get("github_comment_id")
    if type(comment_id) is int:
        try:
            github.update_comment(sub.pr_repository, comment_id, body)
            return comment_id
        except github.httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
    return github.post_comment(sub.pr_repository, sub.pr_number, body)


def report(sub: Submission, history: list[dict] | None = None, *, publish_snapshot: bool = False) -> int | None:
    """New retained-source heads publish their own durable comment before a commit status.

    Preserve legacy aggregate comments: several historical rows may share their comment ID.
    Snapshot publication requires eligibility computed by the caller under the results lock.
    """
    repo = sub.pr_repository
    if not repo or not settings.submissions_repo or repo.lower() != settings.submissions_repo.lower():
        raise ValueError("the submission does not belong to the configured submissions repository")
    url = f"{settings.base_url}/submissions/{sub.id}"
    status = reported_status(sub)
    durable = bool(sub.detail_dict.get("source_ref"))
    if status in {"pending", "verifying"}:
        state, what = "pending", "queued for verification" if status == "pending" else "verification in progress"
        body = f"**ots.golf verifier:** {what}. Details: {url}"
    elif status == "verified":
        if (origin := revalidations.for_check(sub)) is not None:
            what = f"verified: claim {sub.claim} — proof update for {origin['original_author']}"
        else:
            what = f"verified: claim {sub.claim}" + (" — new record" if sub.is_record else " (not a record)")
        state, body = "success", f"**ots.golf verifier:** {what}. Details: {url}"
    else:
        failure = (sub.detail_dict.get("failure") or {}).get("message", "")
        what = f"{status}: {failure}"[:140] if failure else status
        state = "error" if status == "failed" else "failure"
        quoted = failure[:600].replace("```", "'''").replace("<!--", "<!​--")
        body = f"**ots.golf verifier:** `{status}`.\n\n```\n{quoted}\n```\n\nDetails: {url}"
    entries = ([verdict_entry(sub)] if durable else
               [e for e in (history or [verdict_entry(sub)])
                if not e.get("source_ref") and e["status"] not in {"pending", "verifying"}])
    if entries:
        body += "\n\n" + github.verdict_block(entries)
    if not sub.current_contract:
        body = "**Historical contract result; excluded from the current competition.**\n\n" + body
    if not durable and sub.current_contract:
        github.post_status(repo, sub.commit, state, what, url)
    comment_id = publish_comment(sub, body)
    if durable:
        if type(comment_id) is not int or comment_id <= 0:
            raise ValueError("GitHub did not confirm a durable comment identity")
        if sub.current_contract:
            try:
                if publish_snapshot and status == "verified" and sub.is_record:
                    snapshot = record_snapshot.publish_record(sub)
                    detail = sub.detail_dict
                    detail["record_snapshot"] = snapshot
                    sub.detail = json.dumps(detail)
                github.post_status(repo, sub.commit, state, what, url)
            except Exception as exc:
                # The result is already durable. Retry publishing the record snapshot or
                # status through the outbox without repeating the proof.
                raise CommentPublishedError(comment_id, exc) from exc
    return comment_id


def report_backoff(pending: GithubReport) -> None:
    pending.attempts += 1
    pending.next_attempt = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(pending.attempts, 7)))


def deliver_durable_report(sub_id: str) -> None:
    # Hold this lock through the external write. Later record decisions cannot overtake an
    # unpublished result, and tentative promotion stays only on a detached snapshot.
    with local_lock("results"), SessionLocal() as session:
        pending = session.get(GithubReport, sub_id)
        current = session.get(Submission, sub_id)
        if pending is None or current is None or pending.next_attempt > utcnow():
            return
        if (current.pr_repository or "").lower() != settings.submissions_repo.lower():
            return
        version, original_status = pending.version, current.status
        snapshot = Submission(**{column.name: getattr(current, column.name)
                                 for column in Submission.__table__.columns})
        error, comment_id = None, None
        try:
            if original_status == "publishing":
                snapshot.status = reported_status(current)
                snapshot.is_record, snapshot.record_at = False, None
                promote(session, snapshot)
            # Historical improvements retain is_record for their verdict and chart. Only
            # the local frontier may update main, even if its newer snapshot is still pending.
            # beats_record excludes this row, so it also handles a detached new improvement.
            publish_snapshot = (snapshot.status == "verified" and snapshot.is_record
                                and snapshot.current_contract and beats_record(session, snapshot))
            comment_id = report(snapshot, publish_snapshot=publish_snapshot)
        except CommentPublishedError as exc:
            comment_id, error = exc.comment_id, exc.error
        except Exception as exc:
            error = exc
        if error is not None:
            _log(f"GitHub report for {sub_id} failed: {type(error).__name__}; queued for retry")
        # Admission may schedule a newer outbox version while the request is running.
        session.expire_all()
        pending = session.get(GithubReport, sub_id)
        current = session.get(Submission, sub_id)
        if pending is None or current is None:
            return
        detail = current.detail_dict
        published = type(comment_id) is int and comment_id > 0
        if published:
            detail["github_comment_id"] = comment_id
        if pending.version == version:
            if snapshot.detail_dict.get("record_snapshot") is not None:
                detail["record_snapshot"] = snapshot.detail_dict["record_snapshot"]
            if published and current.status == original_status:
                if original_status == "admitting":
                    current.status = "pending"
                elif original_status == "publishing":
                    current.status = snapshot.status
                    current.is_record, current.record_at = snapshot.is_record, snapshot.record_at
                    detail.pop("publication_status", None)
            if error is None and published:
                session.delete(pending)
            else:
                report_backoff(pending)
        current.detail = json.dumps(detail)
        session.commit()


def deliver_report(sub_id: str) -> None:
    # Recovery imports rows incrementally, then reconstructs the complete record frontier.
    with local_lock("recovery", shared=True):
        if (settings.data_dir / "recovery.incomplete").exists():
            return
        _deliver_report(sub_id)


def _deliver_report(sub_id: str) -> None:
    if not settings.submissions_repo or not settings.github_token:
        return
    with SessionLocal() as session:
        pending = session.get(GithubReport, sub_id)
        sub = session.get(Submission, sub_id)
        if pending is None or sub is None or pending.next_attempt > utcnow():
            return
        if (sub.pr_repository or "").lower() != settings.submissions_repo.lower():
            return
        durable = bool(sub.detail_dict.get("source_ref"))
        version = pending.version
        history = [] if durable else [verdict_entry(s) for s in session.scalars(
            select(Submission).where(func.lower(Submission.pr_url) == (sub.pr_url or "").lower())
            .order_by(Submission.created_at)) if not s.detail_dict.get("source_ref")]
    if durable:
        deliver_durable_report(sub_id)
        return
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
                report_backoff(pending)
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
                    Submission.track.in_([t["slug"] for t in contract.tracks()]),
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
    with local_lock("recovery", shared=True), local_lock("results"), SessionLocal() as session:
        if (settings.data_dir / "recovery.incomplete").exists():
            return
        sub = session.get(Submission, sub_id)
        publishing = session.scalar(select(Submission.id).where(
            Submission.status == "publishing",
            Submission.track.in_([t["slug"] for t in contract.tracks()])).limit(1))
        if sub is None or contract.track(sub.track) is None or sub.status != "pending" or publishing is not None:
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
    # A running proof may finish during recovery. Store its result after the import;
    # the persistent marker still prevents publication if recovery was incomplete.
    with local_lock("recovery", shared=True), local_lock("results"), SessionLocal() as session:
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
        detail.pop("riscv_program_size", None)
        raw_size = result.get("riscv_program_size")
        if sub.track == "upper-riscv" and sub.status == "verified" and isinstance(raw_size, dict):
            size = riscv_program_size.validate({**raw_size, "version": 1, "commit": sub.commit,
                                               "contract": detail.get("contract")}, sub.commit, detail.get("contract"))
            if size:
                detail["riscv_program_size"] = size
        notes = result.get("notes")
        if isinstance(notes, str) and notes.strip():
            detail["notes"] = notes[:64 * 1024]
        else:
            detail.pop("notes", None)
        if result.get("source_archive") is not None:
            try:
                detail["source_archive"] = source_archive.validate_metadata(result["source_archive"], sub)
            except source_archive.ArchiveError:
                sub.status = "failed"
                detail["failure"] = {"code": "failed", "message": "invalid source archive metadata"}
        if detail.get("source_ref"):
            detail["publication_status"] = sub.status
            sub.status, sub.is_record, sub.record_at = "publishing", False, None
        sub.detail = json.dumps(detail)
        if sub.status != "publishing":
            promote(session, sub)
        schedule_report(session, sub)
        session.commit()
        _log(f"{sub.id}: {sub.status}" + (f" claim {sub.claim}" + (" RECORD" if sub.is_record else "") if sub.status == "verified" else ""))


def work_loop() -> None:
    # Only the lock holder can reset interrupted jobs. Do this once at startup, never while another
    # worker is actively verifying a proof.
    with SessionLocal() as session:
        for sub in session.scalars(select(Submission).where(
                Submission.status == "verifying",
                Submission.track.in_([t["slug"] for t in contract.tracks()]))):
            sub.status = "pending"
        session.commit()
    while True:
        with SessionLocal() as session:
            publishing = session.scalar(select(Submission.id).where(
                Submission.status == "publishing",
                Submission.track.in_([t["slug"] for t in contract.tracks()])).limit(1))
            blocked = publishing is not None or (settings.data_dir / "recovery.incomplete").exists()
            sub_id = None if blocked else session.scalar(
                select(Submission.id).where(Submission.status == "pending",
                    Submission.track.in_([t["slug"] for t in contract.tracks()]))
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
