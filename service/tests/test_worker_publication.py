"""Regressions for durable admission, result publication and recovery barriers."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import contract, github, records, resync, worker
from app.config import settings
from app.db import Base, GithubReport, Submission, User, local_lock, schedule_report, utcnow


class WorkerPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ots-publication-test-')
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        for setting, value in [('data_dir', Path(self.temp.name)), ('submissions_repo', 'owner/repo'),
                               ('github_token', 'fixture-token')]:
            patcher = patch.object(settings, setting, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in (worker, resync):
            patcher = patch.object(module, 'SessionLocal', self.sessions)
            patcher.start()
            self.addCleanup(patcher.stop)
        snapshot = patch.object(worker.record_snapshot, 'publish_record',
                                return_value={'commit': 'e' * 40, 'published': True, 'reason': 'published'})
        self.publish_snapshot = snapshot.start()
        self.addCleanup(snapshot.stop)
        with self.sessions() as session:
            user = User(login='alice')
            session.add(user)
            session.commit()
            self.user_id = user.id

    def submission(self, key='a', status='admitting', publication_status=None):
        sid = key * 32
        receipt = dict(source_ref=f'refs/tags/ots-source/{sid}', created_at='2026-09-19T01:02:03.000004Z',
                       author={'login': 'alice', 'id': 42}, description='Frozen description', co_authors=['bob'],
                       git_authors=[{'name': 'Alice', 'email': 'alice@example.org'},
                                    {'name': 'Bob', 'email': 'bob@example.org'}],
                       assisted_by='A model', contract_commit='f' * 40,
                       submission_root='formal/Submissions/LowerGenerality2')
        detail = dict(contract=contract.contract_id(), source_ref=receipt['source_ref'], receipt=receipt)
        if publication_status:
            detail['publication_status'] = publication_status
        with self.sessions() as session:
            sub = Submission(id=sid, user_id=self.user_id, track='lower-generality-2', status=status,
                             claim=19 if publication_status == 'verified' else None, commit=key * 40,
                             source_repo='https://github.com/owner/repo.git', pr_number=7,
                             pr_url='https://github.com/owner/repo/pull/7', detail=json.dumps(detail),
                             finished_at=utcnow() if publication_status else None)
            session.add(sub)
            schedule_report(session, sub)
            session.commit()
            return sub

    def load(self, sid):
        with self.sessions() as session:
            return session.get(Submission, sid)

    def due(self, sid):
        with self.sessions() as session:
            session.get(GithubReport, sid).next_attempt = utcnow() - timedelta(seconds=1)
            session.commit()

    def finish(self, sub, claim=19, status='verified'):
        with patch.object(worker, 'run_pipeline', return_value=({'status': status, 'claim': claim,
                                                                'commit': sub.commit}, None)) as run:
            worker.process(sub.id)
        return run

    def test_failed_receipt_cannot_enter_the_verification_queue(self):
        sub = self.submission()
        with patch.object(worker, 'report', side_effect=RuntimeError('offline')):
            worker.deliver_report(sub.id)
        self.assertEqual(self.load(sub.id).status, 'admitting')
        self.finish(sub).assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.get(GithubReport, sub.id).attempts, 1)

    def test_git_attribution_is_in_the_durable_verdict_block(self):
        sub = self.submission()
        restored = github.parse_verdicts(github.verdict_block([worker.verdict_entry(sub)]))[0]
        self.assertEqual(restored['git_authors'], sub.detail_dict['receipt']['git_authors'])

    def test_receipt_precedes_pending_status_and_releases_admission(self):
        sub = self.submission()
        events = []
        def comment(*args):
            self.assertEqual(self.load(sub.id).status, 'admitting')
            events.append('comment')
            return 41
        def status(*args):
            self.assertEqual(events, ['comment'])
            events.append('status')
        with patch.object(worker.github, 'post_comment', side_effect=comment), \
                patch.object(worker.github, 'post_status', side_effect=status), \
                patch.object(worker.github, 'verdict_block', return_value='receipt') as block:
            worker.deliver_report(sub.id)
        entry, = block.call_args.args[0]
        self.assertEqual(entry['status'], 'pending')
        for key, value in sub.detail_dict['receipt'].items():
            self.assertEqual(entry[key], value)
        current = self.load(sub.id)
        self.assertEqual(current.status, 'pending')
        self.assertEqual(current.detail_dict['github_comment_id'], 41)
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, sub.id))

    def test_record_snapshot_follows_durable_verdict_and_precedes_commit_status(self):
        sub = self.submission(status='publishing', publication_status='verified')
        events = []
        def snapshot(checked):
            self.assertEqual(events, ['comment'])
            self.assertEqual(checked.status, 'verified')
            self.assertTrue(checked.is_record)
            events.append('snapshot')
            return {'commit': 'e' * 40, 'published': True, 'reason': 'published'}
        self.publish_snapshot.side_effect = snapshot
        with patch.object(worker.github, 'post_comment', side_effect=lambda *_: events.append('comment') or 41), \
                patch.object(worker.github, 'post_status', side_effect=lambda *_: events.append('status')):
            worker.deliver_report(sub.id)
        self.assertEqual(events, ['comment', 'snapshot', 'status'])
        self.assertEqual(self.load(sub.id).detail_dict['record_snapshot']['commit'], 'e' * 40)

    def test_snapshot_failure_retries_automatically_without_rechecking_proof(self):
        sub = self.submission(status='publishing', publication_status='verified')
        self.publish_snapshot.side_effect = RuntimeError('main temporarily unavailable')
        with patch.object(worker.github, 'post_comment', return_value=41), \
                patch.object(worker.github, 'post_status') as status:
            worker.deliver_report(sub.id)
        status.assert_not_called()
        self.assertEqual(self.load(sub.id).status, 'verified')
        self.assertNotIn('record_snapshot', self.load(sub.id).detail_dict)
        with self.sessions() as session:
            self.assertEqual(session.get(GithubReport, sub.id).attempts, 1)
        self.due(sub.id)
        self.publish_snapshot.side_effect = None
        with patch.object(worker.github, 'update_comment'), patch.object(worker.github, 'post_status'), \
                patch.object(worker, 'run_pipeline') as verify:
            worker.deliver_report(sub.id)
        verify.assert_not_called()
        self.assertEqual(self.load(sub.id).detail_dict['record_snapshot']['commit'], 'e' * 40)
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, sub.id))

    def test_delayed_historical_report_cannot_publish_before_unsnapshotted_new_frontier(self):
        older = self.submission(status='verified')
        newer = self.submission('b', status='verified')
        with self.sessions() as session:
            for sub, claim in ((older, 19), (newer, 20)):
                current = session.get(Submission, sub.id)
                current.claim, current.is_record = claim, True
                current.finished_at = utcnow()
            session.commit()
        self.assertNotIn('record_snapshot', self.load(newer.id).detail_dict)
        with patch.object(worker.github, 'post_comment', return_value=41) as comment, \
                patch.object(worker.github, 'post_status') as status:
            worker.deliver_report(older.id)
        self.publish_snapshot.assert_not_called()
        status.assert_called_once()
        entry, = github.parse_verdicts(comment.call_args.args[2])
        self.assertTrue(entry['record'])  # the old improvement remains part of the public history
        self.assertTrue(self.load(older.id).is_record)
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, older.id))
            self.assertIsNotNone(session.get(GithubReport, newer.id))
        with patch.object(worker.github, 'post_comment', return_value=42), \
                patch.object(worker.github, 'post_status'):
            worker.deliver_report(newer.id)
        self.publish_snapshot.assert_called_once()
        self.assertEqual(self.publish_snapshot.call_args.args[0].id, newer.id)

    def test_detached_new_improvement_is_eligible_while_results_lock_is_held(self):
        older = self.submission(status='verified')
        with self.sessions() as session:
            current = session.get(Submission, older.id)
            current.claim, current.is_record, current.finished_at = 18, True, utcnow()
            session.commit()
        newer = self.submission('b', status='publishing', publication_status='verified')
        def publish(checked):
            self.assertEqual(checked.id, newer.id)
            self.assertEqual(self.load(newer.id).status, 'publishing')
            self.assertEqual(checked.status, 'verified')
            self.assertTrue(checked.is_record)
            with self.assertRaises(BlockingIOError):
                with local_lock('results', blocking=False):
                    self.fail('publication must hold the results lock')
            return {'commit': 'e' * 40, 'published': True, 'reason': 'published'}
        self.publish_snapshot.side_effect = publish
        with patch.object(worker.github, 'post_comment', return_value=42), \
                patch.object(worker.github, 'post_status'):
            worker.deliver_report(newer.id)
        self.publish_snapshot.assert_called_once()
        self.assertTrue(self.load(newer.id).is_record)
        self.assertEqual(self.load(newer.id).status, 'verified')

    def test_nonrecord_never_updates_main(self):
        sub = self.submission(status='verified')
        with patch.object(worker.github, 'post_comment', return_value=41), patch.object(worker.github, 'post_status'):
            worker.deliver_report(sub.id)
        self.publish_snapshot.assert_not_called()

    def test_source_link_is_exact_and_does_not_require_a_local_zip(self):
        sub = self.submission()
        self.assertEqual(sub.source_url, 'https://github.com/owner/repo/tree/' + sub.commit +
                         '/formal/Submissions/LowerGenerality2')
        self.assertIsNone(sub.archive_url)
        detail = sub.detail_dict
        detail['receipt']['submission_root'] = '../../other'
        sub.detail = json.dumps(detail)
        self.assertIsNone(sub.source_url)

    def test_completed_proof_waits_for_publication_and_blocks_the_next_job(self):
        first = self.submission(status='pending')
        second = self.submission('b', status='pending')
        self.finish(first).assert_called_once()
        current = self.load(first.id)
        self.assertEqual((current.status, current.detail_dict['publication_status']), ('publishing', 'verified'))
        self.assertFalse(current.is_record)
        self.finish(second).assert_not_called()
        with self.sessions() as session:
            self.assertIsNone(records.current_record(session, first.track))

    def test_failed_terminal_comment_never_promotes_or_posts_success(self):
        sub = self.submission(status='publishing', publication_status='verified')
        with patch.object(worker.github, 'post_comment', side_effect=RuntimeError('offline')), \
                patch.object(worker.github, 'post_status') as status:
            worker.deliver_report(sub.id)
        status.assert_not_called()
        current = self.load(sub.id)
        self.assertEqual(current.status, 'publishing')
        self.assertFalse(current.is_record)
        with self.sessions() as session:
            self.assertIsNone(records.current_record(session, sub.track))

    def test_durable_comment_releases_result_even_when_commit_status_needs_retry(self):
        sub = self.submission(status='publishing', publication_status='verified')
        with patch.object(worker.github, 'post_comment', return_value=41), \
                patch.object(worker.github, 'post_status', side_effect=RuntimeError('status offline')):
            worker.deliver_report(sub.id)
        current = self.load(sub.id)
        self.assertEqual(current.status, 'verified')
        self.assertTrue(current.is_record)
        self.assertEqual(current.record_at, current.finished_at)
        self.assertEqual(current.detail_dict['github_comment_id'], 41)
        with self.sessions() as session:
            self.assertEqual(session.get(GithubReport, sub.id).attempts, 1)
        self.due(sub.id)
        with patch.object(worker.github, 'update_comment') as update, \
                patch.object(worker.github, 'post_comment') as post, \
                patch.object(worker.github, 'post_status'), patch.object(worker, 'run_pipeline') as run:
            worker.deliver_report(sub.id)
        update.assert_called_once()
        post.assert_not_called()
        run.assert_not_called()
        with self.sessions() as session:
            self.assertIsNone(session.get(GithubReport, sub.id))

    def test_finish_order_and_equal_claim_record_survive_publication_delay(self):
        first = self.submission(status='pending')
        second = self.submission('b', status='pending')
        self.finish(first)
        self.finish(second).assert_not_called()
        with patch.object(worker, 'report', return_value=41):
            worker.deliver_report(first.id)
        self.finish(second).assert_called_once()
        with patch.object(worker, 'report', return_value=42) as report:
            worker.deliver_report(second.id)
        self.assertFalse(report.call_args.args[0].is_record)
        self.assertTrue(self.load(first.id).is_record)
        self.assertFalse(self.load(second.id).is_record)
        self.assertLess(self.load(first.id).finished_at, self.load(second.id).finished_at)

    def test_newer_outbox_version_is_not_released_by_an_older_receipt(self):
        sub = self.submission()
        def changed_while_reporting(_sub, **_kwargs):
            with self.sessions() as session:
                schedule_report(session, session.get(Submission, sub.id))
                session.commit()
            return 41
        with patch.object(worker, 'report', side_effect=changed_while_reporting):
            worker.deliver_report(sub.id)
        current = self.load(sub.id)
        self.assertEqual(current.status, 'admitting')
        self.assertEqual(current.detail_dict['github_comment_id'], 41)
        with self.sessions() as session:
            self.assertEqual(session.get(GithubReport, sub.id).version, 2)

    def test_new_head_comments_never_copy_older_head_metadata(self):
        sub = self.submission()
        history = [dict(id='older', status='verified', commit='c' * 40)]
        with patch.object(worker.github, 'post_comment', return_value=41), \
                patch.object(worker.github, 'post_status'), \
                patch.object(worker.github, 'verdict_block', return_value='receipt') as block:
            worker.report(sub, history)
        entries = block.call_args.args[0]
        self.assertEqual([entry['id'] for entry in entries], [sub.id])

    def test_legacy_history_cannot_publish_a_retained_heads_tentative_result(self):
        sub = self.submission(status='verified')
        sub.detail = json.dumps({'contract': contract.contract_id(), 'github_comment_id': 41})
        legacy = worker.verdict_entry(sub)
        tentative = dict(legacy, id='other-head', source_ref='refs/tags/ots-source/' + 'b' * 32)
        with patch.object(worker.github, 'update_comment'), patch.object(worker.github, 'post_status'), \
                patch.object(worker.github, 'verdict_block', return_value='legacy') as block:
            worker.report(sub, [legacy, tentative])
        self.assertEqual(block.call_args.args[0], [legacy])

    def test_missing_comment_identity_does_not_release_a_barrier(self):
        sub = self.submission()
        with patch.object(worker.github, 'post_comment', return_value=None), \
                patch.object(worker.github, 'post_status') as status:
            worker.deliver_report(sub.id)
        self.assertEqual(self.load(sub.id).status, 'admitting')
        status.assert_not_called()


    def test_status_retry_while_running_keeps_a_recoverable_pending_receipt(self):
        sub = self.submission(status='verifying')
        with patch.object(worker.github, 'post_comment', return_value=41) as post, \
                patch.object(worker.github, 'post_status'):
            worker.deliver_report(sub.id)
        body = post.call_args.args[2]
        self.assertIn('verification in progress', body)
        entry, = github.parse_verdicts(body)
        self.assertEqual(entry['status'], 'pending')
        restored = resync.latest_verdicts([{'id': 41, 'user': {'login': 'bot'}, 'body': body}], 'bot')
        self.assertEqual(restored[0][0]['id'], sub.id)
        self.assertEqual(self.load(sub.id).status, 'verifying')

    def test_incomplete_recovery_blocks_new_work_and_publication_until_retry_succeeds(self):
        sub = self.submission(status='pending')
        failure = {'errors': ['PR comment history unavailable']}
        with patch.object(resync, '_resync', return_value=failure):
            self.assertEqual(resync.resync(False), failure)
        marker = settings.data_dir / 'recovery.incomplete'
        self.assertTrue(marker.exists())
        self.finish(sub).assert_not_called()
        with patch.object(worker, 'report') as report:
            worker.deliver_report(sub.id)
        report.assert_not_called()
        with patch.object(resync, '_resync', return_value={'restored': 1}):
            resync.resync(False)
        self.assertFalse(marker.exists())
        with patch.object(worker, 'report', return_value=41) as report:
            worker.deliver_report(sub.id)
        report.assert_called_once()

    def test_recovery_holds_exclusive_lock_and_interruption_keeps_barrier(self):
        def interrupted(**_kwargs):
            self.assertTrue((settings.data_dir / 'recovery.incomplete').exists())
            with self.assertRaises(BlockingIOError):
                with local_lock('recovery', blocking=False, shared=True):
                    self.fail('recovery did not exclude a worker or reporter')
            raise KeyboardInterrupt
        with patch.object(resync, '_resync', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                resync.resync(False)
        self.assertTrue((settings.data_dir / 'recovery.incomplete').exists())
        with local_lock('recovery', blocking=False):
            pass  # the persistent marker, not an abandoned OS lock, blocks restart

    def test_shared_worker_and_reporter_locks_coexist_but_exclude_recovery(self):
        with local_lock('recovery', shared=True):
            with local_lock('recovery', shared=True, blocking=False):
                with self.assertRaises(BlockingIOError):
                    with local_lock('recovery', blocking=False):
                        self.fail('resync entered while a reader was active')
        with local_lock('recovery', blocking=False):
            pass

    def test_optional_cache_warning_does_not_block_successful_metadata_recovery(self):
        marker = settings.data_dir / 'recovery.incomplete'
        marker.touch()
        result = {'restored': 1, 'warnings': ['source archive unavailable']}
        with patch.object(resync, '_resync', return_value=result):
            self.assertEqual(resync.resync(False), result)
        self.assertFalse(marker.exists())

    def test_running_proof_retains_result_when_recovery_fails_before_it_finishes(self):
        sub = self.submission(status='pending')
        def finish_during_failed_recovery(_sub):
            (settings.data_dir / 'recovery.incomplete').touch()
            return {'status': 'verified', 'claim': 19, 'commit': sub.commit}, None
        with patch.object(worker, 'run_pipeline', side_effect=finish_during_failed_recovery):
            worker.process(sub.id)
        current = self.load(sub.id)
        self.assertEqual(current.status, 'publishing')
        self.assertEqual(current.detail_dict['publication_status'], 'verified')
        self.assertFalse(current.is_record)
        with patch.object(worker, 'report') as report:
            worker.deliver_report(sub.id)
        report.assert_not_called()

if __name__ == '__main__':
    unittest.main()
