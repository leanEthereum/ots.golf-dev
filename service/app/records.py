"""Leaderboard queries: the current record, the record frontier, the in-flight submissions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import contract
from .db import Submission


def eligible(sub: Submission) -> bool:
    """Unversioned and historical results are never evidence for the current contract."""
    return sub.current_contract or bool(sub.detail_dict.get("demo"))


def _verified(slug: str):
    return select(Submission).where(Submission.track == slug, Submission.status == "verified")


def current_record(session: Session, slug: str) -> Submission | None:
    t = contract.track(slug)
    order = Submission.claim.desc() if t["direction"] == "+" else Submission.claim.asc()
    return next((s for s in session.scalars(_verified(slug).where(
        Submission.is_record.is_(True), Submission.claim.is_not(None))
        .order_by(order, Submission.finished_at.asc())) if eligible(s)), None)


def frontier(session: Session, slug: str) -> list[Submission]:
    progress = Submission.claim.desc() if contract.track(slug)["direction"] == "+" else Submission.claim.asc()
    return [s for s in session.scalars(_verified(slug).where(
        Submission.is_record.is_(True), Submission.claim.is_not(None))
        .order_by(Submission.record_at.desc(), progress)) if eligible(s)]


def in_flight(session: Session, slug: str | None = None) -> list[Submission]:
    q = select(Submission).where(Submission.status.in_(("pending", "verifying")))
    if slug:
        q = q.where(Submission.track == slug)
    return list(session.scalars(q.order_by(Submission.created_at.asc())))


def solver_count(session: Session, slug: str) -> int:
    return len({s.user_id for s in session.scalars(_verified(slug)) if eligible(s)})


def track_state(session: Session, t: dict) -> dict:
    rec = current_record(session, t["slug"])
    return {
        "slug": t["slug"], "title": t["title"], "direction": t["direction"],
        "cost_unit": contract.cost_unit(t),
        "record_claim": rec.claim if rec else None,
        "record_verified": rec is not None,
        "record_demo": bool(rec and rec.detail_dict.get("demo")),
        "record_submission_id": rec.id if rec else None,
        "record_setter": rec.user.login if rec else None,
        "record_at": rec.record_at.isoformat() + "Z" if rec and rec.record_at else None,
        "solvers": solver_count(session, t["slug"]),
        "in_flight": len(in_flight(session, t["slug"])),
    }


def interval(session: Session, framework: str = "generality-2") -> dict:
    cfg = contract.load()
    pair = contract.framework_tracks(framework)
    return {"framework": framework,
            "lower": track_state(session, pair["lower"]) if "lower" in pair else None,
            "upper": track_state(session, pair["upper"]) if "upper" in pair else None,
            "contract": {"version": cfg["contract"]["version"], "id": contract.contract_id(),
                         "commit": contract.trusted_commit()}}


def curve(session: Session, slug: str) -> list[dict]:
    """Every record of a track in the order it was set: the step curve of the record over time."""
    progress = Submission.claim.asc() if contract.track(slug)["direction"] == "+" else Submission.claim.desc()
    recs = list(session.scalars(_verified(slug).where(Submission.is_record.is_(True), Submission.claim.is_not(None),
                                                   Submission.record_at.is_not(None))
                                .order_by(Submission.record_at.asc(), progress)))
    return [{"t": s.record_at, "claim": s.claim, "id": s.id, "login": s.user.login,
             "demo": bool(s.detail_dict.get("demo"))} for s in recs if eligible(s)]


def overview(session: Session) -> list[dict]:
    """The three lower-bound classes; upper constructions use the generic interface only."""
    result = []
    for framework in contract.frameworks():
        boards = {}
        for kind, track in contract.framework_tracks(framework["slug"]).items():
            if kind != "lower":
                continue
            boards[kind] = board(session, track)
        result.append({**framework, "boards": boards})
    return result


def track_label(t: dict) -> tuple[str, str]:
    """The one-line name of a track and the leaderboard section it links to."""
    if t["kind"] == "lower":
        return "Lower bound · " + contract.track_framework_title(t), f'/?framework={t["framework"]}#lower'
    if t["framework"] != "generality-3" and t["slug"] != "upper-riscv":
        return contract.track_framework_title(t), "/rules#legacy-certificates"
    return "Upper bound · " + ("RISC-V cycles" if t["slug"] == "upper-riscv" else "compressions"), f'/?upper={t["slug"]}#upper'


def journal(session: Session, track: str | None = None, limit: int = 300, per_author: int = 20) -> list[dict]:
    """Notes of checked submissions, newest first: records, non-records and proofs the checker
    rejected, so ideas and dead ends stay readable. Only the latest checked head of each pull
    request counts, submissions refused before any proof check (format, infrastructure) are left
    out, and each author has at most `per_author` entries, so no one can flood the journal."""
    q = select(Submission).where(Submission.status.in_(("verified", "rejected", "timeout")))
    if track:
        q = q.where(Submission.track == track)
    items, seen_prs, by_author = [], set(), {}
    for s in session.scalars(q.order_by(func.coalesce(Submission.finished_at, Submission.created_at).desc())):
        if not s.notes or not contract.track(s.track):
            continue
        if s.pr_url:
            if s.pr_url in seen_prs:
                continue
            seen_prs.add(s.pr_url)
        if by_author.get(s.user_id, 0) >= per_author:
            continue
        by_author[s.user_id] = by_author.get(s.user_id, 0) + 1
        t = contract.track(s.track)
        label, href = track_label(t)
        items.append({"sub": s, "cfg": t, "label": label, "href": href})
        if len(items) >= limit:
            break
    return items


def latest_records(session: Session, limit: int = 8) -> list[dict]:
    """The most recent record-setting submissions across every public track, newest first."""
    cfg = contract.load()
    public = {f["lower_track"] for f in cfg["frameworks"] if "lower_track" in f} | set(cfg["upper_tracks"])
    items = []
    for t in contract.tracks():
        if t["slug"] not in public:
            continue
        recs = frontier(session, t["slug"])
        for i, s in enumerate(recs):
            prev = recs[i + 1] if i + 1 < len(recs) else None
            label, href = track_label(t)
            items.append({"sub": s, "cfg": t, "label": label, "href": href,
                          "gain": (s.claim - prev.claim) if prev and prev.claim is not None else None})
    items.sort(key=lambda x: x["sub"].record_at or x["sub"].finished_at or x["sub"].created_at, reverse=True)
    return items[:limit]


def board(session: Session, track: dict) -> dict:
    return {"cfg": track, "state": track_state(session, track),
            "frontier": frontier(session, track["slug"]),
            "in_flight": in_flight(session, track["slug"]),
            "curve": curve(session, track["slug"])}
