"""Record promotion, durable reporting, worker exclusivity and pipeline result checks."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main, records, worker
from app.config import settings
from app.db import Base, GithubReport, Submission, User, local_lock, schedule_report, utcnow


class ServiceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        (self.data / 'work').mkdir()
        (self.data / 'logs').mkdir()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.patches = [patch.object(settings, 'data_dir', self.data),
                        patch.object(settings, 'work_dir', self.data / 'work'),
                        patch.object(settings, 'contract_repo', 'owner/core'),
                        patch.object(settings, 'submissions_repo', 'owner/repo'),
                        patch.object(settings, 'github_token', ''),
                        patch('app.worker.SessionLocal', self.sessions), patch('app.main.SessionLocal', self.sessions),
                        patch('app.worker.github.merge_pr', return_value=(False, 'not in tests')),
                        patch.object(settings, 'auto_merge', False)]
        for p in self.patches:
            p.start()
        with self.sessions() as session:
            user = User(login='proof-author')
            session.add(user)
            session.commit()
            self.user_id = user.id

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def submission(self, *, claim=19, status='verified', record=False, pr=7):
        with self.sessions() as session:
            sub = Submission(user_id=self.user_id, track='lower-generality-2', claim=claim, status=status,
                             commit='a' * 40, source_repo='https://github.com/author/repo.git',
                             pr_number=pr, pr_url=f'https://github.com/owner/repo/pull/{pr}' if pr else None,
                             is_record=record,
                             record_at=utcnow() if record else None)
            session.add(sub)
            session.commit()
            return sub

    def merged_pr(self, *, sha='a' * 40, merged=True):
        return {'state': 'closed', 'merged': merged, 'merged_at': '2026-09-17T12:00:00Z',
                'base': {'ref': 'main', 'repo': {'default_branch': 'main'}}, 'head': {'sha': sha, 'repo': {'clone_url': 'https://github.com/author/repo.git'}}}

    def merge(self, sub):
        with patch('app.main.github.get_pr', return_value=self.merged_pr()):
            return main.handle_merged_pull_request('owner/repo', sub.pr_number, sub.commit)

    def test_verification_does_not_promote_until_exact_head_is_merged(self):
        sub = self.submission()
        with self.sessions() as session:
            worker.promote(session, session.get(Submission, sub.id))
            session.commit()
            self.assertIsNone(records.current_record(session, 'lower-generality-2'))
        self.assertTrue(self.merge(sub)['promoted'])
        with self.sessions() as session:
            self.assertEqual(records.current_record(session, 'lower-generality-2').id, sub.id)
            self.assertIsNotNone(session.get(GithubReport, sub.id))

    def test_unmerged_better_claim_does_not_suppress_merged_record(self):
        self.submission(claim=500, pr=8)
        sub = self.submission(claim=19)
        self.merge(sub)
        with self.sessions() as session:
            self.assertEqual(records.current_record(session, 'lower-generality-2').claim, 19)

    def test_demo_records_never_block_a_real_record(self):
        demo = self.submission(claim=500, pr=8, record=True)
        with self.sessions() as session:
            session.get(Submission, demo.id).detail = json.dumps({'demo': True})
            session.commit()
        sub = self.submission(claim=19)
        self.assertTrue(self.merge(sub)['promoted'])

    def test_same_pr_number_and_head_in_core_cannot_receive_submission_merge(self):
        old = self.submission()
        with self.sessions() as session:
            session.get(Submission, old.id).pr_url = 'https://github.com/owner/core/pull/7'
            session.commit()
        new = self.submission()
        self.assertTrue(self.merge(new)['promoted'])
        with self.sessions() as session:
            self.assertFalse(session.get(Submission, old.id).is_record)
            self.assertNotIn('merge', session.get(Submission, old.id).detail_dict)
            self.assertIsNone(session.get(GithubReport, old.id))
            self.assertEqual(records.current_record(session, 'lower-generality-2').id, new.id)

    def test_core_handlers_never_contact_github_for_proof_intake(self):
        with patch('app.main.github.get_pr') as get_pr:
            self.assertFalse(main.handle_pull_request('owner/core', 7, 'a' * 40)['queued'])
            self.assertFalse(main.handle_merged_pull_request('owner/core', 7, 'a' * 40)['promoted'])
            get_pr.assert_not_called()

    def test_submission_pr_queues_its_fork_head_against_the_core_verifier(self):
        pr = {'state': 'open', 'changed_files': 1, 'body': 'A proof.',
              'user': {'login': 'alice', 'id': 42},
              'base': {'ref': 'main', 'repo': {'default_branch': 'main'}}, 'head': {'sha': 'b' * 40, 'repo': {'clone_url': 'https://github.com/alice/entries.git'}}}
        with patch('app.main.github.get_pr', return_value=pr), \
             patch('app.main.github.pr_track', return_value=('lower-generality-3', [])):
            queued = main.handle_pull_request('owner/repo', 9, 'b' * 40)
        self.assertTrue(queued['queued'])
        with self.sessions() as session:
            sub = session.get(Submission, queued['id'])
            self.assertEqual(sub.pr_repository, 'owner/repo')
            self.assertEqual(sub.source_repo, 'https://github.com/alice/entries.git')
            self.assertEqual(sub.commit, 'b' * 40)
            result = {'status': 'verified', 'track': sub.track, 'commit': sub.commit, 'claim': 1}
            proc = Mock(returncode=0)
            proc.communicate.return_value = (json.dumps(result), '')
            with patch('app.worker.subprocess.Popen', return_value=proc) as launch:
                self.assertEqual(worker.run_pipeline(sub)[0]['status'], 'verified')
                command = launch.call_args.args[0]
                self.assertEqual(command[1], str(settings.repo_root / 'verifier/verify.py'))
                self.assertEqual(command[command.index('--source') + 1], sub.source_repo)
                self.assertEqual(command[command.index('--commit') + 1], sub.commit)
                self.assertEqual(launch.call_args.kwargs['cwd'], settings.repo_root)

    def test_pull_requests_not_targeting_the_default_branch_are_refused(self):
        pr = {'state': 'open', 'changed_files': 1, 'body': '', 'user': {'login': 'alice', 'id': 42},
              'base': {'ref': 'side', 'repo': {'default_branch': 'main'}},
              'head': {'sha': 'b' * 40, 'repo': {'clone_url': 'https://github.com/alice/entries.git'}}}
        with patch('app.main.github.get_pr', return_value=pr), \
             patch('app.main.github.pr_track', return_value=('lower-generality-3', [])), \
             patch('app.main.github.post_comment') as comment:
            self.assertFalse(main.handle_pull_request('owner/repo', 9, 'b' * 40)['queued'])
            comment.assert_called_once()
        sub = self.submission()
        merged = dict(self.merged_pr(), base={'ref': 'side', 'repo': {'default_branch': 'main'}})
        with patch('app.main.github.get_pr', return_value=merged):
            self.assertFalse(main.handle_merged_pull_request('owner/repo', sub.pr_number, sub.commit)['promoted'])
        from app import github
        self.assertFalse(github.targets_default_branch(merged))
        self.assertFalse(github.targets_default_branch({'base': {'ref': 'main', 'repo': {}}}))
        self.assertTrue(github.targets_default_branch(self.merged_pr()))

    def test_wrong_head_or_unmerged_close_never_promotes(self):
        sub = self.submission()
        for pr in [self.merged_pr(merged=False), self.merged_pr(sha='b' * 40)]:
            with patch('app.main.github.get_pr', return_value=pr):
                self.assertFalse(main.handle_merged_pull_request('owner/repo', 7, sub.commit)['promoted'])
        with self.sessions() as session:
            self.assertFalse(session.get(Submission, sub.id).is_record)
            self.assertNotIn('merge', session.get(Submission, sub.id).detail_dict)

    def test_merge_before_verification_is_retained_and_promoted_after_success(self):
        sub = self.submission(claim=None, status='pending')
        self.assertFalse(self.merge(sub)['promoted'])
        result = {'status': 'verified', 'claim': 19, 'commit': sub.commit, 'comparator_exit': 0}
        with patch('app.worker.run_pipeline', return_value=(result, None)):
            worker.process(sub.id)
        with self.sessions() as session:
            checked = session.get(Submission, sub.id)
            self.assertTrue(checked.is_record)
            self.assertEqual(checked.detail_dict['merge']['head'], sub.commit)
            self.assertIsNotNone(session.get(GithubReport, sub.id))

    def test_notes_from_the_verifier_are_stored_but_not_rendered(self):
        sub = self.submission(claim=None, status='pending')
        result = {'status': 'rejected', 'track': sub.track, 'commit': sub.commit, 'tail': 'bad proof',
                  'notes': '## Dead end\n\nThe averaging lemma loses a factor of two.'}
        with patch('app.worker.run_pipeline', return_value=(result, None)):
            worker.process(sub.id)
        with self.sessions() as session:
            self.assertEqual(session.get(Submission, sub.id).notes, result['notes'])
            main.app.dependency_overrides[main.get_session] = lambda: session
            try:
                with patch('app.main.prepare_board'), TestClient(main.app) as client:
                    page = client.get(f'/submissions/{sub.id}').text
            finally:
                main.app.dependency_overrides.clear()
        self.assertNotIn('The averaging lemma loses a factor of two.', page)   # agents read /notes.md

    def test_failed_merged_proof_cannot_become_record(self):
        sub = self.submission(claim=None, status='pending')
        self.merge(sub)
        with patch('app.worker.run_pipeline', return_value=({'status': 'rejected', 'tail': 'bad proof'}, None)):
            worker.process(sub.id)
        with self.sessions() as session:
            self.assertFalse(session.get(Submission, sub.id).is_record)
            self.assertIsNone(records.current_record(session, 'lower-generality-2'))

    def test_first_merged_submission_of_an_empty_track_becomes_the_record(self):
        from app import contract
        self.assertTrue(contract.improves('+', 0, None))
        self.assertTrue(contract.improves('-', 10 ** 6, None))
        with self.sessions() as session:
            self.assertIsNone(records.track_state(session, contract.track('lower-generality-2'))['record_claim'])
        sub = self.submission(claim=0)
        self.assertTrue(self.merge(sub)['promoted'])
        bad = self.submission(claim=None, record=True)
        with self.sessions() as session:
            self.assertEqual(records.current_record(session, 'lower-generality-2').id, sub.id)
            self.assertEqual(records.track_state(session, contract.track('lower-generality-2'))['record_claim'], 0)
            self.assertNotIn(bad.id, [s.id for s in records.frontier(session, 'lower-generality-2')])

    def test_local_job_never_becomes_a_record(self):
        sub = self.submission(claim=18, pr=None)
        with self.sessions() as session:
            checked = session.get(Submission, sub.id)
            worker.promote(session, checked)
            session.commit()
            self.assertFalse(checked.is_record)
            self.assertIsNone(records.current_record(session, 'lower-generality-2'))

    def test_result_reports_are_durable_and_retried_without_reverification(self):
        sub = self.submission()
        with self.sessions() as session:
            schedule_report(session, session.get(Submission, sub.id))
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.report', side_effect=RuntimeError('offline')):
            worker.deliver_report(sub.id)
        with self.sessions() as session:
            pending = session.get(GithubReport, sub.id)
            self.assertEqual(pending.attempts, 1)
            self.assertGreater(pending.next_attempt, utcnow())
            pending.next_attempt = utcnow() - timedelta(seconds=1)
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.report', return_value=123) as report:
            worker.retry_reports()
            report.assert_called_once()
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, sub.id))
            self.assertEqual(session.get(Submission, sub.id).detail_dict['github_comment_id'], 123)

    def test_merge_during_report_preserves_newer_pending_outbox_version(self):
        sub = self.submission()
        with self.sessions() as session:
            schedule_report(session, session.get(Submission, sub.id))
            session.commit()
        def report(_sub, _history=None):
            self.merge(sub)
            return 123
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.report', side_effect=report):
            worker.deliver_report(sub.id)
        with self.sessions() as session:
            self.assertIsNotNone(session.get(GithubReport, sub.id))
            checked = session.get(Submission, sub.id)
            self.assertTrue(checked.is_record)
            self.assertEqual(checked.detail_dict['github_comment_id'], 123)

    def test_existing_result_comment_is_updated_instead_of_duplicated(self):
        sub = self.submission()
        sub.detail = json.dumps({'github_comment_id': 123})
        with patch('app.worker.github.post_status') as status, patch('app.worker.github.update_comment') as update, \
             patch('app.worker.github.post_comment') as post:
            self.assertEqual(worker.report(sub), 123)
            status.assert_called_once()
            update.assert_called_once()
            self.assertEqual(status.call_args.args[0], 'owner/repo')
            self.assertEqual(update.call_args.args[:2], ('owner/repo', 123))
            post.assert_not_called()

    def test_pr_submission_ids_are_stable_and_failed_heads_requeue_under_the_same_id(self):
        pr = {'state': 'open', 'user': {'login': 'alice', 'id': 42},
              'base': {'ref': 'main', 'repo': {'default_branch': 'main'}}, 'head': {'sha': 'b' * 40, 'repo': {'clone_url': 'https://github.com/alice/entries.git'}}}
        with patch('app.main.github.get_pr', return_value=pr), \
             patch('app.main.github.pr_track', return_value=('lower-generality-3', [])):
            first = main.handle_pull_request('owner/repo', 9, 'b' * 40)
        from app.db import pr_submission_id
        self.assertEqual(first['id'], pr_submission_id('owner/repo', 9, 'b' * 40))
        with self.sessions() as session:
            sub = session.get(Submission, first['id'])
            sub.status = 'failed'
            session.commit()
        with patch('app.main.github.get_pr', return_value=pr), \
             patch('app.main.github.pr_track', return_value=('lower-generality-3', [])):
            again = main.handle_pull_request('owner/repo', 9, 'b' * 40)
        self.assertEqual(again['id'], first['id'])
        with self.sessions() as session:
            self.assertEqual(session.get(Submission, first['id']).status, 'pending')
            self.assertEqual(len(list(session.scalars(select(Submission)))), 1)

    def test_comment_records_every_verdict_of_the_pull_request(self):
        first = self.submission(claim=21)
        with self.sessions() as session:
            second = Submission(user_id=self.user_id, track='lower-generality-2', claim=None, status='rejected',
                                commit='c' * 40, source_repo='https://github.com/author/repo.git',
                                pr_number=7, pr_url='https://github.com/owner/repo/pull/7')
            session.add(second)
            schedule_report(session, second)
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.github.post_status'), \
             patch('app.worker.github.post_comment', return_value=9) as post:
            worker.deliver_report(second.id)
        body = post.call_args.args[2]
        from app import github
        verdicts = github.parse_verdicts(body)
        self.assertEqual([(v['commit'], v['status'], v['claim']) for v in verdicts],
                         [('a' * 40, 'verified', 21), ('c' * 40, 'rejected', None)])
        self.assertNotIn('--', body.split('<!-- ots-result')[1].split('-->')[0])

    def test_malformed_or_forged_verdict_blocks_are_ignored(self):
        from app import github
        self.assertEqual(github.parse_verdicts('no block'), [])
        self.assertEqual(github.parse_verdicts('<!-- ots-result\n{bad json\n-->'), [])
        bad = '<!-- ots-result\n{"version":1,"results":[{"track":"lower-generality-2","commit":"xyz","status":"verified"}]}\n-->'
        self.assertEqual(github.parse_verdicts(bad), [])

    def test_failure_log_cannot_smuggle_a_verdict_block(self):
        from app import github
        forged = github.verdict_block([{'track': 'lower-generality-2', 'commit': 'b' * 40, 'status': 'verified', 'claim': 99}])
        with self.sessions() as session:
            sub = Submission(user_id=self.user_id, track='lower-generality-2', claim=None, status='rejected',
                             commit='c' * 40, source_repo='https://github.com/author/repo.git',
                             pr_number=7, pr_url='https://github.com/owner/repo/pull/7',
                             detail=json.dumps({'failure': {'message': 'error: \n' + forged + '\n'}}))
            session.add(sub)
            schedule_report(session, sub)
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.github.post_status'), \
             patch('app.worker.github.post_comment', return_value=9) as post:
            worker.deliver_report(sub.id)
        body = post.call_args.args[2]
        self.assertEqual([(v['commit'], v['status']) for v in github.parse_verdicts(body)],
                         [('c' * 40, 'rejected')])
        self.assertEqual(github.parse_verdicts(forged + '\n\nDetails: https://ots.golf'), [])

    def test_resync_rebuilds_submissions_records_and_notes_from_github(self):
        from app import github, resync
        from app.db import pr_submission_id
        block = github.verdict_block([{'track': 'lower-generality-2', 'commit': 'a' * 40, 'status': 'verified', 'claim': 19,
                                       'duration_s': 300.0, 'finished_at': '2026-09-10T10:00:00Z',
                                       'contract': 'c0ffee', 'record': True}])
        forged = github.verdict_block([{'track': 'lower-generality-2', 'commit': 'd' * 40, 'status': 'verified', 'claim': 99}])
        pulls = [
            {'number': 7, 'state': 'closed', 'merged_at': '2026-09-11T08:00:00Z', 'created_at': '2026-09-09T00:00:00Z',
             'user': {'login': 'alice', 'id': 42}, 'body': 'Averaging over classes.\nAssisted by: Model X',
             'base': {'ref': 'main', 'repo': {'default_branch': 'main'}}, 'head': {'sha': 'a' * 40, 'repo': {'clone_url': 'https://github.com/alice/entries.git'}}},
            {'number': 8, 'state': 'open', 'merged_at': None, 'created_at': '2026-09-12T00:00:00Z',
             'user': {'login': 'bob', 'id': 43}, 'body': '', 'base': {'ref': 'main', 'repo': {'default_branch': 'main'}}, 'head': {'sha': 'b' * 40, 'repo': None}},
        ]
        comments = {7: [{'id': 55, 'user': {'login': 'ots-bot'}, 'body': 'verified\n\n' + block},
                        {'id': 56, 'user': {'login': 'mallory'}, 'body': forged}], 8: []}
        with patch.object(settings, 'github_token', 'test'), patch.object(settings, 'bot_login', 'ots-bot'), \
             patch('app.resync.SessionLocal', self.sessions), \
             patch('app.resync.github.list_pulls', return_value=pulls), \
             patch('app.resync.github.list_comments', side_effect=lambda repo, n: comments[n]), \
             patch('app.resync.github.read_file', return_value='## Idea\n\nAverage over classes.'), \
             patch('app.main.handle_pull_request') as queue:
            first = resync.resync()
            second = resync.resync()
        self.assertEqual(first, {'restored': 1, 'promoted': 1, 'queued': 1})
        self.assertEqual(second['restored'], 0)
        queue.assert_called_with('owner/repo', 8, 'b' * 40, announce=False)
        with self.sessions() as session:
            sub = session.get(Submission, pr_submission_id('owner/repo', 7, 'a' * 40))
            self.assertEqual((sub.claim, sub.status, sub.is_record, sub.user.login), (19, 'verified', True, 'alice'))
            self.assertEqual(sub.record_at.strftime('%Y-%m-%d %H:%M'), '2026-09-11 08:00')
            self.assertEqual(sub.assisted_by, 'Model X')
            self.assertEqual(sub.notes, '## Idea\n\nAverage over classes.')
            self.assertEqual(sub.detail_dict['github_comment_id'], 55)
            self.assertIsNone(session.scalars(select(Submission).where(Submission.commit == 'd' * 40)).first())

    def test_startup_reseeds_the_phony_board_only_in_phony_mode(self):
        with patch.object(settings, 'phony', True), patch('app.main.SessionLocal', self.sessions), \
             patch('seed_demo.reseed', return_value=(0, 3)) as reseed:
            main.prepare_board()
        reseed.assert_called_once()
        with patch.object(settings, 'phony', False), patch('app.main.SessionLocal', self.sessions), \
             patch('seed_demo.reseed') as reseed:
            main.prepare_board()
        reseed.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(Submission)).all(), [])

    def deliver(self, sub, merge_result):
        with self.sessions() as session:
            schedule_report(session, session.get(Submission, sub.id))
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.github.post_status'), \
             patch('app.worker.github.post_comment', return_value=11), \
             patch('app.worker.github.merge_pr', return_value=merge_result) as merge:
            if 'auto_merge_off' in self._testMethodName:
                worker.deliver_report(sub.id)
            else:
                with patch.object(settings, 'auto_merge', True):
                    worker.deliver_report(sub.id)
        return merge

    def test_verified_record_is_merged_automatically_and_promoted(self):
        sub = self.submission(claim=19)
        merge = self.deliver(sub, (True, ''))
        merge.assert_called_once()
        self.assertEqual(merge.call_args.args[:3], ('owner/repo', 7, 'a' * 40))
        with self.sessions() as session:
            stored = session.get(Submission, sub.id)
            self.assertTrue(stored.is_record)
            self.assertTrue(stored.detail_dict['merge']['automatic'])
            self.assertIsNotNone(session.get(GithubReport, sub.id))   # the comment is updated to "new record"

    def test_non_record_is_never_merged(self):
        self.submission(claim=25, record=True, pr=5)
        sub = self.submission(claim=19)
        merge = self.deliver(sub, (True, ''))
        merge.assert_not_called()
        with self.sessions() as session:
            self.assertFalse(session.get(Submission, sub.id).is_record)

    def test_refused_merge_is_explained_on_the_pull_request(self):
        sub = self.submission(claim=19)
        self.deliver(sub, (False, 'Pull Request is not mergeable'))
        with self.sessions() as session:
            stored = session.get(Submission, sub.id)
            self.assertFalse(stored.is_record)
            self.assertEqual(stored.detail_dict['merge_blocked'], 'Pull Request is not mergeable')
        with patch('app.worker.github.post_status'), patch('app.worker.github.update_comment') as update:
            worker.report(stored)
        self.assertIn('GitHub refused the automatic merge', update.call_args.args[2])

    def test_auto_merge_off_never_merges(self):
        sub = self.submission(claim=19)
        merge = self.deliver(sub, (True, ''))
        merge.assert_not_called()

    def test_reports_never_retarget_an_old_core_pr(self):
        sub = self.submission()
        sub.pr_url = 'https://github.com/owner/core/pull/7'
        with patch('app.worker.github.post_status') as status, patch('app.worker.github.post_comment') as post:
            with self.assertRaises(ValueError):
                worker.report(sub)
            status.assert_not_called()
            post.assert_not_called()

    def test_old_repository_outbox_does_not_block_current_reports(self):
        for n in range(25):
            sub = self.submission(pr=n + 100)
            with self.sessions() as session:
                old = session.get(Submission, sub.id)
                old.pr_url = f'https://github.com/owner/core/pull/{old.pr_number}'
                schedule_report(session, old)
                session.commit()
        current = self.submission()
        with self.sessions() as session:
            schedule_report(session, session.get(Submission, current.id))
            session.commit()
        with patch.object(settings, 'github_token', 'test'), patch('app.worker.report', return_value=456) as report:
            worker.deliver_report(sub.id)
            report.assert_not_called()
            worker.retry_reports()
            report.assert_called_once()
            self.assertEqual(report.call_args.args[0].id, current.id)
        with self.sessions() as session:
            self.assertIsNotNone(session.get(GithubReport, sub.id))
            self.assertIsNone(session.get(GithubReport, current.id))

    def test_pr_identity_requires_a_matching_github_pull_request_url(self):
        sub = self.submission()
        for url in ('https://example.com/owner/repo/pull/7', 'https://github.com/owner/repo/pull/8',
                    'https://github.com/owner/repo/pull/7/extra', None):
            sub.pr_url = url
            self.assertIsNone(sub.pr_repository)

    def test_deleted_result_comment_is_recreated(self):
        sub = self.submission()
        sub.detail = json.dumps({'github_comment_id': 123})
        response = httpx.Response(404, request=httpx.Request('PATCH', 'https://api.github.com/comment'))
        error = httpx.HTTPStatusError('deleted', request=response.request, response=response)
        with patch('app.worker.github.post_status'), patch('app.worker.github.update_comment', side_effect=error), \
             patch('app.worker.github.post_comment', return_value=456) as post:
            self.assertEqual(worker.report(sub), 456)
            post.assert_called_once()

    def test_production_worker_refuses_web_role_even_if_settings_loaded(self):
        with patch.object(settings, 'environment', 'production'), patch.object(settings, 'role', 'web'), \
             patch('app.worker.init_db') as initialize:
            with self.assertRaises(SystemExit):
                worker.main()
            initialize.assert_not_called()

    def test_worker_lock_excludes_another_worker_and_is_released(self):
        with local_lock('worker', blocking=False):
            with self.assertRaises(BlockingIOError):
                with local_lock('worker', blocking=False):
                    self.fail('second worker acquired the active lock')
        with local_lock('worker', blocking=False):
            pass

    def pipeline(self, sub, result, *, returncode=0):
        proc = Mock(returncode=returncode)
        proc.communicate.return_value = (json.dumps(result), '')
        with patch('app.worker.subprocess.Popen', return_value=proc) as launch:
            result, log_path = worker.run_pipeline(sub)
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            self.assertTrue(Path(log_path).is_file())
            return result

    def test_pipeline_rejects_forged_or_inconsistent_success_metadata(self):
        sub = self.submission()
        valid = {'status': 'verified', 'track': 'lower-generality-2', 'claim': 19, 'commit': sub.commit}
        self.assertEqual(self.pipeline(sub, valid)['status'], 'verified')
        for changes in ({'track': 'no-such-track'}, {'claim': True}, {'claim': -1}, {'claim': 1000001},
                        {'commit': 'b' * 40}, {'claim': None}):
            self.assertEqual(self.pipeline(sub, valid | changes)['status'], 'failed')
        self.assertEqual(self.pipeline(sub, valid, returncode=1)['status'], 'failed')
        self.assertEqual(self.pipeline(sub, [])['status'], 'failed')

    def test_pipeline_outer_timeout_stops_group_and_preserves_log(self):
        sub = self.submission()
        proc = Mock(pid=12345, returncode=-15)
        proc.communicate.side_effect = [subprocess.TimeoutExpired('verify', 1), ('partial output', '')]
        with patch('app.worker.subprocess.Popen', return_value=proc), patch('app.worker.os.killpg') as kill:
            result, log_path = worker.run_pipeline(sub)
        kill.assert_called_once_with(12345, worker.signal.SIGTERM)
        self.assertEqual(result['status'], 'timeout')
        self.assertIn('partial output', Path(log_path).read_text())
        self.assertIn('outer time limit', Path(log_path).read_text())

    def test_pipeline_termination_escalates_if_graceful_shutdown_stalls(self):
        proc = Mock(pid=12345)
        proc.communicate.side_effect = [subprocess.TimeoutExpired('verify', 40), ('stopped', '')]
        with patch('app.worker.os.killpg') as kill:
            self.assertEqual(worker._stop_pipeline(proc), ('stopped', ''))
        self.assertEqual([call.args for call in kill.call_args_list],
                         [(12345, worker.signal.SIGTERM), (12345, worker.signal.SIGKILL)])

    def test_github_http_failure_is_not_silently_treated_as_reported(self):
        response = httpx.Response(503, request=httpx.Request('POST', 'https://api.github.com/test'), text='unavailable')
        with self.assertRaises(httpx.HTTPStatusError):
            worker.github._check(response, 'test status')


if __name__ == '__main__':
    unittest.main()
