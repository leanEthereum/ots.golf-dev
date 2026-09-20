"""Git identities from the exact commits of a submitted PR revision."""
from __future__ import annotations

import re

import httpx

from . import github

MAX_COMMITS = 5000
TRAILER = re.compile(r"^Co-authored-by:[ \t]*(.*?)[ \t]*<([^<>]*)>[ \t]*$", re.I)


def validate(authors: list[dict]) -> list[dict]:
    """Validate without silently discarding an author; deduplicate email case-insensitively."""
    if not isinstance(authors, list) or not authors:
        raise ValueError("missing Git authors")
    result, seen = [], set()
    for author in authors:
        if not isinstance(author, dict):
            raise ValueError("invalid Git author")
        name, email = author.get("name"), author.get("email")
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or any(ord(c) < 32 or ord(c) == 127 or c in "<>" for c in name)
                or not isinstance(email, str) or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", email)
                or any(ord(c) < 32 or ord(c) == 127 for c in email)):
            raise ValueError("Git author cannot be represented safely in a co-author trailer")
        if email.casefold() not in seen:
            result.append({"name": name, "email": email})
            seen.add(email.casefold())
    return result


def from_commits(commits: list[dict]) -> list[dict]:
    authors = []
    for item in commits:
        commit = item.get("commit")
        if not isinstance(commit, dict) or not isinstance(commit.get("message"), str):
            raise ValueError("malformed GitHub commit")
        authors.append(commit.get("author"))
        # Git trailers belong to the final paragraph, not quoted prose earlier in the body.
        footer = commit["message"].rstrip().rsplit("\n\n", 1)[-1]
        for line in footer.splitlines():
            if line.lower().startswith("co-authored-by:"):
                match = TRAILER.fullmatch(line)
                if match is None:
                    raise ValueError("malformed co-author trailer")
                authors.append({"name": match[1], "email": match[2]})
    return validate(authors)


def for_pr(repo: str, number: int, head: str) -> list[dict]:
    """Freeze authors before admission. Compare immutable SHAs, never a moving commit list."""
    if not github.REPO_RE.fullmatch(repo) or not github.SHA_RE.fullmatch(head):
        raise ValueError("invalid source identity")
    pr = github.get_pr(repo, number)
    base = (pr.get("base") or {}).get("sha")
    if (pr.get("head") or {}).get("sha") != head:
        raise ValueError("PR head changed before Git attribution was frozen")
    if not isinstance(base, str) or not github.SHA_RE.fullmatch(base):
        raise ValueError("missing PR base commit")
    commits, seen, total = [], set(), None
    with httpx.Client(timeout=30, headers=github._headers()) as client:
        for page in range(1, MAX_COMMITS // 100 + 1):
            response = client.get(f"{github.API}/repos/{repo}/compare/{base}...{head}",
                                  params={"per_page": 100, "page": page})
            response.raise_for_status()
            data = response.json()
            if (not isinstance(data, dict) or (data.get("base_commit") or {}).get("sha") != base
                    or type(data.get("total_commits")) is not int
                    or not 1 <= data["total_commits"] <= MAX_COMMITS
                    or not isinstance(data.get("commits"), list)
                    or (total is not None and total != data["total_commits"])):
                raise ValueError("incomplete GitHub comparison")
            total = data["total_commits"]
            batch = data["commits"]
            for item in batch:
                sha = item.get("sha") if isinstance(item, dict) else None
                if not isinstance(sha, str) or not github.SHA_RE.fullmatch(sha) or sha in seen:
                    raise ValueError("invalid or repeated PR commit")
                seen.add(sha)
            commits.extend(batch)
            if len(commits) == total:
                if head not in seen:
                    raise ValueError("comparison omits the checked head")
                return from_commits(commits)
            if len(batch) != 100 or len(commits) > total:
                raise ValueError("truncated GitHub comparison")
    raise ValueError("GitHub comparison exceeds the attribution limit")


def trailers(authors: list[dict]) -> str:
    return "\n".join(f"Co-authored-by: {a['name']} <{a['email']}>" for a in validate(authors))
