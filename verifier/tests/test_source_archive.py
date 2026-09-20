"""Exact source retention, crash-safe publication and retry; no Lean or network required."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

VERIFIER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VERIFIER))
import source_archive as archive
import verify


class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ots-archive-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sub = self.root / "input"
        self.sub.mkdir()
        (self.sub / "Solution.lean").write_bytes(b"-- exact source\r\n")
        (self.sub / "claim.txt").write_bytes(b"19\n")
        (self.sub / "NOTES.md").write_bytes(b"a note\n")
        self.store = self.root / "sources"
        self.sid = "1" * 32
        self.identity = dict(source_repo="https://github.com/author/proofs.git", commit="a" * 40,
                             track="lower-generality-1", submission_root="formal/Submissions/LowerGenerality1",
                             contract="b" * 64)

    def save(self, sid=None):
        return archive.save_source(self.store, sid or self.sid, self.sub, **self.identity)

    def test_exact_deterministic_archive_and_safe_layout(self):
        first = self.save()
        second = self.save("2" * 32)
        self.assertEqual(first, second)
        self.assertEqual(archive.read_metadata(self.store, self.sid), first)
        path = archive.validated_path(self.store, first)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), first["sha256"])
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.read(self.identity["submission_root"] + "/Solution.lean"), b"-- exact source\r\n")
            self.assertEqual(len(z.infolist()), 4)
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))

    def test_historical_bytes_survive_source_change_or_removal(self):
        meta = self.save()
        original = archive.validated_path(self.store, meta).read_bytes()
        (self.sub / "Solution.lean").write_text("-- newer head\n")
        with self.assertRaises(archive.ArchiveError):
            self.save()
        shutil.rmtree(self.sub)
        self.assertEqual(archive.validated_path(self.store, meta).read_bytes(), original)
        restored = self.root / "retry"
        archive.restore_source(self.store, meta, restored, **{k: self.identity[k] for k in
            ("commit", "track", "contract", "submission_root")})
        self.assertEqual((restored / self.identity["submission_root"] / "Solution.lean").read_bytes(), b"-- exact source\r\n")

    def test_retry_refuses_wrong_commit_track_or_contract(self):
        meta = self.save()
        for key, value in (("commit", "c" * 40), ("track", "upper-compressions"), ("contract", "d" * 64)):
            expected = {k: self.identity[k] for k in ("commit", "track", "contract", "submission_root")}
            expected[key] = value
            with self.subTest(key=key), self.assertRaises(archive.ArchiveError):
                archive.restore_source(self.store, meta, self.root / "retry", **expected)
        self.assertFalse((self.root / "retry").exists())

    def test_corruption_and_symlinks_are_never_served(self):
        meta = self.save()
        path = archive.object_path(self.store, meta)
        path.write_bytes(b"corrupt")
        with self.assertRaises(archive.ArchiveError):
            archive.validated_path(self.store, meta)
        path.unlink()
        path.symlink_to(self.sub / "Solution.lean")
        with self.assertRaises(OSError):
            archive.validated_path(self.store, meta)

    def test_rejects_unsafe_names_and_metadata(self):
        for key, value in (("sha256", "../outside"), ("size_bytes", True),
                           ("submission_root", "../elsewhere"), ("commit", "main")):
            meta = self.save()
            meta[key] = value
            with self.subTest(key=key), self.assertRaises(archive.ArchiveError):
                archive.validate_metadata(meta)
        with self.assertRaises(archive.ArchiveError):
            archive.read_metadata(self.store, "../outside")
        (self.sub / "Extra.lean").symlink_to(self.sub / "Solution.lean")
        with self.assertRaises(OSError):
            self.save("3" * 32)

    def test_missing_archive_and_missing_index_are_distinct(self):
        self.assertIsNone(archive.read_metadata(self.store, self.sid))
        meta = self.save()
        archive.object_path(self.store, meta).unlink()
        self.assertEqual(archive.read_metadata(self.store, self.sid), meta)
        with self.assertRaises(OSError):
            archive.validated_path(self.store, meta)

    def test_no_partial_index_on_publication_failure(self):
        original = archive._publish
        def fail_sidecar(path, data):
            if path.suffix == ".json":
                raise OSError("simulated interrupted sidecar publication")
            return original(path, data)
        with patch.object(archive, "_publish", side_effect=fail_sidecar), self.assertRaises(OSError):
            self.save()
        self.assertIsNone(archive.read_metadata(self.store, self.sid))
        self.assertEqual(len(list(self.store.glob("*.zip"))), 1)
        meta = self.save()
        self.assertEqual(archive.read_metadata(self.store, self.sid), meta)
        self.assertEqual(list(self.store.glob(".archive-*")), [])

    def test_low_disk_space_preserves_room_for_failure_record(self):
        with patch.object(archive.shutil, "disk_usage", return_value=SimpleNamespace(free=1)), \
                self.assertRaises(archive.ArchiveError):
            self.save()
        self.assertEqual(list(self.store.iterdir()), [])

    def test_archive_failure_prevents_any_candidate_compilation(self):
        trusted = self.root / "trusted"
        (trusted / "verifier").mkdir(parents=True)
        cfg = json.loads((VERIFIER.parent / "challenges.json").read_text())
        (trusted / "challenges.json").write_text(json.dumps(cfg))
        (trusted / cfg["contract"]["pin_file"]).write_text("fixture pin\n")
        def export(source, commit, rel, dest, **kwargs):
            shutil.copytree(self.sub, dest / rel)
            return commit
        argv = ["verify.py", self.identity["track"], "--source", "fixture", "--commit", self.identity["commit"],
                "--trusted", str(trusted), "--work", str(self.root / "work"), "--archive-dir", str(self.store),
                "--archive-id", self.sid, "--json"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(verify, "tools_env", return_value={}), \
                patch.object(verify.platform, "system", return_value="Darwin"), \
                patch.object(verify.signal, "signal"), patch.object(verify, "export_submission", side_effect=export), \
                patch.object(verify, "save_source", side_effect=archive.ArchiveError("archive unavailable")), \
                patch.object(verify.subprocess, "Popen") as compiler, contextlib.redirect_stdout(output):
            self.assertEqual(verify.main(), 1)
        compiler.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
