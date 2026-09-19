"""Queue a commit for local verification the way the webhook would.

    .venv/bin/python -m app.queue lower --repo PATH_OR_URL [--commit HEAD] [--login ots.golf]

`--repo` is a submissions checkout holding the track's submission root. A local job never becomes
a record: records come only from pull requests to the submissions repository.
"""
from __future__ import annotations

import argparse
import subprocess

from . import contract, github
from .auth import get_or_create_user
from .db import SessionLocal, Submission, init_db, stable_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--repo", required=True, help="submissions checkout (path or URL)")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--login", default="ots.golf")   # a dot: no GitHub account can claim it
    ap.add_argument("--description", default=None)
    a = ap.parse_args()
    t = contract.track(a.track)
    if t is None:
        print(f"unknown track {a.track}")
        return 1
    sha = a.commit
    if a.repo.startswith("http") and not github.SHA_RE.fullmatch(sha):
        print("--commit must be a full commit id for a remote repository")
        return 1
    if not a.repo.startswith("http"):
        sha = subprocess.run(["git", "-C", a.repo, "rev-parse", a.commit], check=True, capture_output=True,
                             text=True).stdout.strip()
    init_db()
    with SessionLocal() as session:
        user = get_or_create_user(session, a.login)
        sid = stable_id("local", a.track, a.repo, sha)
        if session.get(Submission, sid) is not None:
            print(f"already queued as {sid}")
            return 0
        sub = Submission(id=sid, track=a.track, user_id=user.id, source_repo=a.repo, commit=sha,
                         description=a.description)
        session.add(sub)
        session.commit()
        print(f"queued {sub.id} for {a.track}: {a.repo}@{sha[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
