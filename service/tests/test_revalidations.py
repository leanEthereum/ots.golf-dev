"""Proof ports must survive fresh recovery without transferring an achievement's credit."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import contract, github, main, records, resync, revalidations, worker
from app.config import settings
from app.db import Base, Submission, get_session


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = revalidations.entries()
        self.assertEqual(len(self.catalog), 3)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (patch.object(settings, 'data_dir', Path(tmp.name)),
                  patch.object(settings, 'submissions_repo', 'leanEthereum/ots.golf-submissions'),
                  patch.object(settings, 'github_token', 'test-token'),
                  patch.object(settings, 'bot_login', 'ots-bot'),
                  patch('app.resync.SessionLocal', self.sessions),
                  patch('app.resync.github.read_file', return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def restore(self):
        pulls, comments = [], {}
        for i, entry in enumerate(self.catalog):
            for side in ('check', 'original'):  # Newer check intentionally arrives first.
                number = int(entry[side + '_pr_url'].rsplit('/', 1)[1])
                sid = entry[side + '_id']
                author = entry['original_author'] if side == 'original' else 'maintenance-author'
                finish = entry['original_finished_at'] if side == 'original' else f'2026-09-20T15:2{i}:00Z'
                value = dict(id=sid, track=entry['track'], commit=entry[side + '_commit'],
                             contract=entry[side + '_contract'], status='verified', claim=entry['claim'],
                             record=True, finished_at=finish, created_at='2026-09-19T00:00:00Z',
                             source_ref=f'refs/tags/ots-source/{sid}',
                             author={'login': author, 'id': (100 + i if side == 'original' else 999), 'avatar_url': None},
                             description='Original explanation', co_authors=['Original collaborator'],
                             assisted_by='Original assistant', contract_commit='c' * 40,
                             submission_root=entry['submission_root'])
                pulls.append(dict(number=number, state='closed', head={'sha': entry[side + '_commit']},
                                  body='', user={'login': 'edited-pr-author'}))
                comments[number] = [dict(id=number, user={'login': 'ots-bot'},
                                         updated_at=finish, body=github.verdict_block([value]))]
        with patch('app.resync.github.list_pulls', return_value=pulls), \
             patch('app.resync.github.list_comments', side_effect=lambda repo, number: comments[number]), \
             patch('app.worker.run_pipeline') as run:
            result = resync.resync(queue_open_heads=False)
        run.assert_not_called()
        self.assertNotIn('errors', result)
        return result

    def test_fresh_github_recovery_preserves_original_authors_dates_and_receipts(self):
        self.assertEqual(self.restore()['restored'], 6)
        with self.sessions() as session:
            for e in self.catalog:
                original = session.get(Submission, e['original_id'])
                check = session.get(Submission, e['check_id'])
                record = records.current_record(session, e['track'])
                self.assertEqual(record.id, original.id)
                self.assertEqual(record.user.login, e['original_author'])
                self.assertEqual(record.record_at, resync._time(e['original_finished_at']))
                self.assertEqual(record.detail_dict['contract'], e['original_contract'])
                self.assertEqual(record.co_authors_list, ['Original collaborator'])
                self.assertEqual(record.assisted_by, 'Original assistant')
                self.assertFalse(check.is_record)
                self.assertIsNone(check.record_at)
                self.assertFalse(worker.beats_record(session, check))
                self.assertEqual([x.id for x in records.frontier(session, e['track'])], [original.id])
                self.assertEqual(records.curve(session, e['track'])[0]['login'], e['original_author'])
        self.assertEqual(self.restore()['restored'], 0)

    def test_lower_revalidation_matches_exact_source_claim_pr_and_contract_only(self):
        e = next(x for x in self.catalog if x['track'] == 'lower-generality-1')
        sub = Submission(id=e['original_id'], commit=e['original_commit'], track=e['track'],
                         pr_url=e['original_pr_url'], claim=e['claim'], status='verified',
                         detail=json.dumps({'contract': e['original_contract']}))
        self.assertTrue(sub.current_contract)
        for key, value in dict(id='f' * 32, commit='f' * 40, claim=91, pr_url='https://github.com/else/repo/pull/1',
                               status='rejected').items():
            old = getattr(sub, key)
            setattr(sub, key, value)
            self.assertFalse(sub.current_contract, key)
            setattr(sub, key, old)
        with patch('app.contract.contract_id', return_value='f' * 64):
            self.assertFalse(sub.current_contract)
            check = Submission(id=e['check_id'], commit=e['check_commit'], track=e['track'],
                               pr_url=e['check_pr_url'], claim=e['claim'], status='verified',
                               detail=json.dumps({'contract': e['check_contract']}))
            self.assertTrue(revalidations.is_check(check))

    def test_new_improvement_is_still_a_new_record(self):
        self.restore()
        with self.sessions() as session:
            origin = records.current_record(session, 'upper-compressions')
            new = Submission(track=origin.track, user_id=origin.user_id, commit='f' * 40, claim=91,
                             status='verified', source_repo=origin.source_repo, pr_number=50,
                             pr_url='https://github.com/leanEthereum/ots.golf-submissions/pull/50',
                             detail=json.dumps({'contract': contract.contract_id()}))
            session.add(new)
            session.flush()
            worker.promote(session, new)
            session.flush()
            self.assertTrue(new.is_record)
            self.assertEqual(records.current_record(session, new.track).id, new.id)

    def test_check_link_returns_to_original_credit_and_links_adapted_source(self):
        self.restore()
        def session_override():
            with self.sessions() as s:
                yield s
        main.app.dependency_overrides[get_session] = session_override
        self.addCleanup(main.app.dependency_overrides.clear)
        client = TestClient(main.app)
        for e in self.catalog:
            response = client.get('/submissions/' + e['check_id'], follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['location'], '/submissions/' + e['original_id'] + '#revalidation')
            page = client.get('/submissions/' + e['original_id'])
            self.assertEqual(page.status_code, 200)
            self.assertIn(e['original_author'], page.text)
            self.assertIn(revalidations.proof_url(e), page.text)
            self.assertNotIn('excluded from the current leaderboard', page.text)
        page = client.get('/solvers/maintenance-author')
        for e in self.catalog:
            self.assertNotIn('/submissions/' + e['check_id'], page.text)

    def test_budget_change_is_not_a_retirement(self):
        from app import hall_of_fame
        retired = hall_of_fame.retirements()
        self.assertFalse(any(g['id'] == 'keygen-budget-2026-09-20' for g in retired))
        for e in self.catalog:
            self.assertFalse(hall_of_fame.contains(e['original_id']))
