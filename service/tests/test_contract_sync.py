"""Contract deployment pins preserve concurrent records and cannot be rolled back by old hosts."""
import json
import unittest
from unittest.mock import patch, AsyncMock

import httpx

from app import contract_sync
from app.config import settings
from app.record_snapshot import SnapshotError
from test_record_snapshot import FakeGit, identity


class PinGit(FakeGit):
    target = "e" * 40
    status = "ahead"

    def handle(self, request):
        if request.url.path.startswith('/repos/owner/core/compare/'):
            self.requests.append(request)
            previous = request.url.path.rsplit('/', 1)[1].split('...')[0]
            return httpx.Response(200, json={"status": self.status,
                "base_commit": {"sha": previous}, "merge_base_commit": {"sha": previous}})
        if request.method == 'POST' and request.url.path.endswith('/git/trees'):
            self.requests.append(request)
            body = json.loads(request.content)
            self.test.assertEqual(body['tree'], [dict(path='.contract', mode='160000',
                                                     type='commit', sha=self.target)])
            return httpx.Response(201, json={'sha': self.replace(body['base_tree'], '.contract',
                dict(mode='160000', type='commit', sha=self.target))})
        return super().handle(request)


class ContractSyncTests(unittest.TestCase):
    def setUp(self):
        self.git = PinGit(self)
        self.initial = dict(self.git.trees[self.git.commits[self.git.head]])
        for key, value in dict(environment='production', role='web', phony=False,
                               github_token='test', submissions_repo='owner/entries',
                               contract_repo='owner/core').items():
            p = patch.object(settings, key, value)
            p.start()
            self.addCleanup(p.stop)
        real_client = httpx.Client
        p = patch.object(contract_sync.httpx, 'Client', side_effect=lambda **kw:
            real_client(transport=httpx.MockTransport(self.git.handle), **kw))
        p.start()
        self.addCleanup(p.stop)

    def sync(self):
        return contract_sync.sync_pin(self.git.target)

    def writes(self):
        return [r for r in self.git.requests if r.method != 'GET']

    def test_updates_only_pin_and_is_idempotent(self):
        self.assertEqual(self.sync()['reason'], 'updated')
        current = dict(self.git.trees[self.git.commits[self.git.head]])
        self.assertEqual(current.pop('.contract')['sha'], self.git.target)
        self.initial.pop('.contract')
        self.assertEqual(current, self.initial)
        self.git.requests.clear()
        self.assertEqual(self.sync()['reason'], 'already_current')
        self.assertFalse(self.writes())

    def test_preserves_concurrent_record_publication(self):
        self.git.before_patch = lambda: self.git.set_registry({'records': {'new': 'record'}})
        self.assertEqual(self.sync()['reason'], 'updated')
        self.assertEqual(self.git.registry(), {'records': {'new': 'record'}})
        self.assertEqual(self.git.at('.contract')['sha'], self.git.target)

    def test_refuses_to_roll_back_newer_pin(self):
        self.git.status = 'behind'
        self.assertEqual(self.sync()['reason'], 'newer_pin')
        self.assertFalse(self.writes())

    def test_rechecks_pin_when_newer_deployment_wins_race(self):
        def newer():
            self.git.set_registry({'new_deployment': True})
            tree = self.git.replace(self.git.commits[self.git.head], '.contract',
                                   dict(mode='160000', type='commit', sha='d' * 40))
            self.git.head = identity(['new deployment', tree])
            self.git.commits[self.git.head] = tree
            self.git.status = 'behind'
        self.git.before_patch = newer
        self.assertEqual(self.sync()['reason'], 'newer_pin')
        self.assertEqual(self.git.registry(), {'new_deployment': True})
        self.assertEqual(self.git.at('.contract')['sha'], 'd' * 40)

    def test_divergent_contract_rejected_before_writes(self):
        self.git.status = 'diverged'
        with self.assertRaises(SnapshotError):
            self.sync()
        self.assertFalse(self.writes())

    def test_missing_submodule_rejected(self):
        self.git.commits[self.git.head] = self.git.tree({'README.md': self.git.original_readme})
        with self.assertRaises(SnapshotError):
            self.sync()
        self.assertFalse(self.writes())

    def test_development_phony_worker_cannot_publish(self):
        for key, value in [('environment', 'development'), ('phony', True), ('role', 'worker')]:
            with self.subTest(key=key), patch.object(settings, key, value):
                self.assertFalse(contract_sync.enabled())
                with self.assertRaises(SnapshotError):
                    self.sync()
        self.assertFalse(self.git.requests)

    def test_lost_success_response_is_safe_to_retry(self):
        self.git.lose_patch_response = True
        with self.assertRaises(httpx.ReadTimeout):
            self.sync()
        self.git.requests.clear()
        self.assertEqual(self.sync()['reason'], 'already_current')
        self.assertFalse(self.writes())

    def test_transient_failure_can_retry(self):
        self.git.fail_commit = True
        with self.assertRaises(httpx.HTTPStatusError):
            self.sync()
        self.assertEqual(self.sync()['reason'], 'updated')


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_retries_same_deployed_commit(self):
        with patch.object(contract_sync.contract, 'trusted_commit', return_value='a' * 40), \
             patch.object(contract_sync, 'sync_pin', side_effect=[ValueError('offline'),
                 {'reason': 'updated'}]) as sync, \
             patch.object(contract_sync.asyncio, 'sleep', new_callable=AsyncMock) as sleep, \
             patch.object(contract_sync.log, 'exception'), patch('builtins.print'):
            await contract_sync.sync_on_start()
        self.assertEqual(sync.call_count, 2)
        self.assertEqual(sync.call_args.args, ('a' * 40,))
        sleep.assert_awaited_once_with(60)
