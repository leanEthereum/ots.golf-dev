"""Public source downloads are bound to retained bytes, not the current pull-request head."""
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import source_archive
from app.config import settings


class SourceDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ots-source-download-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = patch.object(settings, "data_dir", self.root)
        self.config.start()
        self.addCleanup(self.config.stop)
        files = self.root / "input"
        files.mkdir()
        (files / "Solution.lean").write_text("-- public fixture\n")
        (files / "claim.txt").write_text("19\n")
        (files / "NOTES.md").write_text("## Original checked idea\n")
        self.sub = SimpleNamespace(id="1" * 32, commit="a" * 40, track="lower-generality-1", detail_dict={"contract": "b" * 64})
        self.meta = source_archive.archives.save_source(source_archive.directory(), self.sub.id, files,
            source_repo="https://github.com/author/proofs.git", commit=self.sub.commit, track=self.sub.track,
            submission_root="formal/Submissions/LowerGenerality1", contract="b" * 64)

    def test_notes_come_from_the_retained_checked_root(self):
        self.sub.detail_dict["source_archive"] = self.meta
        (self.root / "input" / "NOTES.md").unlink()
        self.assertEqual(source_archive.read_notes(self.sub), "## Original checked idea")

    def test_timeout_can_recover_archive_without_final_result_json(self):
        self.assertEqual(source_archive.recover_metadata(self.sub), self.meta)
        self.assertIsNone(source_archive.metadata_for_submission(self.sub))

    def test_download_is_attachment_and_matches_digest(self):
        self.sub.detail_dict["source_archive"] = self.meta
        response = source_archive.download_response(self.sub)
        self.assertEqual(response.media_type, "application/zip")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.headers["etag"], '"' + self.meta["sha256"] + '"')
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertTrue(source_archive.is_available(self.sub))
        self.assertEqual(hashlib.sha256(response.body).hexdigest(), self.meta["sha256"])
        self.assertEqual(int(response.headers["content-length"]), self.meta["size_bytes"])

    def test_response_never_reopens_archive_after_validation(self):
        self.sub.detail_dict["source_archive"] = self.meta
        response = source_archive.download_response(self.sub)
        checked_bytes = response.body
        path = source_archive.archives.object_path(source_archive.directory(), self.meta)
        private = self.root / "private.txt"
        private.write_bytes(b"private fixture must never be downloaded")
        path.unlink()
        path.symlink_to(private)
        self.assertEqual(response.body, checked_bytes)
        self.assertEqual(hashlib.sha256(response.body).hexdigest(), self.meta["sha256"])
        self.assertNotEqual(response.body, private.read_bytes())
        with self.assertRaises(HTTPException):
            source_archive.download_response(self.sub)

    def test_missing_or_corrupt_object_returns_unavailable(self):
        self.sub.detail_dict["source_archive"] = self.meta
        path = source_archive.validated_path(self.sub)
        path.write_bytes(b"corrupt")
        with self.assertRaises(HTTPException) as error:
            source_archive.download_response(self.sub)
        self.assertEqual(error.exception.status_code, 404)
        path.unlink()
        self.assertFalse(source_archive.is_available(self.sub))
        self.assertEqual(source_archive.metadata_for_submission(self.sub), self.meta)

    def test_wrong_commit_contract_and_path_like_digest_are_not_downloaded(self):
        for key, value in (("commit", "c" * 40), ("contract", "d" * 64), ("sha256", "../../private")):
            self.sub.detail_dict["source_archive"] = dict(self.meta, **{key: value})
            with self.subTest(key=key), self.assertRaises(HTTPException):
                source_archive.download_response(self.sub)

    def test_recovery_requires_the_frozen_contract(self):
        self.sub.detail_dict["contract"] = "d" * 64
        with self.assertRaises(source_archive.ArchiveError):
            source_archive.recover_metadata(self.sub)
        self.sub.detail_dict.pop("contract")
        with self.assertRaises(source_archive.ArchiveError):
            source_archive.recover_metadata(self.sub)


if __name__ == "__main__":
    unittest.main()
