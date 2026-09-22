"""Keep contributor tooling pinned to the deployed core, independently of record publication."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx

from . import contract, github
from .config import settings
from .record_snapshot import SnapshotError, _Git, _json, _sha

log = logging.getLogger(__name__)


def enabled() -> bool:
    # A localhost preview must never repin the public submissions repository.
    return (settings.environment == "production" and settings.role == "web"
            and not settings.phony and bool(settings.github_token and settings.submissions_repo))


def sync_pin(target: str) -> dict:
    """Advance only .contract to this process's deployed commit; never force or roll back.

    Re-read the default branch after a concurrent publication and build on its new tree.
    A lost response is safe to retry: the next read detects an already-current pin.
    """
    if not enabled():
        raise SnapshotError("contract synchronization requires the real production web service")
    target = _sha(target)
    with httpx.Client(timeout=30, headers=github._headers()) as client:
        git = _Git(client, settings.submissions_repo)
        core = _Git(client, settings.contract_repo)
        branch = git.get("").get("default_branch")
        if not isinstance(branch, str) or not branch or len(branch) > 255:
            raise SnapshotError("GitHub returned an invalid default branch")
        branch_path = quote(branch, safe="")
        for _ in range(3):
            ref = git.get("/git/ref/heads/" + branch_path)
            obj = ref.get("object") or {}
            if ref.get("ref") != f"refs/heads/{branch}" or obj.get("type") != "commit":
                raise SnapshotError("GitHub returned a different branch reference")
            head = _sha(obj.get("sha"))
            tree = git.commit_tree(head)
            pin = git.tree(tree).get(".contract")
            if not pin or pin.get("mode") != "160000" or pin.get("type") != "commit":
                raise SnapshotError(".contract must already be a Git submodule")
            previous = _sha(pin.get("sha"))
            if previous == target:
                return {"reason": "already_current", "commit": head, "pin": target}
            # Besides checking ancestry, this ensures the target is fetchable from the core repo.
            comparison = core.get(f"/compare/{previous}...{target}")
            status = comparison.get("status")
            if status == "behind":
                return {"reason": "newer_pin", "commit": head, "pin": previous}
            if (status != "ahead" or (comparison.get("base_commit") or {}).get("sha") != previous
                    or (comparison.get("merge_base_commit") or {}).get("sha") != previous):
                raise SnapshotError("deployed core does not descend from the submissions contract pin")
            new_tree = _sha(_json(client.post(git.url + "/git/trees", json={
                "base_tree": tree,
                "tree": [{"path": ".contract", "mode": "160000", "type": "commit", "sha": target}],
            })).get("sha"))
            commit = _sha(_json(client.post(git.url + "/git/commits", json={
                "message": f"Sync contract with deployed verifier ({target[:12]})\n\nTrusted core: {target}\n",
                "tree": new_tree, "parents": [head],
            })).get("sha"))
            response = client.patch(git.url + "/git/refs/heads/" + branch_path,
                                    json={"sha": commit, "force": False})
            if response.status_code in {409, 422}:
                if _ == 2:
                    response.raise_for_status()
                continue
            result = _json(response)
            if (result.get("object") or {}).get("sha") != commit:
                raise SnapshotError("GitHub returned a different updated reference")
            return {"reason": "updated", "commit": commit, "pin": target}
    raise SnapshotError("submissions branch kept changing during contract synchronization")


async def sync_on_start() -> None:
    """Retry without holding up page serving. Finish after success or observing a newer deployment."""
    target = contract.trusted_commit()
    while True:
        try:
            result = await asyncio.to_thread(sync_pin, target)
            if result["reason"] == "newer_pin":
                log.warning("Contract pin is newer than this deployment; leaving it unchanged: %s", result)
            else:
                print(f"Submissions contract synchronized: {result}", flush=True)
            return
        except Exception:
            log.exception("Submissions contract synchronization failed; retrying in 60 seconds")
        await asyncio.sleep(60)
