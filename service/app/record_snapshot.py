"""Publish current verified track roots on the submissions default branch via Git Data APIs.

Only the frozen root tree and records.json are changed. A non-forced ref update preserves
concurrent main changes; retries reconcile the registry before creating another commit.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from . import contract, git_authors, github, revalidations, source_archive
from .config import settings

REGISTRY = "records.json"
MAX_REGISTRY_BYTES = 256 * 1024
MAX_ATTEMPTS = 3


class SnapshotError(ValueError):
    """The source or current registry is unsuitable for record publication."""


def _sha(value) -> str:
    if not isinstance(value, str) or not github.SHA_RE.fullmatch(value):
        raise SnapshotError("invalid Git object identity")
    return value


def _time(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        pass
    raise SnapshotError("record requires a timezone-qualified completion time")


def _validate_entry(value, slug: str, repo: str) -> dict:
    if not isinstance(value, dict):
        raise SnapshotError("invalid record registry entry")
    sid = value.get("id")
    if (not isinstance(sid, str) or not source_archive.archives.SUBMISSION_ID.fullmatch(sid)
            or value.get("track") != slug
            or value.get("source_ref") != f"refs/tags/ots-source/{sid}"
            or type(value.get("pr_number")) is not int or value["pr_number"] < 1
            or value.get("pr_url") != f"https://github.com/{repo}/pull/{value['pr_number']}"
            or type(value.get("claim")) is not int or value["claim"] < 0):
        raise SnapshotError("invalid record registry identity")
    _sha(value.get("commit"))
    _sha(value.get("contract_commit"))
    _sha(value.get("source_tree"))
    _time(value.get("finished_at"))
    try:
        source_archive.archives.validate_metadata(value.get("source_archive"), commit=value["commit"],
            track=slug, contract=value.get("contract"), submission_root=value.get("submission_root"))
    except source_archive.ArchiveError as exc:
        raise SnapshotError("invalid record source archive identity") from exc
    if (not isinstance(value.get("contract"), str)
            or not source_archive.archives.HEX64.fullmatch(value["contract"])
            or not isinstance(value.get("submission_root"), str)
            or not source_archive.archives.ROOT.fullmatch(value["submission_root"])):
        raise SnapshotError("invalid record contract or root")
    return value


def _entry(sub, repo: str) -> dict:
    detail = sub.detail_dict
    receipt = detail.get("receipt") or {}
    cfg = contract.track(sub.track)
    if (sub.status != "verified" or not sub.is_record or not sub.current_contract or revalidations.is_check(sub)
            or (sub.pr_repository or "").lower() != repo.lower() or cfg is None
            or not isinstance(receipt, dict) or receipt.get("submission_root") != cfg["submission_root"]
            or type(sub.claim) is not int or not 0 <= sub.claim <= contract.load()["limits"]["max_claim"]
            or not isinstance(sub.finished_at, datetime)):
        raise SnapshotError("only a current verified record with its frozen receipt can be published")
    finished = sub.finished_at.replace(tzinfo=timezone.utc) if sub.finished_at.tzinfo is None else sub.finished_at
    value = dict(id=sub.id, track=sub.track, commit=sub.commit, source_ref=detail.get("source_ref"),
                 submission_root=receipt["submission_root"], pr_number=sub.pr_number,
                 pr_url=f"https://github.com/{repo}/pull/{sub.pr_number}", claim=sub.claim,
                 contract=detail.get("contract"), contract_commit=receipt.get("contract_commit"),
                 finished_at=finished.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                 source_archive=source_archive.validate_metadata(detail.get("source_archive"), sub),
                 source_tree="0" * 40)
    return _validate_entry(value, sub.track, repo)


def _json(response: httpx.Response) -> dict:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise SnapshotError("GitHub returned a malformed object")
    return value


class _Git:
    def __init__(self, client: httpx.Client, repo: str):
        self.client, self.url = client, f"{github.API}/repos/{repo}"
        self.cache: dict[str, dict] = {}

    def get(self, path: str) -> dict:
        return _json(self.client.get(self.url + path))

    def tree(self, sha: str) -> dict:
        sha = _sha(sha)
        if sha not in self.cache:
            data = self.get("/git/trees/" + sha)  # deliberately non-recursive
            if data.get("sha") != sha or data.get("truncated") is not False or not isinstance(data.get("tree"), list):
                raise SnapshotError("GitHub returned an incomplete tree")
            entries = {}
            for item in data["tree"]:
                name = item.get("path") if isinstance(item, dict) else None
                if (not isinstance(name, str) or not name or name in {".", ".."}
                        or "/" in name or "\x00" in name or name in entries):
                    raise SnapshotError("GitHub returned an invalid tree path")
                _sha(item.get("sha"))
                entries[name] = item
            self.cache[sha] = entries
        return self.cache[sha]

    def commit_tree(self, sha: str) -> str:
        data = self.get("/git/commits/" + _sha(sha))
        if data.get("sha") != sha or not isinstance(data.get("tree"), dict):
            raise SnapshotError("GitHub returned a different commit")
        return _sha(data["tree"].get("sha"))

    def root(self, tree: str, path: str, *, missing: bool = False) -> str | None:
        for part in path.split("/"):
            entry = self.tree(tree).get(part)
            if entry is None and missing:
                return None
            if not entry or entry.get("type") != "tree" or entry.get("mode") != "040000":
                raise SnapshotError("the submission root is not a Git directory")
            tree = entry["sha"]
        return tree

    def registry(self, tree: str, repo: str) -> dict:
        item = self.tree(tree).get(REGISTRY)
        if item is None:
            return {"version": 1, "records": {}}
        if (item.get("type") != "blob" or item.get("mode") != "100644"
                or type(item.get("size")) is not int or not 0 <= item["size"] <= MAX_REGISTRY_BYTES):
            raise SnapshotError("record registry is not a bounded regular file")
        blob = self.get("/git/blobs/" + item["sha"])
        if (blob.get("sha") != item["sha"] or blob.get("encoding") != "base64"
                or blob.get("size") != item["size"] or not isinstance(blob.get("content"), str)
                or len(blob["content"]) > 2 * MAX_REGISTRY_BYTES):
            raise SnapshotError("GitHub returned an invalid registry blob")
        try:
            raw = base64.b64decode("".join(blob["content"].split()), validate=True)
            if len(raw) != item["size"]:
                raise ValueError("incorrect registry size")
            registry = source_archive.archives._json(raw)
        except (ValueError, source_archive.ArchiveError) as exc:
            raise SnapshotError("invalid record registry JSON") from exc
        if registry.get("version") != 1 or not isinstance(registry.get("records"), dict):
            raise SnapshotError("unsupported record registry")
        for slug, value in registry["records"].items():
            _validate_entry(value, slug, repo)
        return registry


def _validate_source(git: _Git, entry: dict) -> None:
    files = git.tree(entry["source_tree"])
    meta = entry["source_archive"]
    if len(files) != meta["file_count"] or not {"Solution.lean", "claim.txt"} <= files.keys():
        raise SnapshotError("source tree differs from the checked archive layout")
    total = 0
    for name, item in files.items():
        if (not source_archive.archives._name(name) or item.get("type") != "blob"
                or item.get("mode") not in {"100644", "100755"}
                or type(item.get("size")) is not int
                or not 0 <= item["size"] <= source_archive.archives.MAX_FILE_BYTES):
            raise SnapshotError("source tree violates the checked flat-root policy")
        total += item["size"]
    if total != meta["total_bytes"]:
        raise SnapshotError("source tree size differs from the checked archive")


def publish_record(sub) -> dict:
    """Publish one current frontier record; caller decides that it is still the track's best.

    Returns the default-branch commit and whether this call changed it. Errors leave the worker's
    outbox retryable. Tree/commit objects created before a failure are harmless unreferenced objects.
    """
    repo = settings.submissions_repo
    if not repo or not github.REPO_RE.fullmatch(repo) or not settings.github_token:
        raise SnapshotError("record publication requires the configured repository and credentials")
    entry = _entry(sub, repo)
    github.verify_source_ref(repo, sub.id, sub.commit, entry["source_ref"])
    with httpx.Client(timeout=30, headers=github._headers()) as client:
        git = _Git(client, repo)
        branch = git.get("").get("default_branch")
        if not isinstance(branch, str) or not branch or len(branch) > 255:
            raise SnapshotError("GitHub returned an invalid default branch")
        ref_path = "/git/ref/heads/" + quote(branch, safe="")
        update_path = "/git/refs/heads/" + quote(branch, safe="")
        entry["source_tree"] = git.root(git.commit_tree(sub.commit), entry["submission_root"])
        _validate_source(git, entry)
        conflict_head, conflict_error = None, None
        for attempt in range(MAX_ATTEMPTS):
            ref = git.get(ref_path)
            obj = ref.get("object") or {}
            if ref.get("ref") != f"refs/heads/{branch}" or obj.get("type") != "commit":
                raise SnapshotError("GitHub returned a different branch reference")
            head = _sha(obj.get("sha"))
            if head == conflict_head:
                raise conflict_error
            tree = git.commit_tree(head)
            registry = git.registry(tree, repo)
            # Existing ancestor files must never be replaced implicitly by nested tree creation.
            current_root = git.root(tree, entry["submission_root"], missing=True)
            old = registry["records"].get(sub.track)
            if old:
                if old["id"] == entry["id"]:
                    if old != entry:
                        raise SnapshotError("published submission identity has conflicting metadata")
                    if current_root == entry["source_tree"]:
                        return {"commit": head, "published": False, "reason": "already_current"}
                elif (_time(old["finished_at"]) >= _time(entry["finished_at"])
                      or (old["contract"] == entry["contract"] and not contract.improves(
                          contract.track(sub.track)["direction"], entry["claim"], old["claim"]))):
                    return {"commit": head, "published": False, "reason": "superseded"}
            # Modern receipts freeze attribution at admission, before a submitter can
            # push another revision. Legacy jobs require their head still to match.
            authors = (sub.detail_dict.get("receipt") or {}).get("git_authors")
            if authors is None:
                authors = git_authors.for_pr(repo, sub.pr_number, sub.commit)
            author_trailers = git_authors.trailers(authors)
            registry["records"][sub.track] = entry
            content = json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            if len(content.encode()) > MAX_REGISTRY_BYTES:
                raise SnapshotError("record registry exceeds its size limit")
            new_tree = _sha(_json(client.post(git.url + "/git/trees", json={"base_tree": tree, "tree": [
                {"path": entry["submission_root"], "mode": "040000", "type": "tree", "sha": entry["source_tree"]},
                {"path": REGISTRY, "mode": "100644", "type": "blob", "content": content},
            ]})).get("sha"))
            new_commit = _sha(_json(client.post(git.url + "/git/commits", json={
                "message": (f"Record {sub.track}: {sub.claim} (PR #{sub.pr_number})\n\n"
                            f"Checked source: {entry['commit']}\nPull request: {entry['pr_url']}\n"
                            f"Contract: {entry['contract']}\nTrusted core: {entry['contract_commit']}\n\n"
                            f"{author_trailers}\n"),
                "tree": new_tree, "parents": [head],
            })).get("sha"))
            if not sub.current_contract:
                raise SnapshotError("the contract changed during record publication")
            try:
                response = client.patch(git.url + update_path, json={"sha": new_commit, "force": False})
                if response.status_code in {409, 422}:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        conflict_head, conflict_error = head, exc
                    continue
                result = _json(response)
                if result.get("ref") != f"refs/heads/{branch}" or (result.get("object") or {}).get("sha") != new_commit:
                    raise SnapshotError("GitHub did not confirm the published record commit")
                return {"commit": new_commit, "published": True, "reason": "published"}
            except httpx.TransportError:
                # A lost response may follow a successful ref update. Re-read before retrying.
                if attempt + 1 == MAX_ATTEMPTS:
                    raise
        raise SnapshotError("default branch kept changing; retry record publication")
