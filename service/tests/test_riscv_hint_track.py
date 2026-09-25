"""The hinted RISC-V track is admitted from the contract and shares the RISC-V image metadata."""
from __future__ import annotations

import copy
import re
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import contract, riscv_program_size
from app.config import settings
from app.db import Base, Submission, User, get_session
from app.main import app, queue_submission


class RiscvHintTrackTests(unittest.TestCase):
    def setUp(self):
        phony_patcher = patch.object(settings, 'phony', True)
        phony_patcher.start()
        self.addCleanup(phony_patcher.stop)
        self.config = copy.deepcopy(contract.load())
        self.config_patch = patch.object(contract, 'load', return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool)
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
    def charts(html):
        return [ET.fromstring(svg) for svg in
                re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)]

    def test_registering_the_track_opens_it_for_submission(self):
        self.assertEqual([t['slug'] for t in contract.upper_tracks()],
                         ['upper-compressions', 'upper-riscv', 'upper-leanisa', 'upper-riscv-hint'])
        self.assertIsNotNone(contract.upper_riscv_hint_track())
        user = User(login='hint-solver')
        self.session.add(user)
        self.session.commit()
        sub = queue_submission(self.session, user, 'upper-riscv-hint', 'local', 'a' * 40,
                               None, [], None, None, None)
        self.assertEqual((sub.track, sub.status, sub.user_id),
                         ('upper-riscv-hint', 'pending', user.id))

    def test_unlisted_track_neither_opens_admission_nor_appears(self):
        self.config['upper_tracks'] = [t for t in self.config['upper_tracks']
                                       if t != 'upper-riscv-hint']
        self.assertIsNone(contract.upper_riscv_hint_track())
        self.assertNotIn('upper-riscv-hint', self.client.get('/').text)
        self.assertNotIn('id="upper-riscv-hint"', self.client.get('/rules').text)
        user = User(login='hint-solver')
        self.session.add(user)
        self.session.commit()
        with self.assertRaises(HTTPException) as caught:
            queue_submission(self.session, user, 'upper-riscv-hint', 'local', 'a' * 40,
                             None, [], None, None, None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_home_carries_a_fourth_board_with_the_riscv_reference_line(self):
        """The hinted machine is the RISC-V machine, so the whole-word lower bound reads in its
        cycles too: hints cannot replace compressions (`Sound` forces every query the decision
        depends on), and `HASH` still takes an input of any length."""
        html = self.client.get('/').text
        for marker in ('upper-riscv-hint-card', 'data-upper="upper-riscv-hint"',
                       'data-chart="upper-riscv-hint"', 'id="upper-riscv-hint-chart-points"',
                       'By hinted RISC-V cycles'):
            self.assertIn(marker, html)
        self.assertEqual([svg.get('data-unit') for svg in self.charts(html)],
                         ['compressions', 'cycles', 'cycles', 'cycles'])
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('cycles_per_compression', contract.upper_riscv_hint_track())

    def test_rules_state_both_obligations_and_the_accepting_bound_without_scores(self):
        html = self.client.get('/rules').text
        section = re.search(r'<details id="upper-riscv-hint">.*?</details>', html, re.S).group(0)
        for phrase in ('prover-chosen view', 'Faithful', 'Sound', 'projected signature',
                       'every accepting execution', 'not charged', '1,048,576 bits',
                       'strictly less than 1 MiB (1,048,576 bytes)',
                       'must query the oracle for every answer', 'not a forgery'):
            self.assertIn(phrase, section)
        self.assertIn('formal/Submissions/UpperRiscvHint/', html)
        self.assertIn('<code>upper-riscv-hint</code>', html)
        self.assertNotRegex(html, r'<details\b[^>]*\bopen\b')

    def test_image_metadata_serves_both_riscv_tracks(self):
        """Both tracks fix a `Riscv.Image`; the collector's result is displayed for either."""
        self.assertEqual(riscv_program_size.IMAGE_TRACKS, {'upper-riscv', 'upper-riscv-hint'})
        user = User(login='hint-solver')
        self.session.add(user)
        self.session.commit()
        sub = queue_submission(self.session, user, 'upper-riscv-hint', 'local', 'b' * 40,
                               None, [], None, None, None)
        sub.status = 'verified'
        sub.claim = 300
        sub.detail = '{"contract": "%s", "riscv_program_size": {"version": 1, "commit": "%s", "contract": "%s", "instructions": 1200, "data_bytes": 64}}' % (
            contract.contract_id(), 'b' * 40, contract.contract_id())
        self.session.commit()
        size = self.session.get(Submission, sub.id).program_size
        self.assertEqual((size.instructions, size.data_bytes), (1200, 64))
        page = self.client.get(f'/submissions/{sub.id}').text
        self.assertIn('id="embedded-data"', page)
        self.assertIn('64 B', page)
        # The pre-rule image audit is RISC-V history only.
        self.assertFalse(riscv_program_size.compatible_image_limit(sub))


if __name__ == '__main__':
    unittest.main()
