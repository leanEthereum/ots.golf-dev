"""The leanISA track is admitted from the contract, and carries its own cycle price."""
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


class LeanIsaTrackTests(unittest.TestCase):
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
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def charts(html):
        return [ET.fromstring(svg) for svg in
                re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)]

    def test_registering_the_track_opens_it_for_submission(self):
        """`upper_tracks()` is derived from the contract. A hard-coded list would leave the
        track registered everywhere except the one place that admits submissions."""
        self.assertEqual([t['slug'] for t in contract.upper_tracks()],
                         ['upper-compressions', 'upper-riscv', 'upper-leanisa'])
        self.assertIsNotNone(contract.upper_leanisa_track())
        user = User(login='leanisa-solver')
        self.session.add(user)
        self.session.commit()
        sub = queue_submission(self.session, user, 'upper-leanisa', 'local', 'a' * 40,
                               None, [], None, None, None)
        self.assertEqual((sub.track, sub.status, sub.user_id),
                         ('upper-leanisa', 'pending', user.id))

    def test_unlisted_track_neither_opens_admission_nor_appears(self):
        self.config['upper_tracks'] = [t for t in self.config['upper_tracks']
                                       if t != 'upper-leanisa']
        self.assertIsNone(contract.upper_leanisa_track())
        self.assertNotIn('upper-leanisa', self.client.get('/').text)
        self.assertNotIn('id="upper-leanisa"', self.client.get('/rules').text)
        user = User(login='leanisa-solver')
        self.session.add(user)
        self.session.commit()
        with self.assertRaises(HTTPException) as caught:
            queue_submission(self.session, user, 'upper-leanisa', 'local', 'a' * 40,
                             None, [], None, None, None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_home_carries_a_third_board_a_third_chart_and_the_fixed_input_cost(self):
        html = self.client.get('/').text
        for marker in ('upper-leanisa-card', 'data-upper="upper-leanisa"',
                       'data-chart="upper-leanisa"', 'id="upper-leanisa-chart-points"',
                       'By leanISA cycles'):
            self.assertIn(marker, html)
        # The 120 cycles every leanISA claim spends re-deriving the public input are stated
        # wherever the score is, so the two cycle tracks are not compared naively.
        note = re.search(r'<p class="upper-card-note muted">(.*?)</p>', html, re.S)
        self.assertIsNotNone(note)
        self.assertIn('120 cycles', note.group(1))
        self.assertIn('public input', note.group(1))
        self.assertEqual([svg.get('data-unit') for svg in self.charts(html)],
                         ['compressions', 'cycles', 'cycles'])
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_leanisa_carries_no_whole_word_reference_line(self):
        """The whole-word lower bound says nothing about leanISA. `BLAKE2S` fixes every oracle
        query at 896 bits, while a whole-word DAG hash node queries the length of its parent's
        value, so no leanISA submission's scheme is in the whole-word class. RISC-V's `HASH`
        takes any length, so its chart keeps the line."""
        seed_demo.refresh(self.session)
        self.assertIsNotNone(self.session.scalar(select(Submission).where(
            Submission.track == 'lower-generality-1', Submission.claim == 90)))
        html = self.client.get('/').text
        points = json.loads(re.search(
            r'<script id="upper-leanisa-chart-points" type="application/json">(.*?)</script>',
            html, re.S).group(1))
        self.assertTrue(all(p['kind'] == 'upper' for p in points))
        leanisa = next(ET.fromstring(s) for s in
                       re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)
                       if 'id="upper-leanisa-record-chart-title"' in s)
        self.assertIsNone(leanisa.find("./g[@data-reference='whole-word-cycle-lower']"))
        riscv = next(ET.fromstring(s) for s in
                     re.findall(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S)
                     if 'id="upper-riscv-record-chart-title"' in s)
        self.assertIsNotNone(riscv.find("./g[@data-reference='whole-word-cycle-lower']"))

    def test_rules_state_both_obligations_and_the_surcharge_without_scores(self):
        html = self.client.get('/rules').text
        section = re.search(r'<details id="upper-leanisa">.*?</details>', html, re.S).group(0)
        for phrase in ('committed by an untrusted prover', 'does not exist',
                       'Faithful', 'Sound', 'every completing execution',
                       'no cost on rejection', '120 cycles', '262,144 instructions',
                       '896 bits', 'not RFC 7693 BLAKE2s'):
            self.assertIn(phrase, section)
        self.assertIn('formal/Submissions/UpperLeanIsa/', html)
        self.assertIn('<code>upper-leanisa</code>', html)
        self.assertNotRegex(html, r'<details\b[^>]*\bopen\b')

    def test_every_admitted_upper_track_names_itself_distinctly(self):
        """Two upper tracks whose `focus` agreed would render identical links and identical
        board titles. The RISC-V test fixture copies the compressions entry, so this is a real
        way to get it wrong."""
        focuses = [contract.upper_focus(t) for t in contract.upper_tracks()]
        self.assertTrue(all(focuses))
        self.assertEqual(len(focuses), len(set(focuses)))
        for t in contract.upper_tracks():
            self.assertIn('tab_label', t)


if __name__ == '__main__':
    unittest.main()
