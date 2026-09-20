"""The submissions workspace pins the core and starts without submission roots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_submissions_repo import CORE_URL, ROOT, SUBMISSIONS_URL, git, prepare


class SubmissionsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'core'
        self.root.mkdir()
        git(self.root, 'init', '--initial-branch=main')
        git(self.root, 'config', 'user.name', 'Test')
        git(self.root, 'config', 'user.email', 'test@example.invalid')
        config = json.loads((ROOT / 'challenges.json').read_text())
        (self.root / 'challenges.json').write_text(json.dumps(config))
        pin = self.root / config['contract']['pin_file']
        pin.parent.mkdir(parents=True)
        pin.write_text('fixture pin\n')
        (self.root / 'LICENSE').write_text('Fixture license\n')
        # A stray root in the core must never be exported.
        stray = self.root / 'formal/Submissions/UpperCompressions'
        stray.mkdir(parents=True)
        (stray / 'Solution.lean').write_text('def fixture := 1\n')
        (stray / 'claim.txt').write_text('7\n')
        shutil.copytree(ROOT / 'tools/submissions_template', self.root / 'tools/submissions_template')
        git(self.root, 'add', '--all')
        git(self.root, 'commit', '-m', 'Fixture')

    def tearDown(self):
        self.temp.cleanup()

    def test_export_is_a_separate_repo_with_an_exact_core_pin(self):
        destination = Path(self.temp.name) / 'entries'
        result = prepare(self.root, destination)
        self.assertEqual(set(result['tracks']),
                         {'lower-generality-1', 'lower-generality-2', 'lower-generality-3', 'upper-compressions', 'upper-riscv'})
        self.assertEqual(git(destination, 'remote', 'get-url', 'origin'), SUBMISSIONS_URL)
        self.assertEqual(git(destination, 'config', '-f', '.gitmodules', 'submodule.contract.url'), CORE_URL)
        self.assertEqual(git(destination / '.contract', 'remote', 'get-url', 'origin'), CORE_URL)
        commit = git(self.root, 'rev-parse', 'HEAD')
        self.assertEqual(git(destination / '.contract', 'rev-parse', 'HEAD'), commit)
        self.assertIn('160000 ' + commit, git(destination, 'ls-files', '--stage', '.contract'))
        self.assertEqual(result['contract_id'], hashlib.sha256(b'fixture pin\n').hexdigest())
        names = set(git(destination, 'ls-files').splitlines())
        self.assertNotIn('service/app/main.py', names)
        self.assertNotIn('formal/OptimalOTS/Dag.lean', names)
        self.assertFalse(any(name.startswith('formal/') for name in names))
        self.assertEqual(names, {'.contract', '.github/PULL_REQUEST_TEMPLATE.md', '.gitignore', '.gitmodules',
                                 'AGENTS.md', 'LICENSE', 'README.md', 'RISCV_PROFILES.md', 'riscv-profiles.json'})
        self.assertEqual((destination / 'LICENSE').read_text(), 'Fixture license\n')
        self.assertIn(commit, (destination / 'README.md').read_text())
        self.assertNotIn('{{CONTRACT_', (destination / 'README.md').read_text())
        self.assertEqual(git(self.root, 'status', '--porcelain'), '')

    def test_existing_destination_and_dirty_core_are_refused(self):
        destination = Path(self.temp.name) / 'entries'
        destination.mkdir()
        marker = destination / 'preserve'
        marker.write_text('existing work')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            prepare(self.root, destination)
        self.assertEqual(marker.read_text(), 'existing work')
        (self.root / 'challenges.json').write_text('{}')
        new = Path(self.temp.name) / 'new'
        with self.assertRaisesRegex(ValueError, 'commit the core changes'):
            prepare(self.root, new)
        self.assertFalse(new.exists())


if __name__ == '__main__':
    unittest.main()
