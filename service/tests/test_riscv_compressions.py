"""A supplemental bound must belong to this exact verified machine submission."""
import json
import unittest

from app import riscv_compressions
from app.config import settings
from app.db import Submission, User
import test_riscv_track


class CompressionBoundTests(unittest.TestCase):
    setUp = test_riscv_track.RiscvTrackTests.setUp
    tearDown = test_riscv_track.RiscvTrackTests.tearDown

    def real(self):
        entry = riscv_compressions._load(settings.repo_root / 'service' / 'riscv-compression-bounds.json')[0]
        sub = Submission(id=entry['id'], track='upper-riscv', claim=entry['cycles'],
                         commit=entry['commit'], status='verified',
                         source_repo=f'https://github.com/{entry["repository"]}.git',
                         pr_url=f'https://github.com/{entry["repository"]}/pull/11', pr_number=11,
                         detail=json.dumps({'contract': entry['contract']}),
                         user=User(login='scaraven'))
        self.session.add(sub)
        self.session.commit()
        return sub

    def test_bound_links_exact_source_and_preserves_cycle_claim(self):
        sub = self.real()
        html = self.client.get(f'/submissions/{sub.id}').text
        self.assertIn('≤ 170 compressions', html)
        self.assertIn('687 cycles', html)
        self.assertIn('scaraven', html)
        self.assertIn(f'/blob/{sub.commit}/formal/Submissions/UpperRiscv/Wire.lean#L79', html)
        self.assertNotIn('Per-instruction breakdown', html)
        self.assertEqual(sub.claim, 687)

    def test_identity_and_verdict_must_match(self):
        sub = self.real()
        for key, value in [('id', 'f' * 32), ('commit', 'f' * 40), ('claim', 702),
                           ('status', 'rejected'), ('track', 'upper-compressions'),
                           ('pr_url', 'https://github.com/other/repo/pull/11'),
                           ('detail', json.dumps({'contract': 'f' * 64})),
                           ('detail', json.dumps({**sub.detail_dict, 'demo': True}))]:
            with self.subTest(key=key, value=value):
                old = getattr(sub, key)
                setattr(sub, key, value)
                self.assertIsNone(riscv_compressions.for_submission(sub))
                setattr(sub, key, old)

    def test_unlisted_submission_does_not_get_a_bound_from_notes(self):
        sub = self.real()
        sub.id = 'a' * 32
        sub.detail = json.dumps({**sub.detail_dict, 'compressions': 1, 'notes': '≤ 1 compression'})
        self.session.commit()
        html = self.client.get(f'/submissions/{sub.id}').text
        self.assertNotIn('Hashing bound', html)


if __name__ == '__main__':
    unittest.main()
