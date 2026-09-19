"""GitHub receipts recover exact queue state; optional cache rebuilding never checks a proof."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import contract, github, rebuild, resync, source_archive
from app.config import settings
from app.db import Base, GithubReport, Submission, User


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ots-rebuild-test-")
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        (self.data / "work").mkdir()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        for item in [patch.object(settings, "data_dir", self.data),
                     patch.object(settings, "work_dir", self.data / "work"),
                     patch.object(settings, "submissions_repo", "owner/entries"),
                     patch.object(settings, "github_token", "test-token"),
                     patch.object(settings, "bot_login", "ots-bot"),
                     patch("app.resync.SessionLocal", self.sessions),
                     patch("app.rebuild.SessionLocal", self.sessions),
                     patch("app.resync.github.read_file", return_value=None)]:
            item.start()
            self.addCleanup(item.stop)
        self.root = "formal/Submissions/LowerGenerality2"
        self.sid = "1" * 32
        self.commit = "a" * 40
        self.pr = {"number": 7, "state": "closed", "body": "Changed attribution", "user": None,
                   "head": {"sha": "b" * 40, "repo": None}, "created_at": "2026-01-01T00:00:00Z"}

    def entry(self, **changes):
        value = dict(id=self.sid, track="lower-generality-2", commit=self.commit, status="pending",
                     contract=contract.contract_id(), source_ref=f"refs/tags/ots-source/{self.sid}",
                     created_at="2026-09-01T10:00:00.123456Z", author={"login": "alice", "id": 42, "avatar_url": None},
                     description="The admitted description", co_authors=["Bob Smith"], assisted_by="Model X",
                     contract_commit="c" * 40, submission_root=self.root)
        value.update(changes)
        return value

    def comment(self, entry, *, cid=5, edited="2026-09-01T10:00:01Z"):
        return {"id": cid, "user": {"login": "ots-bot"}, "updated_at": edited,
                "body": github.verdict_block([entry])}

    def restore(self, entries, **kwargs):
        comments = [self.comment(entry, cid=5 + i) for i, entry in enumerate(entries)]
        with patch("app.resync.github.list_pulls", return_value=[self.pr]), \
             patch("app.resync.github.list_comments", return_value=comments):
            return resync.resync(queue_open_heads=False, **kwargs)

    def row(self, *, entry=None, status="verified"):
        entry = entry or self.entry()
        detail = {"contract": entry["contract"], "source_ref": entry["source_ref"],
                  "receipt": {key: entry[key] for key in resync.RECEIPT_KEYS}}
        with self.sessions() as session:
            user = User(login="alice", github_id=42)
            session.add(user)
            session.flush()
            sub = Submission(id=self.sid, track=entry["track"], commit=self.commit, source_repo="https://github.com/owner/entries.git",
                             user_id=user.id, pr_number=7, pr_url="https://github.com/owner/entries/pull/7",
                             claim=19 if status == "verified" else None, status=status,
                             created_at=resync._time(entry["created_at"]),
                             finished_at=resync._time("2026-09-01T10:30:00Z") if status in resync.FINISHED else None,
                             detail=json.dumps(detail))
            session.add(sub)
            session.commit()
            return sub

    def test_closed_force_pushed_receipt_restores_frozen_author_and_pending_head(self):
        with patch("app.resync.github.verify_source_ref") as verify, \
             patch("app.source_archive._export_exact") as export:
            result = self.restore([self.entry(description=None)])
            self.assertEqual(result, {"restored": 1, "promoted": 0, "queued": 1})
            self.assertEqual(self.restore([self.entry(description=None)])["restored"], 0)
        verify.assert_called_with("owner/entries", self.sid, self.commit, f"refs/tags/ots-source/{self.sid}")
        export.assert_not_called()
        with self.sessions() as session:
            sub = session.get(Submission, self.sid)
            self.assertEqual((sub.status, sub.commit, sub.source_repo), ("pending", self.commit, "https://github.com/owner/entries.git"))
            self.assertEqual((sub.user.login, sub.user.github_id), ("alice", 42))
            self.assertEqual(sub.created_at, resync._time("2026-09-01T10:00:00.123456Z"))
            self.assertEqual(sub.co_authors_list, ["Bob Smith"])
            self.assertEqual(sub.assisted_by, "Model X")
            self.assertIsNone(sub.description)
            self.assertIsNone(sub.claim)
            self.assertIsNone(sub.log_path)
            self.assertEqual(sub.detail_dict["receipt"]["contract_commit"], "c" * 40)

    def test_pending_ref_missing_or_mismatched_is_not_queued(self):
        with patch("app.resync.github.verify_source_ref", side_effect=ValueError("mismatch")):
            result = self.restore([self.entry()])
        self.assertEqual(result["restored"], 0)
        self.assertTrue(result["errors"])
        with patch("app.resync.github.verify_source_ref") as verify:
            result = self.restore([self.entry(source_ref="refs/tags/ots-source/" + "2" * 32)])
        self.assertEqual(result["restored"], 0)
        verify.assert_not_called()

    def test_malformed_receipt_never_falls_back_to_current_pr(self):
        self.pr["user"] = {"login": "mallory", "id": 7}
        for change in ({"author": None}, {"contract_commit": "unknown"}, {"created_at": "bad"},
                       {"submission_root": "../../private"}, {"source_ref": None}):
            with self.subTest(change=change), patch("app.resync.github.verify_source_ref"):
                self.assertEqual(self.restore([self.entry(**change)])["restored"], 0)

    def test_completed_verdict_survives_missing_tag_and_never_fetches_zip_on_sync(self):
        value = self.entry(status="verified", claim=19, finished_at="2026-09-01T11:00:00Z")
        with patch("app.resync.github.verify_source_ref", side_effect=ValueError("deleted")) as verify, \
             patch("app.source_archive.rebuild_cache") as recover:
            self.assertEqual(self.restore([value])["restored"], 1)
        verify.assert_not_called()
        recover.assert_not_called()
        with self.sessions() as session:
            sub = session.get(Submission, self.sid)
            self.assertEqual(sub.status, "verified")
            self.assertTrue(sub.is_record)
            self.assertIsNone(sub.log_path)

    def test_restored_record_requeues_missing_main_snapshot_publication(self):
        value = self.entry(status="verified", claim=19, finished_at="2026-09-01T11:00:00Z")
        self.restore([value])
        with self.sessions() as session:
            self.assertIsNotNone(session.get(GithubReport, self.sid))
            current = session.get(Submission, self.sid)
            current.detail = json.dumps(current.detail_dict | {"record_snapshot":
                {"commit": "e" * 40, "published": True, "reason": "published"}})
            session.delete(session.get(GithubReport, self.sid))
            session.commit()
        self.restore([value])
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, self.sid))

    def test_failure_summary_is_bounded_and_survives_without_original_logs(self):
        value = self.entry(status="failed", finished_at="2026-09-01T11:00:00Z",
                           failure={"code": "x" * 200, "message": "error" * 2000})
        self.restore([value])
        with self.sessions() as session:
            sub = session.get(Submission, self.sid)
            self.assertEqual(sub.detail_dict["failure"], {"code": "x" * 120, "message": "error" * 800})
            self.assertIsNone(sub.log_path)

    def test_retry_receipt_uses_event_time_and_copied_old_receipt_cannot_win(self):
        failed = self.entry(status="failed", finished_at="2026-09-01T10:30:00Z")
        retry = self.entry(created_at="2026-09-01T11:00:00Z")
        comments = [self.comment(failed, cid=1), self.comment(retry, cid=2)]
        self.assertEqual(resync.latest_verdicts(comments, "ots-bot")[0][0]["status"], "pending")
        verified = self.entry(status="verified", claim=19, finished_at="2026-09-01T12:00:00Z")
        comments.append(self.comment(verified, cid=3))
        comments.append(self.comment(retry, cid=4, edited="2026-09-02T12:00:00Z"))
        for order in (comments, comments[::-1]):
            self.assertEqual(resync.latest_verdicts(order, "ots-bot")[0][0]["status"], "verified")
        self.row(status="failed")
        with self.sessions() as session:
            old = session.get(Submission, self.sid)
            old.started_at, old.log_path = old.created_at, "/unavailable/old-attempt.log"
            session.commit()
        with patch("app.resync.github.verify_source_ref"):
            self.assertEqual(self.restore([retry])["queued"], 1)
        with self.sessions() as session:
            sub = session.get(Submission, self.sid)
            self.assertEqual(sub.status, "pending")
            self.assertIsNone(sub.finished_at)
            self.assertIsNone(sub.started_at)
            self.assertIsNone(sub.log_path)

    def test_stale_remote_event_cannot_replace_a_newer_retry(self):
        retry = self.entry(created_at="2026-09-01T11:00:00Z")
        for status in ("admitting", "pending", "publishing", "verifying"):
            with self.subTest(status=status):
                with self.sessions() as session:
                    session.query(Submission).delete()
                    session.query(User).delete()
                    session.commit()
                self.row(entry=retry, status=status)
                stale = self.entry(status="failed", finished_at="2026-09-01T10:30:00Z")
                self.restore([stale])
                with patch("app.resync.github.verify_source_ref"):
                    self.restore([self.entry()])
                with self.sessions() as session:
                    current = session.get(Submission, self.sid)
                    self.assertEqual(current.status, status)
                    self.assertEqual(current.detail_dict["receipt"]["created_at"], retry["created_at"])

    def test_pending_receipt_does_not_restart_currently_running_job(self):
        self.row(status="verifying")
        with patch("app.resync.github.verify_source_ref"):
            self.restore([self.entry(created_at="2026-09-02T10:00:00Z")])
        with self.sessions() as session:
            self.assertEqual(session.get(Submission, self.sid).status, "verifying")

    def test_receipt_recovers_crash_after_comment_before_admission_commit(self):
        self.row(status="admitting")
        with patch("app.resync.github.verify_source_ref"):
            result = self.restore([self.entry()])
        self.assertEqual(result["queued"], 1)
        with self.sessions() as session:
            self.assertEqual(session.get(Submission, self.sid).status, "pending")

    def make_expected(self, sub):
        files = self.data / "original"
        files.mkdir()
        (files / "Solution.lean").write_bytes(b"-- exact bytes\r\n\xff\x00\n")
        (files / "claim.txt").write_bytes(b"19\n")
        (files / "NOTES.md").write_bytes(b"Original idea\n")
        meta = source_archive.archives.save_source(self.data / "original-store", self.sid, files,
            source_repo="https://github.com/deleted-fork/entries.git", commit=self.commit, track=sub.track,
            submission_root=self.root, contract=sub.detail_dict["contract"])
        with self.sessions() as session:
            current = session.get(Submission, self.sid)
            current.detail = json.dumps(current.detail_dict | {"source_archive": meta})
            session.commit()
            sub = current
        def export(source, commit, root, destination):
            self.assertEqual(source, "https://github.com/owner/entries.git")
            self.assertEqual(commit, self.commit)
            self.assertEqual(root, self.root)
            shutil.copytree(files, destination / root)
        return sub, meta, export

    def test_cache_reconstructs_exact_bytes_and_historical_manifest_from_base_repo(self):
        sub, expected, export = self.make_expected(self.row())
        with patch("app.github.verify_source_ref") as verify, \
             patch("app.source_archive._export_exact", side_effect=export):
            result = rebuild.rebuild_sources()
        self.assertEqual(result, {"restored": 1, "cached": 0, "skipped": 0, "errors": []})
        verify.assert_called_once()
        with self.sessions() as session:
            current = session.get(Submission, self.sid)
            self.assertEqual(current.detail_dict["source_archive"], expected)
            self.assertEqual((current.status, current.claim, current.finished_at), (sub.status, sub.claim, sub.finished_at))
            self.assertEqual(current.notes, "Original idea")
            self.assertIsNone(current.log_path)
        self.assertEqual(source_archive.archives.read_validated_bytes(source_archive.directory(), expected),
                         source_archive.archives.read_validated_bytes(self.data / "original-store", expected))
        with patch("app.github.verify_source_ref") as verify, patch("app.source_archive._export_exact") as fetch:
            self.assertEqual(rebuild.rebuild_sources()["cached"], 1)
        verify.assert_not_called()
        fetch.assert_not_called()

    def test_digest_mismatch_is_not_published_and_does_not_change_verdict(self):
        sub, expected, export = self.make_expected(self.row())
        expected["sha256"] = "f" * 64
        with self.sessions() as session:
            current = session.get(Submission, self.sid)
            current.detail = json.dumps(current.detail_dict | {"source_archive": expected})
            session.commit()
        with patch("app.github.verify_source_ref"), patch("app.source_archive._export_exact", side_effect=export):
            result = rebuild.rebuild_sources()
        self.assertIn("does not match", result["errors"][0]["error"])
        self.assertFalse(source_archive.directory().exists())
        with self.sessions() as session:
            current = session.get(Submission, self.sid)
            self.assertEqual(current.status, "verified")
            self.assertEqual(current.detail_dict["source_archive"], expected)

    def test_failed_source_fetch_preserves_result_and_reports_error(self):
        self.row()
        with patch("app.github.verify_source_ref", side_effect=ValueError("deleted ref")):
            result = rebuild.rebuild_sources()
        self.assertEqual(result["restored"], 0)
        self.assertIn("pinned source ref unavailable", result["errors"][0]["error"])
        with self.sessions() as session:
            self.assertEqual(session.get(Submission, self.sid).status, "verified")

    def test_legacy_cache_uses_exact_base_commit_without_claiming_pin_guarantee(self):
        sub, expected, export = self.make_expected(self.row())
        with self.sessions() as session:
            current = session.get(Submission, self.sid)
            current.detail = json.dumps({"contract": expected["contract"], "source_archive": expected})
            session.commit()
        with patch("app.github.verify_source_ref") as verify, patch("app.source_archive._export_exact", side_effect=export):
            self.assertEqual(rebuild.rebuild_sources()["restored"], 1)
        verify.assert_not_called()

    def test_source_export_never_inherits_credentials_or_git_configuration(self):
        destination = self.data / "export"
        poison = {"GITHUB_TOKEN": "secret", "GITHUB_WEBHOOK_SECRET": "secret", "GH_TOKEN": "secret",
                  "GIT_ASKPASS": "/credential-helper", "GIT_CONFIG_PARAMETERS": "unsafe", "PYTHONPATH": "/untrusted"}
        completed = subprocess.CompletedProcess([], 0, self.commit + "\n", "")
        with patch.dict(os.environ, poison), patch("app.source_archive.subprocess.run", return_value=completed) as run:
            source_archive._export_exact("https://github.com/owner/entries.git", self.commit, self.root, destination)
        env = run.call_args.kwargs["env"]
        self.assertFalse(set(poison) & set(env))
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "")
        self.assertNotIn("verify.py", run.call_args.args[0])

    def test_real_bounded_export_preserves_binary_bytes_without_candidate_execution(self):
        repo = self.data / "git-fixture"
        root = repo / self.root
        root.mkdir(parents=True)
        raw = b"-- source-only fixture\r\n\xff\x00\n"
        (root / "Solution.lean").write_bytes(raw)
        (root / "claim.txt").write_bytes(b"19\n")
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "--quiet", "-m", "source fixture"], check=True, capture_output=True)
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        destination = self.data / "real-export"
        source_archive._export_exact(str(repo), sha, self.root, destination)
        self.assertEqual((destination / self.root / "Solution.lean").read_bytes(), raw)

    def test_explicit_command_defaults_to_receipts_without_new_admission_or_sources(self):
        with patch("app.rebuild.init_db") as init, \
             patch("app.rebuild.resync.resync", return_value={"restored": 2, "queued": 1, "promoted": 0}) as sync, \
             patch("app.rebuild.rebuild_sources") as sources, patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(rebuild.main([]), 0)
        init.assert_called_once()
        sync.assert_called_once_with(queue_open_heads=False)
        sources.assert_not_called()
        self.assertIn("missing logs remain unavailable", json.loads(out.getvalue())["logs"])

    def test_command_reports_partial_cache_failure_with_nonzero_exit(self):
        with patch("app.rebuild.init_db"), patch("app.rebuild.resync.resync", return_value={"restored": 0}), \
             patch("app.rebuild.rebuild_sources", return_value={"errors": [{"id": self.sid, "error": "missing"}]}) as sources, \
             patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(rebuild.main(["--sources", "--limit", "2"]), 1)
        sources.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
