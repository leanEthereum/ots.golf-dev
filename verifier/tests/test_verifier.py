"""Regression tests for the pre-compilation trust boundary; no Lean or network needed."""
from __future__ import annotations

import fcntl
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

VERIFIER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VERIFIER))
from check_submission import check, header_imports
from contract import ContractError, read_claim
from render_challenge import render
from linux_exec import isolation_check
from linux_storage import MAX_WORK_BYTES, linux_work_preflight, mount_path
from verify import (PolicyReject, bounded_output, export_submission, linux_command, linux_preflight,
                    read_notes, run, tools_env)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"OTS_VERIFIER_HOST_DEV": "-1", "OTS_VERIFIER_HOST_SHM_DEV": "", "OTS_VERIFIER_HOST_PIDNS": "-1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.own_pid_namespace = patch("linux_exec.pid_namespace", return_value="7")
        self.own_pid_namespace.start()
        self.addCleanup(self.own_pid_namespace.stop)
        self.readonly_mounts = patch("linux_exec.os.statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY))
        self.readonly_mounts.start()
        self.addCleanup(self.readonly_mounts.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="ots-policy-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = json.loads((VERIFIER.parent / "challenges.json").read_text())
        (self.root / "challenges.json").write_text(json.dumps(self.cfg))
        self.rel = "formal/Submissions/LowerGenerality3"
        self.sub = self.root / self.rel
        self.sub.mkdir(parents=True)
        (self.sub / "Solution.lean").write_text("import Mathlib\nimport OptimalOTS.OracleAlgorithm\n")
        (self.sub / "claim.txt").write_bytes(b"1\n")

    def export(self, **kwargs):
        return export_submission(str(self.root), None, self.rel, self.root / "out", **kwargs)

    def commit(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Verifier tests",
                        "-c", "user.email=verifier@invalid.example", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "fixture"], check=True)

    def export_commit(self, **kwargs):
        return export_submission(str(self.root), "HEAD", self.rel, self.root / "out", **kwargs)

    def test_valid_submission_and_export(self):
        self.assertTrue(check(self.root, "lower-generality-3")["ok"])
        self.assertEqual(self.export(), "worktree")
        self.assertEqual((self.root / "out" / self.rel / "claim.txt").read_bytes(), b"1\n")

    def test_canonical_claims(self):
        claim = self.sub / "claim.txt"
        for data in (b"0", b"1\n", b"1000000"):
            with self.subTest(data=data):
                claim.write_bytes(data)
                self.assertEqual(read_claim(claim, 1000000), int(data))

    def test_malformed_claims_are_rejections_not_crashes(self):
        claim = self.sub / "claim.txt"
        for data in (b"", b"01", b"-1", b"+1", b"1\n\n", b"1\r\n", b" 1", b"1 ",
                     b"\xff", b"1000001", b"1" * 10000):
            with self.subTest(data=data[:20]):
                claim.write_bytes(data)
                with self.assertRaises(ContractError):
                    read_claim(claim, 1000000)
                self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_render_rejects_out_of_range_explicit_claim(self):
        for claim in (-1, 1000001):
            with self.subTest(claim=claim), self.assertRaises(ContractError):
                render(self.root, "lower-generality-3", claim)

    def test_ordinary_import_header(self):
        imports, error = header_imports("/- outer /- inner -/ -/\nimport Mathlib\n-- hi\nimport VCVio\nnamespace X")
        self.assertEqual(imports, ["Mathlib", "VCVio"])
        self.assertIsNone(error)

    def test_header_bypasses_are_rejected(self):
        for prefix in ("prelude", "module", "public import Mathlib", "private import Mathlib",
                       "meta import Mathlib", "public meta import Mathlib", "module import Mathlib",
                       "prelude\timport Mathlib", "import Mathlib OptimalOTS.WholeWords"):
            with self.subTest(prefix=prefix):
                (self.sub / "Solution.lean").write_text(prefix + "\nimport Submissions.UpperCompressions.Solution\n")
                self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_comments_cannot_hide_header_commands(self):
        # Lean treats comments as whitespace. Deleting them used to fuse these keywords,
        # making the policy checker stop before the forbidden import.
        for prefix in ("module/- comment -/prelude", "prelude/- comment -/import Mathlib",
                       "module/- outer /- nested -/ -/import Mathlib",
                       "module/- first\nsecond -/prelude"):
            with self.subTest(prefix=prefix):
                (self.sub / "Solution.lean").write_text(prefix + "\nimport Witnesses.Hidden\n")
                result = check(self.root, "lower-generality-3")
                self.assertFalse(result["ok"])
                self.assertTrue(any("not allowed" in error for error in result["errors"]))

    def test_header_comments_preserve_import_boundaries(self):
        imports, error = header_imports(
            "import/- comment -/Mathlib/- first\nsecond -/import VCVio\n"
            "def value := 1\n")
        self.assertEqual(imports, ["Mathlib", "VCVio"])
        self.assertIsNone(error)

    def test_quoted_module_paths_cannot_escape_library_prefixes(self):
        for module in ("Mathlib.«..».Witnesses.Hidden", "Mathlib.«../Witnesses/Hidden»",
                       "VCVio.«..».Witnesses.Hidden", "VCVio.«../Witnesses/Hidden»",
                       "Mathlib..Witnesses.Hidden", "Mathlib./Witnesses/Hidden"):
            with self.subTest(module=module):
                (self.sub / "Solution.lean").write_text(f"import {module}\n")
                result = check(self.root, "lower-generality-3")
                self.assertFalse(result["ok"])
                self.assertTrue(any("module names" in error for error in result["errors"]))

    def test_source_header_policy_does_not_restrict_runtime_loads(self):
        # This checks admission only: the source is never executed here. Runtime loads are
        # outside this policy; the comparator must still check the exported proof.
        (self.sub / "Solution.lean").write_text(
            "import Mathlib\nrun_cmd do\n"
            "  let _ ← Lean.importModules #[{ module := `Witnesses.Hidden }] {}\n"
            "  pure ()\n")
        self.assertTrue(check(self.root, "lower-generality-3")["ok"])

    def test_bom_does_not_hide_imports(self):
        (self.sub / "Solution.lean").write_text("\ufeffimport Submissions.UpperCompressions.Solution\n")
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_notes_are_admitted_exported_and_read(self):
        (self.sub / "NOTES.md").write_text("# Idea\n\nTried a wider cut; dead end.\n")
        self.assertTrue(check(self.root, "lower-generality-3")["ok"])
        self.export()
        self.assertEqual(read_notes(self.root / "out" / self.rel), "# Idea\n\nTried a wider cut; dead end.")
        self.assertIsNone(read_notes(self.sub.parent))
        (self.sub / "notes.txt").write_text("not admitted")
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_disallowed_and_missing_sibling_imports(self):
        for module in ("OptimalOTS", "OptimalOTS.Dag.Extra", "Submissions.UpperCompressions.Solution",
                       "OptimalOTS.OracleAlgorithm.Extra", "Submissions.LowerGenerality3.Absent"):
            with self.subTest(module=module):
                (self.sub / "Solution.lean").write_text(f"import {module}\n")
                self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_existing_sibling_import_is_allowed(self):
        (self.sub / "Helper.lean").write_text("import Mathlib\n")
        (self.sub / "Solution.lean").write_text("import Submissions.LowerGenerality3.Helper\n")
        self.assertTrue(check(self.root, "lower-generality-3")["ok"])

    def test_upper_compressions_header_imports_stay_in_allowed_modules(self):
        sub = self.root / "formal/Submissions/UpperCompressions"
        sub.mkdir(parents=True)
        (sub / "claim.txt").write_text("106\n")
        (sub / "Helper.lean").write_text("import OptimalOTS.OracleAlgorithm\n")
        solution = sub / "Solution.lean"
        solution.write_text("import Submissions.UpperCompressions.Helper\n")
        self.assertTrue(check(self.root, "upper-compressions")["ok"])
        for module in ("Submissions.UpperCompressions.Main", "OptimalOTS.AlgorithmWeak", "OptimalOTS.Riscv",
                       "OptimalOTS.OracleAlgorithm.Extra", "Submissions.LowerGenerality3.Proof"):
            with self.subTest(module=module):
                solution.write_text(f"import {module}\n")
                self.assertFalse(check(self.root, "upper-compressions")["ok"])

    def test_upper_compressions_requires_admissibility_security_and_cost(self):
        track = next(t for t in self.cfg["tracks"] if t["slug"] == "upper-compressions")
        template = self.root / track["challenge_template"]
        template.parent.mkdir(parents=True)
        template.write_text((VERIFIER.parent / track["challenge_template"]).read_text())
        rendered, claim = render(self.root, "upper-compressions", 105)
        self.assertEqual(claim, 105)
        source = rendered.read_text()
        self.assertIn("scheme.VerifyCostAtMost 105", source)
        self.assertIn("theorem admissible : scheme.Admissible := sorry", source)
        comparator = json.loads((VERIFIER.parent / track["comparator_config"]).read_text())
        prefix = "OptimalOTS.Challenge.UpperCompressions."
        self.assertEqual(set(comparator["theorem_names"]),
                         {prefix + name for name in ("admissible", "secure", "cost")})
        self.assertEqual(comparator["definition_names"], [prefix + "scheme"])

    def test_upper_riscv_requires_one_bundled_certificate(self):
        track = next(t for t in self.cfg["tracks"] if t["slug"] == "upper-riscv")
        self.assertIn("upper-riscv", self.cfg["upper_tracks"])
        self.assertEqual((track["kind"], track["framework"], track["cost_unit"]),
                         ("upper", "generality-3", "cycles"))
        self.assertFalse(any("upper_track" in f for f in self.cfg["frameworks"]))
        template = self.root / track["challenge_template"]
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text((VERIFIER.parent / track["challenge_template"]).read_text())
        rendered, claim = render(self.root, "upper-riscv", 229112)
        self.assertEqual(claim, 229112)
        source = rendered.read_text()
        self.assertIn("submission.Certificate 229112", source)
        self.assertIn("def submission : Riscv.Submission", source)
        comparator = json.loads((VERIFIER.parent / track["comparator_config"]).read_text())
        prefix = "OptimalOTS.Challenge.UpperRiscv."
        self.assertEqual(comparator["theorem_names"], [prefix + "certificate"])
        self.assertEqual(comparator["definition_names"], [prefix + "submission"])
        self.assertEqual(set(track["allowed_import_prefixes"]),
                         {"Mathlib", "VCVio", "OptimalOTS.Model", "OptimalOTS.Dag",
                          "OptimalOTS.OracleAlgorithm", "OptimalOTS.RiscvMachine", "OptimalOTS.Riscv"})
        for rel in (track["challenge_template"], track["comparator_config"]):
            self.assertIn(rel, self.cfg["protected"])

    def test_signing_failure_bound_is_a_contract_constant(self):
        model = (VERIFIER.parent / "formal/OptimalOTS/Model.lean").read_text()
        self.assertIn("def signingFailureBits : ℕ := 128", model)
        algorithm = (VERIFIER.parent / "formal/OptimalOTS/OracleAlgorithm.lean").read_text()
        self.assertIn("S.SigningFailureAtMost (1 / 2 ^ signingFailureBits)", algorithm)
        for slug in ("lower-generality-3", "upper-compressions", "upper-riscv"):
            with self.subTest(track=slug):
                track = next(t for t in self.cfg["tracks"] if t["slug"] == slug)
                self.assertNotIn("signing_failure_allowance", track)
                template = self.root / track["challenge_template"]
                template.parent.mkdir(parents=True, exist_ok=True)
                template.write_text((VERIFIER.parent / track["challenge_template"]).read_text())
                rendered, _ = render(self.root, slug, 7)
                self.assertNotIn("2 ^ 128", rendered.read_text())

    def test_invalid_utf8_source(self):
        (self.sub / "Solution.lean").write_bytes(b"\xff")
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])

    def test_filename_newline_is_rejected(self):
        (self.sub / "Sneaky.lean\n").write_text("")
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])
        with self.assertRaises(PolicyReject):
            self.export()

    def test_hidden_files_are_not_silently_ignored(self):
        (self.sub / ".DS_Store").write_bytes(b"fixture")
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])
        with self.assertRaises(PolicyReject):
            self.export()

    def test_directory_rejected_before_copy(self):
        (self.sub / "nested").mkdir()
        with self.assertRaises(PolicyReject):
            self.export()

    def test_symlink_rejected_before_read(self):
        (self.sub / "Secret.lean").symlink_to(self.root / "absent-secret")
        with self.assertRaises(PolicyReject):
            self.export()

    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.sub / "Pipe.lean")
        with self.assertRaises(PolicyReject):
            self.export()

    def test_root_symlink_is_rejected(self):
        original = self.root / "original"
        self.sub.rename(original)
        self.sub.symlink_to(original, target_is_directory=True)
        self.assertFalse(check(self.root, "lower-generality-3")["ok"])
        with self.assertRaises(PolicyReject):
            self.export()

    def test_per_file_limit_applies_before_copy(self):
        with self.assertRaises(PolicyReject):
            self.export(max_file_bytes=2)
        self.assertFalse((self.root / "out" / self.rel / "Solution.lean").exists())

    def test_total_limit_applies_before_copy(self):
        with self.assertRaises(PolicyReject):
            self.export(max_total_bytes=3)

    def test_file_count_limit_applies_before_copy(self):
        with self.assertRaises(PolicyReject):
            self.export(max_files=1)

    def test_git_export_is_byte_exact_despite_archive_attributes(self):
        # Git archive would omit this claim and rewrite this source: neither is allowed.
        (self.root / ".gitattributes").write_text(
            f"{self.rel}/claim.txt export-ignore\n{self.rel}/Solution.lean export-subst\n")
        source = b"import Mathlib\n-- $Format:%H$\n"
        (self.sub / "Solution.lean").write_bytes(source)
        self.commit()
        result = self.export_commit()
        self.assertRegex(result, r"^[a-f0-9]{40}$")
        self.assertEqual((self.root / "out" / self.rel / "Solution.lean").read_bytes(), source)
        self.assertEqual((self.root / "out" / self.rel / "claim.txt").read_bytes(), b"1\n")

    def test_git_symlink_is_rejected(self):
        (self.sub / "Secret.lean").symlink_to("/etc/passwd")
        self.commit()
        with self.assertRaises(PolicyReject):
            self.export_commit()

    def test_git_nested_tree_is_rejected(self):
        (self.sub / "nested").mkdir()
        (self.sub / "nested" / "Extra.lean").write_text("")
        self.commit()
        with self.assertRaises(PolicyReject):
            self.export_commit()

    def test_git_blob_size_is_checked_before_read(self):
        self.commit()
        with self.assertRaises(PolicyReject):
            self.export_commit(max_file_bytes=2)

    def remote_fixture(self):
        self.commit()
        subprocess.run(['git', '-C', str(self.root), 'config', 'uploadpack.allowFilter', 'true'], check=True)
        return subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()

    def traced_remote_export(self, commit, **kwargs):
        trace = self.root / 'trace.json'
        with patch.dict(os.environ, {'GIT_TRACE2_EVENT': str(trace)}):
            return export_submission(self.root.as_uri(), commit, self.rel, self.root / 'out', **kwargs)

    def remote_fetches(self):
        events = [json.loads(line) for line in (self.root / 'trace.json').read_text().splitlines()]
        return [e['argv'] for e in events if e['event'] == 'start' and 'fetch' in e.get('argv', [])]

    def test_blobless_remote_batches_184_modules_without_fetching_other_roots(self):
        expected = {'claim.txt': b'1\n', 'Solution.lean': (self.sub / 'Solution.lean').read_bytes()}
        for i in range(183):
            expected[f'Proof{i:03}.lean'] = f'def value{i} : Nat := {i}\n'.encode()
        for name, data in expected.items():
            (self.sub / name).write_bytes(data)
        outside = self.root / 'unrelated.bin'
        outside.write_bytes(b'not part of the submission' * 10000)
        outside_oid = subprocess.check_output(['git', 'hash-object', str(outside)], text=True).strip()
        commit = self.remote_fixture()
        probes = []

        def inspect(cmd, limit, timeout=60):
            if 'ls-tree' in cmd and '-l' in cmd:
                # The size listing may not lazily download anything. Every selected blob
                # must already be present, and unrelated blobs must still be absent.
                repo = cmd[cmd.index('-C') + 1]
                env = {**os.environ, 'GIT_NO_LAZY_FETCH': '1'}
                absent = subprocess.run(['git', '-C', repo, 'cat-file', '-e', outside_oid],
                                        env=env, capture_output=True)
                self.assertNotEqual(absent.returncode, 0)
                for name in expected:
                    subprocess.run(['git', '-C', repo, 'cat-file', '-e', f'{commit}:{self.rel}/{name}'],
                                   env=env, capture_output=True, check=True)
                probes.append(True)
            return bounded_output(cmd, limit, timeout)

        with patch('verify.bounded_output', side_effect=inspect):
            self.assertEqual(self.traced_remote_export(commit), commit)
        self.assertEqual(probes, [True])
        fetches = self.remote_fetches()
        self.assertEqual(len(fetches), 2, 'one tree fetch plus one batch, no per-blob network requests')
        self.assertNotIn(outside_oid, fetches[1])
        for name, data in expected.items():
            self.assertEqual((self.root / 'out' / self.rel / name).read_bytes(), data)

    def test_remote_rejects_layout_before_fetching_blobs(self):
        for failure in ['count', 'directory', 'symlink', 'filename']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sub = root / self.rel
                sub.mkdir(parents=True)
                (sub / 'claim.txt').write_text('1\n')
                (sub / 'Solution.lean').write_text('')
                if failure == 'directory':
                    (sub / 'nested').mkdir()
                    (sub / 'nested' / 'Extra.lean').write_text('')
                elif failure == 'symlink':
                    (sub / 'Link.lean').symlink_to('/etc/passwd')
                elif failure == 'filename':
                    (sub / 'bad.txt').write_text('')
                old_root, self.root = self.root, root
                try:
                    commit = self.remote_fixture()
                    with self.assertRaises(PolicyReject):
                        self.traced_remote_export(commit, max_files=1 if failure == 'count' else 200)
                    self.assertEqual(len(self.remote_fetches()), 1)
                    self.assertEqual(list((root / 'out' / self.rel).iterdir()), [])
                finally:
                    self.root = old_root

    def test_remote_size_limits_still_apply_before_exporting_files(self):
        commit = self.remote_fixture()
        for kwargs in [{'max_file_bytes': 2}, {'max_total_bytes': 3}]:
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / 'out'
                with self.assertRaises(PolicyReject):
                    export_submission(self.root.as_uri(), commit, self.rel, out, **kwargs)
                self.assertEqual(list((out / self.rel).iterdir()), [])

    def test_git_commit_cannot_inject_an_option(self):
        with self.assertRaises(PolicyReject):
            export_submission(str(self.root), "--help", self.rel, self.root / "out")

    def test_bounded_git_output(self):
        with self.assertRaises(PolicyReject):
            bounded_output([sys.executable, "-c", "print('x' * 100000)"], 1024)

    def test_bounded_command_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded_output([sys.executable, "-c", "import time; time.sleep(5)"], 1024, timeout=0.05)

    def assert_helper_times_out(self, code: str):
        """A separate watchdog makes the regression fail instead of hanging the test runner."""
        pid_file = self.root / "helper-pgid"
        command = [sys.executable, "-c",
                   f"from pathlib import Path; import os; Path({str(pid_file)!r}).write_text(str(os.getpid()))\n" + code]
        probe = f"""
import subprocess, sys
sys.path.insert(0, {str(VERIFIER)!r})
from verify import bounded_output, _BOUNDED_PROCESSES
try:
    bounded_output({command!r}, 1024 * 1024, timeout=0.5)
except subprocess.TimeoutExpired:
    assert not _BOUNDED_PROCESSES, 'helper remained registered after cleanup'
else:
    raise AssertionError('the helper deadline did not fire')
"""
        def cleanup_fixture():
            # Run after the test's cleanup assertions, and also if the watchdog caught a hang.
            if pid_file.exists():
                try:
                    os.killpg(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.addCleanup(cleanup_fixture)
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 3)

    def test_exited_leader_with_descendant_holding_stdout_obeys_deadline(self):
        ready, lock_path = self.root / "child-ready", self.root / "child-lock"
        self.assert_helper_times_out(f"""
import fcntl, time
if os.fork() == 0:
    with open({str(lock_path)!r}, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        Path({str(ready)!r}).write_text('ready')
        time.sleep(30)
else:
    while not Path({str(ready)!r}).exists():
        time.sleep(0.005)
    os._exit(0)
""")
        self.assertTrue(ready.is_file(), 'the fixture must actually start its descendant')
        # Advisory locks disappear when a process dies, including before its orphan is reaped.
        with lock_path.open('a') as lock:
            deadline = time.monotonic() + 1
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        self.fail('the helper left its descendant running after timeout')
                    time.sleep(0.005)

    def test_closed_output_does_not_remove_the_leader_deadline(self):
        self.assert_helper_times_out('import time; os.close(1); os.close(2); time.sleep(30)')

    def test_continuing_output_does_not_reset_the_deadline(self):
        self.assert_helper_times_out("import time\nwhile True:\n    os.write(1, b'x'); time.sleep(0.005)")

    def test_bounded_output_accepts_exact_limit_and_rejects_next_byte(self):
        self.assertEqual(bounded_output([sys.executable, '-c', "import os; os.write(1, b'x' * 1024)"], 1024),
                         b'x' * 1024)
        self.assertEqual(bounded_output([sys.executable, '-c', 'pass'], 0), b'')
        for count, limit in ((1025, 1024), (1, 0)):
            with self.subTest(count=count, limit=limit), self.assertRaises(PolicyReject):
                bounded_output([sys.executable, '-c', f"import os; os.write(1, b'x' * {count})"], limit)

    def test_bounded_output_preserves_nonzero_exit_and_stderr(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            bounded_output([sys.executable, '-c', "import os; os.write(2, b'fetch failed'); os._exit(7)"], 1024)
        self.assertEqual(error.exception.returncode, 7)
        self.assertEqual(error.exception.stderr, 'fetch failed')

    def test_fetch_helper_bounds_remote_progress(self):
        with patch("verify.LOG_CAP", 1024), self.assertRaises(PolicyReject):
            run([sys.executable, "-c", "import sys; sys.stderr.write('x' * 100000)"])

    def test_fetch_helper_uses_registered_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)

    def test_linux_refuses_root(self):
        with patch("verify.os.geteuid", return_value=0), self.assertRaisesRegex(ContractError, "root"):
            linux_preflight({})

    def test_linux_refuses_missing_systemd(self):
        with patch("verify.os.geteuid", return_value=1000), patch("verify.shutil.which", return_value=None):
            with self.assertRaisesRegex(ContractError, "unsandboxed"):
                linux_preflight({})

    def test_linux_refuses_missing_landlock(self):
        with patch("verify.os.geteuid", return_value=1000), patch("verify.shutil.which", return_value="/bin/tool"), \
             patch("verify.Path.is_file", return_value=False):
            with self.assertRaisesRegex(ContractError, "Landlock"):
                linux_preflight({})

    def test_linux_refuses_fake_landrun(self):
        fake = self.root / "fake.sh"
        fake.write_text("#!/bin/sh\nexec \"$@\"\n")
        with patch("verify.os.geteuid", return_value=1000), patch("verify.shutil.which", return_value="/bin/tool"), \
             patch("verify.Path.is_file", return_value=True), patch("verify.Path.read_text", return_value="landlock,yama\n"):
            with self.assertRaisesRegex(ContractError, "development shim"):
                linux_preflight({"COMPARATOR_LANDRUN": str(fake)})

    def test_linux_refuses_landlock_without_truncate_protection(self):
        fake = self.root / "landrun"
        fake.write_bytes(b"\x7fELFfixture")
        with patch("verify.os.geteuid", return_value=1000), patch("verify.shutil.which", return_value="/bin/tool"), \
             patch("verify.Path.is_file", return_value=True), patch("verify.Path.read_text", return_value="landlock\n"), \
             patch("verify.landlock_abi", return_value=2):
            with self.assertRaisesRegex(ContractError, "truncate"):
                linux_preflight({"COMPARATOR_LANDRUN": str(fake)})

    def test_tools_environment_requires_all_executables(self):
        tools = self.root / "verifier" / ".tools"
        tools.mkdir(parents=True)
        (tools / "env.sh").write_text('export COMPARATOR_BIN="/bin/sh"\n')
        with self.assertRaises(ContractError):
            tools_env(self.root)

    def test_linux_service_properties_cannot_silently_fall_back(self):
        cmd = linux_command(["comparator", "config.json"], self.root, {"PATH": "/usr/bin", "HOME": "/empty"},
                            {"memory_bytes": 1234, "wall_clock_seconds": 56}, "test-unit",
                            [Path("/srv/ots/data/ots.db")])
        for required in ("InaccessiblePaths=-/etc/ots -/srv/ots/data/ots.db", "MemoryMax=1234", "MemorySwapMax=0", "RuntimeMaxSec=56", "KillMode=control-group", "TimeoutStopSec=5", "SendSIGKILL=yes",
                         "TasksMax=512", "PrivatePIDs=yes", "ProcSubset=pid", "InaccessiblePaths=/sys", "PrivateDevices=yes", "PrivateIPC=yes",
                         "ProtectSystem=strict", f"ReadWritePaths={self.root / '.lake'}",
                         "SystemCallErrorNumber=EPERM",
                         "SystemCallFilter=~@network-io @debug ptrace process_vm_readv process_vm_writev "
                         "pidfd_getfd kill tkill tgkill pidfd_send_signal",
                         "RestrictAddressFamilies=~AF_UNIX", "NoNewPrivileges=yes"):
            self.assertIn(required, cmd)
        self.assertEqual(cmd[cmd.index("--"):][:3], ["--", "/usr/bin/env", "-i"])
        self.assertEqual(cmd[-6:], ["PATH=/usr/bin", "HOME=/empty", sys.executable,
                                   str(VERIFIER / "linux_exec.py"), "comparator", "config.json"])

    def test_linux_launcher_refuses_the_host_pid_namespace(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch("linux_exec.pid_namespace", return_value="-1"):
            with self.assertRaisesRegex(RuntimeError, "PID namespace"):
                isolation_check()

    def test_linux_launcher_refuses_permitted_sockets(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch("linux_exec.Path.read_bytes", side_effect=PermissionError), \
             patch("linux_exec.Path.iterdir", side_effect=PermissionError), patch("linux_exec.socket.socket"):
            with self.assertRaisesRegex(RuntimeError, "networking"):
                isolation_check()

    def test_linux_launcher_accepts_only_effective_isolation(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch("linux_exec.Path.read_bytes", side_effect=PermissionError), \
             patch("linux_exec.Path.iterdir", side_effect=PermissionError), \
             patch("linux_exec.socket.socket", side_effect=PermissionError), \
             patch("linux_exec.os.kill", side_effect=PermissionError):
            isolation_check()

    def test_linux_launcher_refuses_permitted_signals(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch("linux_exec.Path.read_bytes", side_effect=PermissionError), \
             patch("linux_exec.Path.iterdir", side_effect=PermissionError), \
             patch("linux_exec.socket.socket", side_effect=PermissionError), patch("linux_exec.os.kill"):
            with self.assertRaisesRegex(RuntimeError, "process signals"):
                isolation_check()

    def test_linux_launcher_refuses_shared_devices(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch.dict(os.environ, {"OTS_VERIFIER_HOST_DEV": str(Path("/dev").stat().st_dev)}):
            with self.assertRaisesRegex(RuntimeError, "private devices"):
                isolation_check()

    def test_linux_launcher_refuses_writable_trusted_mounts(self):
        with patch("linux_exec.sys.platform", "linux"), patch("linux_exec.os.geteuid", return_value=1000), \
             patch("linux_exec.os.statvfs", return_value=SimpleNamespace(f_flag=0)):
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                isolation_check()


class LinuxStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ots-storage-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.volume = self.root / "work"
        self.work = self.volume / "job"
        self.work.mkdir(parents=True)
        self.trusted = self.root / "repo"
        self.trusted.mkdir()
        self.state = self.root / "data"
        self.state.mkdir()
        self.device = os.makedev(0, 2)
        self.same_device = set()
        self.fs = "ext4"
        self.mount_root = "/"
        self.extra_mounts = ""
        self.capacity = 32 * 1024 ** 3
        original_stat = Path.stat

        def fake_stat(path, *args, **kwargs):
            result = list(original_stat(path, *args, **kwargs))
            result[2] = self.device if path.is_relative_to(self.volume) or path in self.same_device else os.makedev(0, 1)
            return os.stat_result(result)

        def mountinfo(_path, *args, **kwargs):
            return (f"1 0 0:1 / / rw - ext4 /dev/root rw\n"
                    f"2 1 0:2 {self.mount_root} {self.volume} rw - {self.fs} /dev/work rw\n" + self.extra_mounts)

        for mocked in (patch.dict(os.environ, {"OTS_WORK_DIR": str(self.volume), "OTS_DATA_DIR": str(self.state)}),
                       patch("linux_storage.Path.stat", fake_stat), patch("linux_storage.Path.read_text", mountinfo),
                       patch("linux_storage.os.statvfs", side_effect=lambda _: SimpleNamespace(f_blocks=self.capacity // 4096, f_frsize=4096))):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_bounded_dedicated_volume_is_allowed(self):
        linux_work_preflight(self.work, self.trusted)

    def test_missing_work_configuration_is_rejected(self):
        with patch.dict(os.environ, {"OTS_WORK_DIR": ""}), self.assertRaisesRegex(ContractError, "OTS_WORK_DIR"):
            linux_work_preflight(self.work, self.trusted)

    def test_unbounded_volume_is_rejected(self):
        self.capacity = MAX_WORK_BYTES + 4096
        with self.assertRaisesRegex(ContractError, "64 GiB"):
            linux_work_preflight(self.work, self.trusted)

    def test_same_filesystem_as_persistent_state_is_rejected(self):
        self.same_device.add(self.state)
        with self.assertRaisesRegex(ContractError, "persistent data"):
            linux_work_preflight(self.work, self.trusted)

    def test_same_filesystem_as_trusted_checkout_is_rejected(self):
        self.same_device.add(self.trusted)
        with self.assertRaisesRegex(ContractError, "trusted checkout"):
            linux_work_preflight(self.work, self.trusted)

    def test_same_filesystem_as_system_root_is_rejected(self):
        self.same_device.add(Path("/"))
        with self.assertRaisesRegex(ContractError, "system"):
            linux_work_preflight(self.work, self.trusted)

    def test_same_filesystem_as_home_is_rejected(self):
        self.same_device.add(Path.home())
        with self.assertRaisesRegex(ContractError, "home"):
            linux_work_preflight(self.work, self.trusted)

    def test_same_filesystem_as_warm_cache_is_rejected(self):
        cache = self.trusted / "cache"
        cache.mkdir()
        self.same_device.add(cache)
        with self.assertRaisesRegex(ContractError, "cache"):
            linux_work_preflight(self.work, self.trusted, cache)

    def loop_volume(self, allocated_blocks):
        original_exists = Path.exists
        return (patch("linux_storage.Path.exists",
                      lambda path: str(path) == "/sys/dev/block/0:2/loop" or original_exists(path)),
                patch("linux_storage.loop_backing_file", return_value=Path("/var/lib/ots-work.img")),
                patch("linux_storage.image_allocation", return_value=(4096 * 8, allocated_blocks * 512)))

    def test_fully_allocated_loop_volume_is_allowed(self):
        exists, backing, stat = self.loop_volume(allocated_blocks=8 * 8)
        with exists, backing, stat:
            linux_work_preflight(self.work, self.trusted)

    def test_sparse_loop_volume_is_rejected(self):
        exists, backing, stat = self.loop_volume(allocated_blocks=8)
        with exists, backing, stat, self.assertRaisesRegex(ContractError, "fully allocated"):
            linux_work_preflight(self.work, self.trusted)

    def test_loop_volume_with_unreadable_backing_file_is_rejected(self):
        exists, _, stat = self.loop_volume(allocated_blocks=64)
        with exists, stat, patch("linux_storage.loop_backing_file", return_value=None), \
                self.assertRaisesRegex(ContractError, "backing file"):
            linux_work_preflight(self.work, self.trusted)

    def test_bounded_tmpfs_is_allowed(self):
        self.fs = "tmpfs"
        linux_work_preflight(self.work, self.trusted)

    def test_work_outside_dedicated_volume_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "beneath"):
            linux_work_preflight(self.trusted, self.trusted)

    def test_shared_or_subvolume_filesystems_are_rejected(self):
        self.fs = "btrfs"
        with self.assertRaisesRegex(ContractError, "dedicated ext4"):
            linux_work_preflight(self.work, self.trusted)

    def test_bind_subtree_is_rejected(self):
        self.mount_root = "/elsewhere"
        with self.assertRaisesRegex(ContractError, "bind-mounted"):
            linux_work_preflight(self.work, self.trusted)

    def test_nested_mount_is_rejected(self):
        self.extra_mounts = f"3 2 0:3 / {self.work}/escape rw - ext4 /dev/escape rw\n"
        with self.assertRaisesRegex(ContractError, "nested mounts"):
            linux_work_preflight(self.work, self.trusted)

    def test_not_a_mount_root_is_rejected(self):
        with patch.dict(os.environ, {"OTS_WORK_DIR": str(self.work)}), self.assertRaises(ContractError):
            linux_work_preflight(self.work, self.trusted)

    def test_mountinfo_escapes_are_decoded(self):
        self.assertEqual(mount_path(r"/some\040space/with\134backslash"), Path("/some space/with\\backslash"))


if __name__ == "__main__":
    unittest.main()
