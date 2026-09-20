"""GitHub: webhook signature, which submission root a pull request touches, statuses and comments."""
from __future__ import annotations

import hashlib
import hmac
import json
import re

import httpx

from . import contract
from .config import settings

API = "https://api.github.com"
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$")     # what GitHub can issue


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not settings.github_webhook_secret or not signature:
        return False
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))   # bytes: any header is safe


def _check(r: httpx.Response, what: str) -> None:
    """A verdict that never reaches the pull request must at least reach the log."""
    if r.status_code >= 300:
        print(f"[github] {what}: HTTP {r.status_code} {r.text[:200]}", flush=True)
        r.raise_for_status()


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "ots.golf-verifier"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def get_pr(owner_repo: str, number: int) -> dict:
    """The pull request as GitHub describes it now: author, state and head come from here, never from
    a webhook payload, so a leaked webhook secret cannot put words in anyone's mouth."""
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{API}/repos/{owner_repo}/pulls/{number}", headers=_headers())
        r.raise_for_status()
        return r.json()


def pr_track(owner_repo: str, number: int, *, expected_files: int | None = None) -> tuple[str | None, list[str]]:
    """The track whose root the PR changes, and the files outside any root (which disqualify it)."""
    roots = {t["submission_root"].rstrip("/") + "/": t["slug"] for t in contract.tracks()}
    touched, outside, count = set(), [], 0
    # GitHub's pull-request files endpoint returns at most 3,000 files. Refuse a truncated list.
    if expected_files is not None and not 0 <= expected_files <= 3000:
        return None, ["file list exceeds GitHub's 3,000-file limit"]
    with httpx.Client(timeout=30) as client:
        page = 1
        while True:
            r = client.get(f"{API}/repos/{owner_repo}/pulls/{number}/files",
                           params={"per_page": 100, "page": page}, headers=_headers())
            r.raise_for_status()
            files = r.json()
            count += len(files)
            for f in files:
                # A rename changes both paths, including a source outside the submitted root.
                for name in {f["filename"], f.get("previous_filename", f["filename"])}:
                    slug = next((s for root, s in roots.items() if name.startswith(root)), None)
                    if slug:
                        touched.add(slug)
                    else:
                        outside.append(name)
            if len(files) < 100:
                break
            if page == 30:
                if expected_files != count:
                    return None, ["GitHub returned an incomplete file list"]
                break
            page += 1
    if expected_files is not None and expected_files != count:
        return None, ["GitHub returned an incomplete file list"]
    if len(touched) != 1:
        return None, outside
    return touched.pop(), outside


def _source_ref_path(owner_repo: str, submission_id: str, commit: str, source_ref: str) -> str:
    if (not REPO_RE.fullmatch(owner_repo) or not settings.submissions_repo
            or owner_repo.lower() != settings.submissions_repo.lower()
            or not re.fullmatch(r"[0-9a-f]{32}", submission_id)
            or not SHA_RE.fullmatch(commit)
            or source_ref != f"refs/tags/ots-source/{submission_id}"):
        raise ValueError("invalid retained submission reference")
    return f"{API}/repos/{owner_repo}/git/ref/{source_ref.removeprefix('refs/')}"


def _verify_source_object(data: dict, commit: str) -> None:
    obj = data.get("object") if isinstance(data, dict) else None
    if not isinstance(obj, dict) or obj.get("type") != "commit" or obj.get("sha") != commit:
        raise ValueError("retained submission reference points to a different object")


def verify_source_ref(owner_repo: str, submission_id: str, commit: str, source_ref: str) -> None:
    """Require the immutable retention tag to name the exact queued commit in the base repo."""
    url = _source_ref_path(owner_repo, submission_id, commit, source_ref)
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=_headers())
        _check(response, "read retained source reference")
        _verify_source_object(response.json(), commit)


def ensure_source_ref(owner_repo: str, submission_id: str, commit: str) -> str:
    """Create once and read back; never update or delete a retained source tag.

    PR heads are available in their base repository. Keeping a ref there prevents loss of the
    checked commit when a contributor later force-pushes or deletes their branch or fork.
    """
    source_ref = f"refs/tags/ots-source/{submission_id}"
    url = _source_ref_path(owner_repo, submission_id, commit, source_ref)
    if not settings.github_token:
        raise ValueError("GitHub credentials are required to retain a submission")
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=_headers())
        if response.status_code == 404:
            created = client.post(f"{API}/repos/{owner_repo}/git/refs", headers=_headers(),
                                  json={"ref": source_ref, "sha": commit})
            # Another admission process may have created the same tag. Only a matching readback
            # counts as success; a conflict never authorizes changing an existing ref.
            if created.status_code not in (201, 422):
                _check(created, "retain submission source")
            response = client.get(url, headers=_headers())
        _check(response, "read retained source reference")
        _verify_source_object(response.json(), commit)
    return source_ref


def post_status(owner_repo: str, sha: str, state: str, description: str, target_url: str) -> None:
    if not settings.github_token:
        return
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{API}/repos/{owner_repo}/statuses/{sha}", headers=_headers(),
                        json={"state": state, "description": description[:140], "target_url": target_url,
                              "context": "ots.golf/verifier"})
    _check(r, f"status on {owner_repo}@{sha[:10]}")


def _paged(path: str, params: dict | None = None, limit: int = 5000) -> list[dict]:
    """Read complete history, failing explicitly if its configured bound is exceeded."""
    items: list[dict] = []
    with httpx.Client(timeout=30) as client:
        page = 1
        while True:
            r = client.get(f"{API}{path}", params={**(params or {}), "per_page": 100, "page": page},
                           headers=_headers())
            _check(r, f"list {path}")
            batch = r.json()
            if not isinstance(batch, list):
                raise ValueError("GitHub returned a malformed history page")
            if len(items) + len(batch) > limit:
                raise ValueError(f"GitHub history exceeds {limit} entries; refusing a partial rebuild")
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    return items


def list_pulls(owner_repo: str) -> list[dict]:
    """Every pull request of the repository, open and closed, oldest first."""
    return _paged(f"/repos/{owner_repo}/pulls", {"state": "all", "sort": "created", "direction": "asc"})


def list_comments(owner_repo: str, number: int) -> list[dict]:
    return _paged(f"/repos/{owner_repo}/issues/{number}/comments")


def token_login() -> str:
    """The account the token acts as: the only author whose comments carry verdicts."""
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{API}/user", headers=_headers())
        _check(r, "token login")
        return r.json()["login"]


def read_file(owner_repo: str, path: str, commit: str, max_bytes: int = 64 * 1024) -> str | None:
    """A file at a commit of the repository (pull-request heads included), or None if absent."""
    if not SHA_RE.fullmatch(commit):
        raise ValueError("not a commit id")
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{API}/repos/{owner_repo}/contents/{path}", params={"ref": commit},
                       headers={**_headers(), "Accept": "application/vnd.github.raw+json"})
        if r.status_code == 404:
            return None
        _check(r, f"read {path}")
        return r.content[:max_bytes].decode("utf-8", errors="replace")


def targets_default_branch(pr: dict) -> bool:
    """A submission counts only when its pull request targets the repository's default branch."""
    base = pr.get("base") or {}
    default = (base.get("repo") or {}).get("default_branch")
    return bool(default) and base.get("ref") == default


VERDICT_OPEN, VERDICT_CLOSE = "<!-- ots-result", "-->"
VERDICT_RE = re.compile(r"<!-- ots-result\n(.*)\n-->\s*", re.S)
VERDICT_KEYS = ("id", "track", "commit", "status", "claim", "duration_s", "finished_at", "contract", "record", "source_archive",
                "source_ref", "created_at", "author", "description", "co_authors", "assisted_by",
                "contract_commit", "submission_root", "failure", "git_authors")


def verdict_block(entries: list[dict]) -> str:
    """Every verdict of a pull request, machine-readable, hidden in the bot's comment. The comment is
    the durable copy: the server's database can be rebuilt from it."""
    clean = [{k: e.get(k) for k in VERDICT_KEYS} for e in entries]
    text = json.dumps({"version": 1, "results": clean}, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    text = text.replace("--", "-\\u002d")          # an HTML comment cannot contain "--"
    return VERDICT_OPEN + "\n" + text + "\n" + VERDICT_CLOSE


def parse_verdicts(body: str) -> list[dict]:
    """The verdicts recorded in a bot comment, validated field by field; anything malformed is dropped."""
    # Only a block ending the comment counts: earlier quoted text (a failure log) is submitter-controlled.
    body = body or ""
    start = body.rfind(VERDICT_OPEN)
    match = VERDICT_RE.fullmatch(body, start) if start >= 0 else None
    if not match:
        return []
    try:
        data = json.loads(match[1])
    except ValueError:
        return []
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("results"), list):
        return []
    out = []
    for e in data["results"]:
        if not (isinstance(e, dict) and isinstance(e.get("track"), str) and isinstance(e.get("commit"), str)
                and SHA_RE.fullmatch(e["commit"]) and isinstance(e.get("status"), str)):
            continue
        claim = e.get("claim")
        if claim is not None and (type(claim) is not int or claim < 0):
            continue
        out.append({k: e.get(k) for k in VERDICT_KEYS})
    return out


def post_comment(owner_repo: str, number: int, body: str) -> int | None:
    if not settings.github_token:
        return
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{API}/repos/{owner_repo}/issues/{number}/comments", headers=_headers(), json={"body": body})
    _check(r, f"comment on {owner_repo}#{number}")
    return r.json()["id"]


def update_comment(owner_repo: str, comment_id: int, body: str) -> None:
    with httpx.Client(timeout=30) as client:
        r = client.patch(f"{API}/repos/{owner_repo}/issues/comments/{comment_id}",
                         headers=_headers(), json={"body": body})
    _check(r, f"update comment {comment_id} on {owner_repo}")


# One line each; horizontal whitespace only, so an empty field never swallows the next line.
FIELD_RE = re.compile(r"^[ \t]*(assisted[ _-]?by|co[ _-]?authors?)[ \t]*:[ \t]*(.*?)[ \t\r]*$", re.I | re.M)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def parse_pr_body(body: str) -> dict:
    """`Assisted by: ...` and `Co-authors: a, b` lines from the pull request body; the rest is the description."""
    assisted, co = None, []
    body = COMMENT_RE.sub("", body or "")          # the template's instructions are not a description
    for m in FIELD_RE.finditer(body):
        key, val = m.group(1).lower().replace("-", "").replace("_", "").replace(" ", ""), m.group(2)
        if key == "assistedby":
            assisted = val or None
        else:
            co = [c.strip().lstrip("@") for c in val.split(",") if c.strip()]
    description = FIELD_RE.sub("", body).strip() or None
    return {"assisted_by": assisted, "co_authors": co, "description": description}
