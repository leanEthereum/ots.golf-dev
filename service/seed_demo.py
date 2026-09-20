"""Phony leaderboard data for local development.

Loads versioned demo/submissions.json into a local database. The fictional submissions
exercise record presentation; they carry a demo label and never show verification badges or commit links.
Everything it adds is marked with `detail = {"demo": true}` and `--remove` deletes it again. Claims
are fixed in the fixture file; real submissions are left alone.

    .venv/bin/python seed_demo.py           # reconcile fixtures, preserving existing IDs and dates
    .venv/bin/python seed_demo.py --force   # the same against a database that is not the local one
    .venv/bin/python seed_demo.py --remove  # remove the phony rows only
    .venv/bin/python seed_demo.py --refresh # reconcile claims and add missing fixtures, preserving existing rows
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from sqlalchemy import select

from app import contract
from app.db import Base, Submission, User, engine, SessionLocal, stable_id, utcnow

DEMO = {"demo": True}
NOW = utcnow().replace(microsecond=0)

FIXTURE_PATH = Path(__file__).with_name("demo") / "submissions.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
if FIXTURES["version"] != 1:
    raise ValueError("unsupported demo fixture version")
PEOPLE = [(p["login"], p["name"], p["colour"], p["initials"]) for p in FIXTURES["people"]]
# Only finished rows: the worker must never attempt to verify fictional submissions.
ROWS = [(r["track"], r["login"], r["claim"], r["hours_ago"], "verified",
         r["is_record"], r["assisted_by"], r["co_authors"]) for r in FIXTURES["submissions"]]
FIXTURE_NOTES = {r["id"]: r["notes"] for r in FIXTURES["submissions"] if r.get("notes")}
FIXTURE_IDS = {(r[0], r[1], r[3]): fixture["id"]
               for r, fixture in zip(ROWS, FIXTURES["submissions"])}
if len(set(FIXTURE_IDS.values())) != len(ROWS) or len(FIXTURE_IDS) != len(ROWS):
    raise ValueError("demo fixtures must have unique IDs and dates per author/track")
BASE_ROWS = [r for r in ROWS if r[0] == "lower-generality-1"]
UPPER_COMPRESSIONS_ROWS = [r for r in ROWS if r[0] == "upper-compressions"]


def fixture_id(row) -> str:
    return FIXTURE_IDS[(row[0], row[1], row[3])]


def refresh(session) -> int:
    """Reconcile committed fixtures without replacing existing rows or touching real submissions."""
    changed = 0
    existing_ids = set()
    claims = {fixture_id(r): r[2] for r in ROWS}
    for sub in session.scalars(select(Submission)):
        detail = sub.detail_dict
        if not detail.get("demo"):
            continue
        identifier = detail.get("fixture_id")
        if identifier is None:
            # Adopt rows made by earlier versions, preserving their identifiers and dates.
            matches = [r for r in ROWS if (r[0], r[1], r[2], r[5], r[6]) ==
                       (sub.track, sub.user.login, sub.claim, sub.is_record, sub.assisted_by)]
            if len(matches) == 1:
                identifier = fixture_id(matches[0])
                detail["fixture_id"] = identifier
                sub.detail = json.dumps(detail)
        if identifier:
            existing_ids.add(identifier)
        if identifier in claims and sub.claim != claims[identifier]:
            sub.claim = claims[identifier]
            changed += 1
    missing = [row for row in ROWS if fixture_id(row) not in existing_ids]
    if missing:
        changed += add_rows(session, missing)
    session.commit()
    return changed


def avatar(initials: str, colour: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" fill="{colour}"/>'
           f'<text x="32" y="40" font-family="Helvetica,Arial,sans-serif" font-size="26" font-weight="700" fill="#fff" '
           f'text-anchor="middle">{initials}</text></svg>')
    return "data:image/svg+xml;utf8," + quote(svg, safe="")


def remove(session) -> int:
    subs = [s for s in session.scalars(select(Submission))
            if s.detail_dict.get("demo") or (s.description or "").startswith("Demo data for local development")]
    for s in subs:
        session.delete(s)
    users = [u for u in session.scalars(select(User)) if u.github_id is None and u.login in {p[0] for p in PEOPLE}]
    for u in users:
        if not [s for s in u.submissions if s not in subs]:
            session.delete(u)
    session.commit()
    return len(subs)


def demo_users(session) -> dict:
    users = {}
    for login, name, colour, initials in PEOPLE:
        u = session.scalar(select(User).where(User.login == login))
        if u is None:
            u = User(login=login, name=name, avatar_url=avatar(initials, colour))
            session.add(u)
        users[login] = u
    session.flush()
    return users


def add_rows(session, rows) -> int:
    """Insert only the requested demo rows; leave real submissions untouched."""
    # Metadata is the admission gate. A new demo track appears only after its certificate is pinned.
    rows = [row for row in rows if contract.track(row[0])
            and (row[0] != "upper-riscv" or contract.upper_riscv_track())]
    users = demo_users(session)
    for track, login, claim, hours_ago, status, is_record, assisted, coauthors in rows:
        t = NOW - timedelta(hours=hours_ago)
        commit = hashlib.sha1(f"{track}{login}{claim}{hours_ago}".encode()).hexdigest()
        sub = Submission(id=stable_id("demo", FIXTURE_IDS[(track, login, hours_ago)]),
                         track=track, user_id=users[login].id, claim=claim if status == "verified" else None,
                         source_repo=f"https://github.com/{login}/ots.golf", commit=commit, status=status,
                         is_record=is_record, record_at=t if is_record else None,
                         assisted_by=assisted, co_authors=json.dumps(coauthors),
                         description="Demo data for local development; this submission does not exist.",
                         created_at=t - timedelta(minutes=4), started_at=t - timedelta(minutes=3),
                         finished_at=t if status == "verified" else None,
                         duration_s=150.0 if status == "verified" else None,
                         detail=json.dumps({**DEMO,
                                            "fixture_id": FIXTURE_IDS[(track, login, hours_ago)],
                                            **({"notes": FIXTURE_NOTES[FIXTURE_IDS[(track, login, hours_ago)]]}
                                               if FIXTURE_IDS[(track, login, hours_ago)] in FIXTURE_NOTES else {})}))
        session.add(sub)
    return len(rows)


def add(session) -> int:
    count = add_rows(session, ROWS)
    session.commit()
    return count


def reseed(session) -> tuple[int, int]:
    """Replace the invented rows with the fixture file's, keeping real submissions."""
    removed = remove(session)
    return removed, add(session)


def main() -> None:
    from app.config import SERVICE_DIR, settings
    if settings.environment != "development" or urlsplit(settings.base_url).hostname not in {
        "localhost", "127.0.0.1", "::1"
    }:
        sys.exit("demo data is only available in development with a loopback base URL")
    local = settings.database_url == f"sqlite:///{(SERVICE_DIR / 'data').resolve() / 'ots.db'}"
    if not local and "--force" not in sys.argv:
        sys.exit(f"refusing: {settings.database_url} is not the local development database.\n"
                 "This script updates the invented demo rows; pass --force to do that anyway.")
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if "--remove" in sys.argv:
            print(f"removed {remove(session)} phony submissions")
            return
        print(f"updated or added {refresh(session)} demo submissions")


if __name__ == "__main__":
    main()
