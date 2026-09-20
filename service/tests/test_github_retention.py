"""Retained source refs and receipts make hosted admission recoverable from GitHub."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import github, main, records
from app.config import settings
from app.db import Base, GithubReport, Submission, User


class RetentionRefTests(unittest.TestCase):
    repo = "org/submissions"
    sid = "a" * 32
    sha = "b" * 40

    def setUp(self):
        for key, value in (("submissions_repo", self.repo), ("github_token", "test-token")):
            change = patch.object(settings, key, value)
            change.start()
            self.addCleanup(change.stop)
        self.ref = "refs/tags/ots-source/" + self.sid

    def client(self, statuses):
        requests = []
        def handle(request):
            requests.append(request)
            status, body = statuses.pop(0)
            return httpx.Response(status, json=body)
        client = httpx.Client(transport=httpx.MockTransport(handle))
        return patch.object(github.httpx, "Client", return_value=client), requests

    def target(self, **changes):
        return {"object": {"type": "commit", "sha": self.sha, **changes}}

    def test_existing_tag_is_read_only_and_exact(self):
        client, requests = self.client([(200, self.target())])
        with client:
            self.assertEqual(github.ensure_source_ref(self.repo, self.sid, self.sha), self.ref)
        self.assertEqual([r.method for r in requests], ["GET"])
        self.assertTrue(str(requests[0].url).endswith("/git/ref/tags/ots-source/" + self.sid))

    def test_new_tag_is_created_once_and_read_back(self):
        client, requests = self.client([(404, {}), (201, {}), (200, self.target())])
        with client:
            self.assertEqual(github.ensure_source_ref(self.repo, self.sid, self.sha), self.ref)
        self.assertEqual([r.method for r in requests], ["GET", "POST", "GET"])
        self.assertEqual(json.loads(requests[1].content), {"ref": self.ref, "sha": self.sha})

    def test_creation_race_requires_matching_readback(self):
        client, requests = self.client([(404, {}), (422, {}), (200, self.target())])
        with client:
            self.assertEqual(github.ensure_source_ref(self.repo, self.sid, self.sha), self.ref)
        self.assertNotIn("PATCH", [r.method for r in requests])

    def test_conflicting_or_indirect_objects_are_never_rewritten(self):
        for body in (self.target(sha="c" * 40), self.target(type="tag"), {}):
            with self.subTest(body=body):
                client, requests = self.client([(200, body)])
                with client, self.assertRaises(ValueError):
                    github.ensure_source_ref(self.repo, self.sid, self.sha)
                self.assertEqual([r.method for r in requests], ["GET"])

    def test_recovery_requires_the_expected_tag_and_repository(self):
        for repo, sid, sha, ref in (
                ("other/repo", self.sid, self.sha, self.ref),
                (self.repo, "../bad", self.sha, self.ref),
                (self.repo, self.sid, "HEAD", self.ref),
                (self.repo, self.sid, self.sha, "refs/heads/main")):
            with self.subTest(ref=ref), patch.object(github.httpx, "Client") as client:
                with self.assertRaises(ValueError):
                    github.verify_source_ref(repo, sid, sha, ref)
                client.assert_not_called()

    def test_history_at_the_bound_requires_an_empty_final_page(self):
        page = [{"id": i} for i in range(100)]
        client, requests = self.client([(200, page), (200, [])])
        with client:
            self.assertEqual(github._paged("/fixture", limit=100), page)
        self.assertEqual(len(requests), 2)

    def test_history_is_never_silently_truncated(self):
        client, _ = self.client([(200, [{"id": i} for i in range(100)]), (200, [{"id": 100}])])
        with client, self.assertRaisesRegex(ValueError, "partial rebuild"):
            github._paged("/fixture", limit=100)

    def test_receipt_metadata_round_trips_without_breaking_html_comment(self):
        entry = dict(id=self.sid, track="lower-generality-3", commit=self.sha, status="pending",
                     source_ref=self.ref, created_at="2026-09-19T00:00:00Z",
                     author={"login": "solver", "id": 7}, description="Unicode λ and --> stay data")
        block = github.verdict_block([entry])
        self.assertEqual(block.count("-->"), 1)
        restored = github.parse_verdicts(block)[0]
        for key, value in entry.items():
            self.assertEqual(restored[key], value)


class HostedAdmissionTests(unittest.TestCase):
    def setUp(self):
        attribution = patch.object(main.git_authors, "for_pr", return_value=[
            {"name": "Solver", "email": "solver@example.org"},
            {"name": "Helper", "email": "helper@example.org"}])
        self.attribution = attribution.start()
        self.addCleanup(attribution.stop)
        tmp = tempfile.TemporaryDirectory(prefix="ots-admission-receipt-")
        self.addCleanup(tmp.cleanup)
        for key, value in (("environment", "production"), ("submissions_repo", "org/submissions"),
                           ("github_token", "test-token"), ("data_dir", Path(tmp.name)),
                           ("max_inflight_per_user", 5), ("queue_cap", 20)):
            change = patch.object(settings, key, value)
            change.start()
            self.addCleanup(change.stop)
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.user = User(login="solver", github_id=7)
        self.session.add(self.user)
        self.session.commit()

    def queue(self, description="Prepared proof"):
        return main.queue_submission(self.session, self.user, "lower-generality-3",
            "https://github.com/solver/fork.git", "b" * 40, description, ["helper"], "Assistant",
            17, "https://github.com/org/submissions/pull/17")

    def test_worker_cannot_run_until_receipt_publication(self):
        with patch.object(github, "ensure_source_ref", side_effect=lambda repo, sid, sha: "refs/tags/ots-source/" + sid) as pin:
            sub = self.queue()
        pin.assert_called_once_with("org/submissions", sub.id, sub.commit)
        self.assertEqual(sub.status, "admitting")
        self.assertEqual(sub.source_repo, "https://github.com/org/submissions.git")
        self.assertEqual(sub.detail_dict["receipt"]["author"]["login"], "solver")
        self.assertEqual(sub.detail_dict["receipt"]["co_authors"], ["helper"])
        self.assertEqual(sub.detail_dict["receipt"]["git_authors"], self.attribution.return_value)
        self.attribution.assert_called_once_with("org/submissions", 17, "b" * 40)
        self.assertEqual(sub.detail_dict["receipt"]["created_at"], sub.created_at.isoformat(timespec="microseconds") + "Z")
        self.assertIsNotNone(self.session.get(GithubReport, sub.id))
        self.assertEqual([s.id for s in records.in_flight(self.session)], [sub.id])
        self.assertIsNone(self.session.scalar(select(Submission).where(Submission.status == "pending")))

    def test_retained_retry_does_not_reuse_a_shared_legacy_comment(self):
        with patch.object(github, "ensure_source_ref", side_effect=lambda repo, sid, sha: "refs/tags/ots-source/" + sid):
            sub = self.queue()
            sub.status = "failed"
            sub.detail = json.dumps({"contract": main.contract.contract_id(), "github_comment_id": 123})
            historical = Submission(id="9" * 32, track=sub.track, user_id=self.user.id,
                source_repo=sub.source_repo, commit="c" * 40, status="failed",
                pr_number=17, pr_url=sub.pr_url, detail=sub.detail)
            self.session.add(historical)
            self.session.commit()
            retried = self.queue()
        self.assertEqual(retried.status, "admitting")
        self.assertNotIn("github_comment_id", retried.detail_dict)
        self.assertEqual(historical.detail_dict["github_comment_id"], 123)

    def test_failed_retention_does_not_create_a_queue_item(self):
        with patch.object(github, "ensure_source_ref", side_effect=ValueError("conflicting tag")):
            with self.assertRaises(HTTPException) as error:
                self.queue()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(list(self.session.scalars(select(Submission))), [])

    def test_failed_git_attribution_does_not_admit_or_retain_a_partial_receipt(self):
        self.attribution.side_effect = ValueError("PR head changed")
        with patch.object(github, "ensure_source_ref") as pin:
            with self.assertRaises(HTTPException) as error:
                self.queue()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(list(self.session.scalars(select(Submission))), [])
        pin.assert_not_called()

    def test_comment_escape_expansion_is_included_in_receipt_budget(self):
        with patch.object(github, "ensure_source_ref") as pin:
            with self.assertRaises(HTTPException) as error:
                self.queue("--" * (10 * 1024))
        self.assertEqual(error.exception.status_code, 413)
        pin.assert_not_called()

    def test_unknown_contract_commit_is_not_admitted(self):
        with patch.object(main.contract, "trusted_commit", return_value="unknown"), \
                patch.object(github, "ensure_source_ref") as pin:
            with self.assertRaises(HTTPException) as error:
                self.queue()
        self.assertEqual(error.exception.status_code, 503)
        pin.assert_not_called()

    def test_oversized_receipt_is_refused_before_creating_a_tag(self):
        with patch.object(github, "ensure_source_ref") as pin:
            with self.assertRaises(HTTPException) as error:
                self.queue("x" * (49 * 1024))
        self.assertEqual(error.exception.status_code, 413)
        pin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
