"""Measured bytecode counts retain their identity from verdict to public display."""
import json
from types import SimpleNamespace
import unittest

from app import contract, github, worker
from app.db import Submission, User
from app.leanisa_program_size import validate, for_submission, historical_sizes
import test_leanisa_track
import test_rebuild


class SizeTests(unittest.TestCase):
    def test_historical_sizes_are_bound_to_source_and_contract(self):
        for sid, value in historical_sizes().items():
            sub = SimpleNamespace(id=sid, track='upper-leanisa', status='verified', commit=value['commit'],
                                  detail_dict={'contract': value['contract']})
            self.assertEqual(for_submission(sub).instructions, value['instructions'])
            sub.commit = '0' * 40
            self.assertIsNone(for_submission(sub))
            sub.commit = value['commit']
            sub.detail_dict['contract'] = '0' * 64
            self.assertIsNone(for_submission(sub))

    def test_validation_and_pinning(self):
        size = dict(version=1, commit='a' * 40, contract='b' * 64, instructions=512)
        sub = SimpleNamespace(track='upper-leanisa', status='verified', commit=size['commit'],
                              detail_dict={'contract': size['contract'], 'leanisa_program_size': size})
        self.assertEqual(for_submission(sub).instruction_label, '512')
        for key, bad in [('instructions', True), ('instructions', 0), ('instructions', 513),
                         ('instructions', 524288), ('commit', 'c' * 40), ('contract', 'c' * 64),
                         ('version', True)]:
            with self.subTest(key=key, bad=bad):
                self.assertIsNone(validate({**size, key: bad}, sub.commit, 'b' * 64))
        sub.status = 'rejected'
        self.assertIsNone(for_submission(sub))
        sub.status, sub.track = 'verified', 'upper-riscv'
        self.assertIsNone(for_submission(sub))

    def test_durable_verdict_roundtrip(self):
        size = dict(version=1, commit='a' * 40, contract='b' * 64, instructions=512)
        sub = Submission(id='a' * 32, track='upper-leanisa', status='verified', commit=size['commit'],
                         detail=json.dumps({'contract': size['contract'], 'leanisa_program_size': size}))
        entry = worker.verdict_entry(sub)
        self.assertEqual(github.parse_verdicts(github.verdict_block([entry]))[0]['leanisa_program_size'], size)
        sub.status = 'rejected'
        self.assertNotIn('leanisa_program_size', worker.verdict_entry(sub))


class SizePageTests(test_leanisa_track.LeanIsaTrackTests):
    def test_count_in_card_table_and_detail(self):
        from datetime import datetime
        user = User(login='preview')
        self.session.add(user)
        self.session.flush()
        size = dict(version=1, commit='a' * 40, contract=contract.contract_id(), instructions=512)
        sub = Submission(id='a' * 32, user_id=user.id, track='upper-leanisa', status='verified',
                         source_repo='local-preview', commit=size['commit'], claim=1800, is_record=True,
                         created_at=datetime(2026,9,23), finished_at=datetime(2026,9,23),
                         detail=json.dumps({'demo': True, 'contract': size['contract'], 'leanisa_program_size': size}))
        self.session.add(sub)
        self.session.commit()
        home = self.client.get('/?upper=upper-leanisa').text
        self.assertIn('512 <span>instructions</span>', home)
        self.assertIn(f'/submissions/{sub.id}#program-size', home)
        self.assertIn('>512</a>', home)
        detail = self.client.get(f'/submissions/{sub.id}').text
        self.assertIn('id="program-size">Instructions</dt>', detail)
        self.assertIn('>512</dd>', detail)
        self.assertNotIn('id="embedded-data"', detail)
        sub.detail = json.dumps({'demo': True, 'contract': size['contract']})
        self.session.commit()
        self.assertNotIn('id="program-size"', self.client.get(f'/submissions/{sub.id}').text)
        self.assertIn('title="Program size has not been measured">–', self.client.get('/').text)


class RecoveryTests(test_rebuild.RecoveryTests):
    def test_leanisa_size_recovered_from_github(self):
        size = dict(version=1, commit=self.commit, contract=contract.contract_id(), instructions=512)
        entry = self.entry(track='upper-leanisa', submission_root='formal/Submissions/UpperLeanIsa',
                           status='verified', claim=1800, record=True,
                           finished_at='2026-09-23T12:00:00Z', leanisa_program_size=size)
        self.restore([entry])
        with self.sessions() as session:
            sub = session.get(Submission, self.sid)
            self.assertEqual(sub.detail_dict['leanisa_program_size'], size)
            self.assertEqual(sub.program_size.instructions, 512)
