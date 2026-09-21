"""The machine track has explicit admission and an independent cycle scale."""
from __future__ import annotations

import copy
import json
import re
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import contract
from app.config import settings
from app.db import Base, Submission, User, get_session
from app.main import app, queue_submission
import seed_demo


class RiscvTrackTests(unittest.TestCase):
    def setUp(self):
        phony_patcher = patch.object(settings, 'phony', True)
        phony_patcher.start()
        self.addCleanup(phony_patcher.stop)
        self.config = copy.deepcopy(contract.load())
        machine = copy.deepcopy(next(t for t in self.config['tracks'] if t['slug'] == 'upper-compressions'))
        machine.update(slug='upper-riscv', title='RISC-V upper bound',
                       cost_unit='cycles', submission_root='formal/Submissions/UpperRiscv',
                       focus='RISC-V cycles', tab_label='RISC-V cycles', cycles_per_compression=1)
        self.config['tracks'] = [t for t in self.config['tracks'] if t['slug'] != 'upper-riscv'] + [machine]
        self.config['upper_tracks'] = ['upper-compressions', 'upper-riscv']
        for framework in self.config['frameworks']:
            framework.pop('upper_track', None)
        self.config_patch = patch.object(contract, 'load', return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def points(html, identifier):
        return json.loads(re.search(rf'<script id="{identifier}" type="application/json">(.*?)</script>',
                                    html, re.S).group(1))

    def test_second_upper_track_has_separate_units_and_record_attribution(self):
        seed_demo.refresh(self.session)
        html = self.client.get('/').text
        compression = self.points(html, 'chart-points')
        machine = self.points(html, 'upper-riscv-chart-points')
        self.assertTrue(all(p['unit'].startswith('compression') for p in compression))
        self.assertFalse(any(p['claim'] == 702 for p in compression))
        self.assertEqual([(p['claim'], p['login'], p['unit']) for p in machine],
                         [(1140, 'satoshi-nakamoto', 'cycles'), (1120, 'hal-finney', 'cycles'),
                          (1100, 'satoshi-nakamoto', 'cycles'), (1080, 'vitalik-buterin', 'cycles'),
                          (1060, 'hal-finney', 'cycles'), (1040, 'hal-finney', 'cycles'),
                          (1030, 'satoshi-nakamoto', 'cycles'), (1010, 'vitalik-buterin', 'cycles'),
                          (1000, 'vitalik-buterin', 'cycles'), (990, 'hal-finney', 'cycles'),
                          (980, 'satoshi-nakamoto', 'cycles'), (970, 'hal-finney', 'cycles'),
                          (960, 'vitalik-buterin', 'cycles'), (950, 'hal-finney', 'cycles'),
                          (940, 'vitalik-buterin', 'cycles'), (930, 'vitalik-buterin', 'cycles'),
                          (702, 'satoshi-nakamoto', 'cycles')])
        self.assertIn('class="chart-btn" data-chart="upper-riscv"', html)
        self.assertIn('class="chart-panel machine-dashboard upper-riscv-dashboard" '
                      'data-chart="upper-riscv" hidden', html)
        self.assertIn('data-track="upper-riscv"', html)
        self.assertIn('id="upper-riscv-title"', html)
        self.assertNotIn('lower-bound frameworks.</p>', html)
        self.assertNotIn('Accepting verification cost', html)
        self.assertIn('id="upper-riscv-board-title"', html)
        self.assertIn('id="upper-compressions-title"', html)
        self.assertEqual(len(re.findall('class="framework-card ', html)), 1)
        charts = [ET.fromstring(svg) for svg in re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)]
        self.assertEqual([svg.get('data-unit') for svg in charts], ['compressions', 'cycles'])
        self.assertEqual(len(charts[0].findall("./g[@class='chart-reference']")), 1)
        reference = charts[1].find("./g[@data-reference='whole-word-cycle-lower']")
        self.assertIsNotNone(reference)
        self.assertIn('Whole-word lower (demo) · 90', ''.join(reference.itertext()))
        self.assertIn('not a universal lower bound', reference.find('./title').text)
        self.assertIsNotNone(charts[1].find("./g[@data-series='upper-riscv']"))
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        sub = self.session.get(Submission, machine[-1]['id'])
        detail = self.client.get(f'/submissions/{sub.id}').text
        self.assertIn('702 cycles', detail)
        self.assertIn('Upper bound · RISC-V cycles', detail)
        self.assertNotIn('must prove', detail)
        self.assertIn('<span class="tag">demo</span>', detail)
        self.assertNotIn('class="status s-verified"', detail)
        profile = self.client.get('/solvers/satoshi-nakamoto').text
        self.assertIn('Upper bound · RISC-V cycles</a>', profile)
        self.assertIn('cycles', profile)

    def test_cycle_lower_reference_follows_the_record_and_is_absent_without_one(self):
        self.assertNotIn('data-reference="whole-word-cycle-lower"', self.client.get('/').text)
        seed_demo.refresh(self.session)
        lower = self.session.scalar(select(Submission).where(
            Submission.track == 'lower-generality-1', Submission.claim == 90))
        lower.claim = 91
        self.session.commit()
        html = self.client.get('/').text
        svg = next(ET.fromstring(s) for s in re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)
                   if 'data-unit="cycles"' in s)
        ref = svg.find("./g[@data-reference='whole-word-cycle-lower']")
        self.assertIn('· 91', ''.join(ref.itertext()))
        self.assertEqual(ref.find('./a').get('href'), f'/submissions/{lower.id}')
        self.assertTrue(all(p['kind'] == 'upper' for p in self.points(html, 'upper-riscv-chart-points')))
        with patch.object(settings, 'phony', False):
            self.assertNotIn('data-reference="whole-word-cycle-lower"', self.client.get('/').text)

    def test_unlisted_machine_track_neither_opens_admission_nor_seeds_a_record(self):
        self.config['upper_tracks'] = ['upper-compressions']
        self.assertIsNone(contract.upper_riscv_track())
        self.assertEqual(seed_demo.refresh(self.session), 28)
        self.assertNotIn('upper-riscv', self.client.get('/').text)
        self.assertNotIn('id="upper-riscv"', self.client.get('/rules').text)
        with self.assertRaises(HTTPException) as caught:
            queue_submission(self.session, User(login='tester'), 'upper-riscv', 'local', 'a' * 40,
                             None, [], None, None, None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_machine_demo_migration_preserves_all_existing_entries(self):
        self.config['upper_tracks'] = ['upper-compressions']
        seed_demo.refresh(self.session)
        before = {s.id: (s.created_at, s.finished_at, s.record_at, s.commit, s.claim)
                  for s in self.session.scalars(select(Submission))}
        self.assertEqual(len(before), 28)
        self.config['upper_tracks'].append('upper-riscv')
        self.assertEqual(seed_demo.refresh(self.session), 18)
        self.assertEqual(seed_demo.refresh(self.session), 0)
        self.assertEqual(len(list(self.session.scalars(select(Submission)))), len(seed_demo.ROWS))
        for identifier, original in before.items():
            s = self.session.get(Submission, identifier)
            self.assertEqual((s.created_at, s.finished_at, s.record_at, s.commit, s.claim), original)
        rows = list(self.session.scalars(select(Submission).where(Submission.track == 'upper-riscv')))
        self.assertEqual(len(rows), 18)
        machine = min(rows, key=lambda r: r.claim)
        self.assertEqual(machine.claim, 702)
        self.assertTrue(machine.is_record)

    def test_rules_state_every_execution_bound_and_total_spec_refinement_without_scores(self):
        html = self.client.get('/rules').text
        section = re.search(r'<details id="upper-riscv">.*?</details>', html, re.S).group(0)
        for phrase in ('every execution, accepting or rejecting', 'Every execution must terminate',
                       'same oracle', 'raw signature bit string', 'max(1, ⌈n / 512⌉)',
                       'no additional instruction charge', 'RV64IM',
                       'strictly less than 1 MiB (1,048,576 bytes)',
                       'four bytes per instruction plus all embedded data'):
            self.assertIn(phrase, section)
        self.assertNotIn('702', html)
        self.assertNotRegex(html, r'<details\b[^>]*\bopen\b')
        self.assertIn('formal/Submissions/UpperRiscv/', html)
        self.assertIn('<code>upper-riscv</code>', html)

    def test_machine_admission_is_independent_of_lower_framework_links(self):
        self.assertTrue(all(set(contract.framework_tracks(f['slug'])) == {'lower'}
                            for f in self.config['frameworks']))
        self.assertEqual([t['slug'] for t in contract.upper_tracks()], ['upper-compressions', 'upper-riscv'])
        user = User(login='machine-solver')
        self.session.add(user)
        self.session.commit()
        sub = queue_submission(self.session, user, 'upper-riscv', 'local', 'a' * 40,
                               'Machine proof', [], None, None, None)
        self.assertEqual((sub.track, sub.status), ('upper-riscv', 'pending'))
        self.assertIn(f'href="/submissions/{sub.id}"', self.client.get('/').text)


if __name__ == '__main__':
    unittest.main()
