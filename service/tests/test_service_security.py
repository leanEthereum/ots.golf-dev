"""Service boundaries: signed webhooks, queue admission, and untrusted presentation."""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import github, main
from app.config import Settings, settings
from app.db import Base, Submission, User, get_session


class ServiceSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(settings, 'data_dir', Path(self.temp.name))
        self.patch.start()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        main.app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()
        self.patch.stop()
        self.temp.cleanup()

    def event(self):
        return {'action': 'opened', 'repository': {'full_name': 'owner/repo'},
                'pull_request': {'number': 7, 'head': {'sha': 'a' * 40}}}

    def send_event(self, event, *, repo='owner/repo', signature=True):
        body = json.dumps(event).encode()
        digest = hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
        headers = {'x-github-event': 'pull_request', 'x-hub-signature-256': 'sha256=' + digest}
        if not signature:
            headers['x-hub-signature-256'] = 'sha256=' + '0' * 64
        with patch.object(settings, 'github_webhook_secret', 'test-secret'), patch.object(settings, 'submissions_repo', repo):
            return self.client.post('/webhooks/github', content=body, headers=headers)

    def test_webhook_rejects_bad_signatures_before_any_github_call(self):
        with patch('app.main.handle_pull_request') as handle:
            self.assertEqual(self.send_event(self.event(), signature=False).status_code, 401)
            handle.assert_not_called()

    def test_webhook_rejects_malformed_signed_events(self):
        events = [[], None, {'action': 'opened'}]
        for field, value in [('number', True), ('number', '7'), ('number', -1), ('sha', 'a' * 7),
                             ('sha', 'a' * 40 + '\n'), ('full_name', 42), ('full_name', '../repo')]:
            event = self.event()
            if field == 'full_name':
                event['repository'][field] = value
            elif field == 'sha':
                event['pull_request']['head'][field] = value
            else:
                event['pull_request'][field] = value
            events.append(event)
        with patch('app.main.handle_pull_request') as handle:
            for event in events:
                self.assertEqual(self.send_event(event).status_code, 400, event)
            handle.assert_not_called()

    def test_webhook_is_closed_without_repository_configuration(self):
        with patch('app.main.handle_pull_request') as handle:
            self.assertEqual(self.send_event(self.event(), repo='').status_code, 503)
            self.assertTrue(self.send_event(self.event(), repo='other/repo').json()['ignored'])
            handle.assert_not_called()

    def test_only_authenticated_expected_repository_is_dispatched(self):
        with patch('app.main.handle_pull_request', return_value={'queued': True}) as handle:
            response = self.send_event(self.event())
            self.assertEqual(response.status_code, 200)
            handle.assert_called_once_with('owner/repo', 7, 'a' * 40)

    def test_core_repository_webhooks_do_not_queue_proofs(self):
        with patch.object(settings, 'contract_repo', 'owner/core'), patch('app.main.handle_pull_request') as queue:
            event = self.event()
            event['repository']['full_name'] = 'owner/core'
            response = self.send_event(event)
            self.assertTrue(response.json()['ignored'])
            self.assertEqual(response.json()['reason'], 'not the submissions repository')
            queue.assert_not_called()

    def test_closed_pull_requests_are_ignored(self):
        """Merging or closing a pull request never decides a record."""
        event = self.event()
        event['action'] = 'closed'
        with patch('app.main.handle_pull_request') as queue:
            response = self.send_event(event)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['ignored'])
            queue.assert_not_called()
        self.assertFalse(hasattr(main, 'handle_merged_pull_request'))

    def test_webhook_body_and_content_length_limits(self):
        for value, code in [('not-an-integer', 400), ('-1', 400), (str(main.MAX_WEBHOOK_BYTES + 1), 413)]:
            self.assertEqual(self.client.post('/webhooks/github', content=b'{}',
                             headers={'content-length': value}).status_code, code)
        self.assertEqual(self.client.post('/webhooks/github', content=b'x' * (main.MAX_WEBHOOK_BYTES + 1)).status_code, 413)

    def test_rename_source_outside_root_is_rejected(self):
        with patch('app.github.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.get.return_value
            response.json.return_value = [{'filename': 'formal/Submissions/LowerGenerality2/Solution.lean',
                                           'previous_filename': 'formal/OptimalOTS/Dag.lean'}]
            slug, outside = github.pr_track('owner/repo', 7, expected_files=1)
            self.assertEqual(slug, 'lower-generality-2')
            self.assertEqual(outside, ['formal/OptimalOTS/Dag.lean'])

    def test_truncated_or_oversized_pull_request_file_list_is_rejected(self):
        with patch('app.github.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.get.return_value
            response.json.return_value = [{'filename': 'formal/Submissions/LowerGenerality2/Solution.lean'}]
            self.assertIsNone(github.pr_track('owner/repo', 7, expected_files=2)[0])
            client.reset_mock()
            self.assertIsNone(github.pr_track('owner/repo', 7, expected_files=3001)[0])
            client.assert_not_called()

    def test_untrusted_markdown_cannot_run_scripts_or_link_to_javascript(self):
        html = main.safe_markdown('<script>alert(1)</script><img src=x onerror=alert(1)>'
                                  '[bad](javascript:alert(1)) <a href="https://example.test" onclick="x()">safe</a>')
        for forbidden in ('<script', '<img', 'javascript:', 'onclick', 'onerror'):
            self.assertNotIn(forbidden, html)
        self.assertIn('https://example.test', html)
        self.assertIn('noopener', html)

    def test_browser_errors_are_readable_and_api_errors_remain_json(self):
        browser = self.client.get('/missing', headers={'accept': 'text/html'})
        self.assertEqual(browser.status_code, 404)
        self.assertIn('This page could not be found.', browser.text)
        self.assertIn("script-src 'self'", browser.headers['content-security-policy'])
        self.assertEqual(browser.headers['x-content-type-options'], 'nosniff')
        api = self.client.get('/missing')
        self.assertEqual(api.status_code, 404)
        self.assertEqual(api.json(), {'detail': 'Not Found'})
        with patch('app.main.records.overview', side_effect=RuntimeError('private diagnostic')):
            failure = self.client.get('/', headers={'accept': 'text/html'})
        self.assertEqual(failure.status_code, 500)
        self.assertIn('temporarily unavailable', failure.text)
        self.assertNotIn('private diagnostic', failure.text)
        self.assertEqual(self.client.get('/healthz').json(), {'status': 'ok'})

    def test_commit_queue_requires_exact_sha_and_rejects_duplicates(self):
        user = User(login='alice')
        self.session.add(user)
        self.session.commit()
        for sha in ['a' * 7, 'a' * 39, 'a' * 41, 'x' * 40]:
            with self.assertRaises(HTTPException):
                main.queue_submission(self.session, user, 'lower-generality-2', 'local', sha, None, [], None, None, None)
        main.queue_submission(self.session, user, 'lower-generality-2', 'local', 'a' * 40, None, [], None, None, None)
        with self.assertRaises(HTTPException) as caught:
            main.queue_submission(self.session, user, 'lower-generality-2', 'local', 'a' * 40, None, [], None, None, None)
        self.assertEqual(caught.exception.status_code, 409)

    def test_production_requires_distinct_secret_free_worker_configuration(self):
        kwargs = {'environment': 'production', 'base_url': 'https://ots.example', 'contract_repo': 'owner/core',
                  'submissions_repo': 'owner/repo',
                  'data_dir': Path(self.temp.name), 'github_token': '', 'github_webhook_secret': ''}
        with self.assertRaises(ValueError):
            Settings(**kwargs, role='web')
        Settings(**kwargs, role='worker')
        with self.assertRaises(ValueError):
            Settings(**(kwargs | {'github_token': 'token'}), role='worker')
        Settings(**(kwargs | {'github_token': 'token', 'github_webhook_secret': 's' * 32}), role='web')
        for override in ({'base_url': 'http://ots.example'}, {'queue_cap': 0}, {'contract_repo': '../repo'},
                         {'submissions_repo': '../repo'}, {'submissions_repo': ''}, {'contract_repo': ''},
                         {'submissions_repo': 'OWNER/CORE'}):
            with self.assertRaises(ValueError):
                Settings(**(kwargs | override), role='worker')

    def test_production_website_rejects_worker_role_before_database_startup(self):
        with patch.object(settings, 'environment', 'production'), patch.object(settings, 'role', 'worker'), \
             patch('app.main.init_db') as initialize:
            with self.assertRaises(RuntimeError):
                with TestClient(main.app):
                    pass
            initialize.assert_not_called()

    def test_simultaneous_admission_cannot_bypass_per_user_limit(self):
        engine = create_engine(f'sqlite:///{self.temp.name}/concurrent.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)
        with sessions() as session:
            user = User(login='concurrent')
            session.add(user)
            session.commit()
            user_id = user.id
        def submit(n):
            with sessions() as session:
                user = session.get(User, user_id)
                try:
                    main.queue_submission(session, user, 'lower-generality-2', 'local', f'{n:040x}', None, [], None, None, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        with patch.object(settings, 'max_inflight_per_user', 1), ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(submit, [1, 2])), [200, 429])
        with sessions() as session:
            self.assertEqual(len(list(session.scalars(select(Submission)))), 1)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
