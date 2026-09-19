"""Mock Git Data tests: exact roots, idempotency, stale jobs and concurrent main updates."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json
import unittest
from unittest.mock import patch

import httpx

from app import contract, record_snapshot
from app.config import settings
from app.db import Submission


def identity(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()


class FakeGit:
    def __init__(self, test):
        self.test, self.requests, self.trees, self.blobs, self.commits = test, [], {}, {}, {}
        self.source = 'a' * 40
        self.ref = 'refs/tags/ots-source/' + '1' * 32
        self.root = 'formal/Submissions/LowerGenerality2'
        self.source_tree = self.tree({'Solution.lean': self.blob(b'proof\n'), 'claim.txt': self.blob(b'19\n')})
        source_root = self.replace(self.tree({}), self.root, self.directory(self.source_tree))
        # Deliberately include unrelated and unsafe source-head files: none may be copied.
        source_root = self.replace(source_root, 'outside.txt', self.blob(b'unrelated source'))
        self.commits[self.source] = source_root
        self.head = 'b' * 40
        self.original_readme = self.blob(b'current main readme')
        self.commits[self.head] = self.tree({'README.md': self.original_readme,
            '.contract': {'mode': '160000', 'type': 'commit', 'sha': 'f' * 40}})
        self.before_patch = None
        self.fail_commit = False
        self.lose_patch_response = False

    def directory(self, sha):
        return {'mode': '040000', 'type': 'tree', 'sha': sha}

    def blob(self, raw):
        sha = identity(['blob', list(raw)])
        self.blobs[sha] = raw
        return {'mode': '100644', 'type': 'blob', 'sha': sha, 'size': len(raw)}

    def tree(self, entries):
        sha = identity(entries)
        self.trees[sha] = entries
        return sha

    def replace(self, root, path, item):
        parts = path.split('/')
        entries = dict(self.trees[root])
        if len(parts) == 1:
            entries[path] = item
        else:
            old = entries.get(parts[0]) or self.directory(self.tree({}))
            entries[parts[0]] = self.directory(self.replace(old['sha'], '/'.join(parts[1:]), item))
        return self.tree(entries)

    def at(self, path):
        tree = self.commits[self.head]
        for part in path.split('/'):
            item = self.trees[tree][part]
            tree = item['sha']
        return item

    def registry(self):
        return json.loads(self.blobs[self.at('records.json')['sha']])

    def set_registry(self, value):
        tree = self.replace(self.commits[self.head], 'records.json', self.blob(json.dumps(value).encode()))
        self.head = identity(['main', tree])
        self.commits[self.head] = tree

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix('/repos/owner/entries')
        body = json.loads(request.content) if request.content else None
        def response(data, status=200):
            return httpx.Response(status, json=data)
        if request.method == 'GET':
            if path == '/git/ref/' + self.ref.removeprefix('refs/'):
                return response({'ref': self.ref, 'object': {'type': 'commit', 'sha': self.source}})
            if path == '':
                return response({'default_branch': 'main'})
            if path == '/git/ref/heads/main':
                return response({'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': self.head}})
            if path.startswith('/git/commits/'):
                sha = path.rsplit('/', 1)[1]
                return response({'sha': sha, 'tree': {'sha': self.commits[sha]}})
            if path.startswith('/git/trees/'):
                self.test.assertFalse(request.url.query)  # no recursive whole-repository fetch
                sha = path.rsplit('/', 1)[1]
                return response({'sha': sha, 'truncated': False,
                                 'tree': [dict(value, path=name) for name, value in self.trees[sha].items()]})
            if path.startswith('/git/blobs/'):
                sha = path.rsplit('/', 1)[1]
                raw = self.blobs[sha]
                return response({'sha': sha, 'encoding': 'base64', 'size': len(raw),
                                 'content': base64.b64encode(raw).decode()})
        if request.method == 'POST' and path == '/git/trees':
            self.test.assertEqual({item['path'] for item in body['tree']}, {self.root, 'records.json'})
            tree = body['base_tree']
            for item in body['tree']:
                value = (self.blob(item['content'].encode()) if 'content' in item else
                         {key: item[key] for key in ('mode', 'type', 'sha')})
                tree = self.replace(tree, item['path'], value)
            return response({'sha': tree}, 201)
        if request.method == 'POST' and path == '/git/commits':
            self.test.assertEqual(len(body['parents']), 1)  # never merge a candidate commit
            if self.fail_commit:
                self.fail_commit = False
                return response({'message': 'temporary failure'}, 503)
            sha = identity(body)
            self.commits[sha] = body['tree']
            return response({'sha': sha}, 201)
        if request.method == 'PATCH' and path == '/git/refs/heads/main':
            self.test.assertIs(body['force'], False)
            if self.before_patch:
                callback, self.before_patch = self.before_patch, None
                callback()
                return response({'message': 'not fast forward'}, 422)
            self.head = body['sha']
            if self.lose_patch_response:
                self.lose_patch_response = False
                raise httpx.ReadTimeout('response lost', request=request)
            return response({'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': self.head}})
        self.test.fail(f'unexpected API request: {request.method} {path}')


class RecordSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.git = FakeGit(self)
        for key, value in [('submissions_repo', 'owner/entries'), ('github_token', 'fixture-token')]:
            change = patch.object(settings, key, value)
            change.start()
            self.addCleanup(change.stop)
        real_client = httpx.Client
        change = patch.object(record_snapshot.httpx, 'Client', side_effect=lambda **kwargs:
                              real_client(transport=httpx.MockTransport(self.git.handle), **kwargs))
        change.start()
        self.addCleanup(change.stop)
        self.sub = self.submission()

    def submission(self):
        epoch = contract.contract_id()
        meta = dict(version=1, sha256='d' * 64, size_bytes=1000, file_count=2, total_bytes=9,
                    source_repo='https://github.com/owner/entries.git', commit=self.git.source,
                    track='lower-generality-2', submission_root=self.git.root, contract=epoch)
        detail = dict(contract=epoch, source_ref=self.git.ref, source_archive=meta,
                      receipt={'submission_root': self.git.root, 'contract_commit': 'e' * 40})
        return Submission(id='1' * 32, track='lower-generality-2', status='verified', is_record=True,
                          claim=19, commit=self.git.source, source_repo='https://github.com/owner/entries.git',
                          pr_number=7, pr_url='https://github.com/owner/entries/pull/7',
                          finished_at=datetime(2026, 9, 19, 12), detail=json.dumps(detail))

    def writes(self):
        return [r for r in self.git.requests if r.method != 'GET']

    def old_entry(self, **changes):
        entry = record_snapshot._entry(self.sub, 'owner/entries')
        entry['source_tree'] = self.git.source_tree
        entry.update(changes)
        return entry

    def test_copies_only_checked_root_and_registry_and_preserves_main(self):
        initial = self.git.head
        result = record_snapshot.publish_record(self.sub)
        self.assertTrue(result['published'])
        self.assertEqual(self.git.at(self.git.root)['sha'], self.git.source_tree)
        self.assertEqual(self.git.at('README.md'), self.git.original_readme)
        self.assertEqual(self.git.at('.contract')['sha'], 'f' * 40)
        self.assertNotIn('outside.txt', self.git.trees[self.git.commits[self.git.head]])
        entry = self.git.registry()['records'][self.sub.track]
        self.assertEqual(entry, self.old_entry())
        commit = next(json.loads(r.content) for r in self.writes() if r.url.path.endswith('/git/commits'))
        self.assertEqual(commit['parents'], [initial])
        self.assertIn(self.sub.commit, commit['message'])
        self.assertIn(self.sub.pr_url, commit['message'])
        self.assertIn('e' * 40, commit['message'])

    def test_retry_is_idempotent_after_success(self):
        first = record_snapshot.publish_record(self.sub)
        self.git.requests.clear()
        second = record_snapshot.publish_record(self.sub)
        self.assertEqual(second, {'commit': first['commit'], 'published': False, 'reason': 'already_current'})
        self.assertEqual(self.writes(), [])

    def test_partial_failure_leaves_main_unchanged_and_can_retry(self):
        initial = self.git.head
        self.git.fail_commit = True
        with self.assertRaises(httpx.HTTPStatusError):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.git.head, initial)
        self.assertFalse(any(r.method == 'PATCH' for r in self.git.requests))
        self.assertTrue(record_snapshot.publish_record(self.sub)['published'])

    def test_lost_success_response_is_reconciled_without_duplicate_commit(self):
        self.git.lose_patch_response = True
        result = record_snapshot.publish_record(self.sub)
        self.assertEqual(result['reason'], 'already_current')
        self.assertEqual(sum(r.method == 'PATCH' for r in self.git.requests), 1)

    def test_concurrent_main_change_is_preserved_when_retrying(self):
        replacement = self.git.blob(b'maintainer changed README while publishing')
        def advance():
            tree = self.git.replace(self.git.commits[self.git.head], 'README.md', replacement)
            self.git.head = identity(['concurrent', tree])
            self.git.commits[self.git.head] = tree
        self.git.before_patch = advance
        self.assertTrue(record_snapshot.publish_record(self.sub)['published'])
        self.assertEqual(self.git.at('README.md'), replacement)
        self.assertEqual(sum(r.method == 'PATCH' for r in self.git.requests), 2)

    def test_concurrently_published_newer_record_prevents_retry_rollback(self):
        newer = self.old_entry(id='2' * 32, source_ref='refs/tags/ots-source/' + '2' * 32,
                               claim=20, finished_at='2026-09-19T13:00:00Z')
        self.git.before_patch = lambda: self.git.set_registry({'version': 1, 'records': {self.sub.track: newer}})
        result = record_snapshot.publish_record(self.sub)
        self.assertEqual(result['reason'], 'superseded')
        self.assertEqual(self.git.registry()['records'][self.sub.track]['id'], '2' * 32)
        self.assertEqual(sum(r.method == 'PATCH' for r in self.git.requests), 1)

    def test_later_equal_claim_and_older_claim_never_replace_the_existing_record(self):
        for old_claim, old_time in [(19, '2026-09-19T11:00:00Z'), (20, '2026-09-19T13:00:00Z')]:
            with self.subTest(claim=old_claim):
                old = self.old_entry(id='2' * 32, source_ref='refs/tags/ots-source/' + '2' * 32,
                                     claim=old_claim, finished_at=old_time)
                self.git.set_registry({'version': 1, 'records': {self.sub.track: old}})
                self.git.requests.clear()
                self.assertEqual(record_snapshot.publish_record(self.sub)['reason'], 'superseded')
                self.assertEqual(self.writes(), [])

    def test_new_track_preserves_other_registry_entries(self):
        other = self.old_entry(track='lower-generality-3', id='3' * 32,
                               source_ref='refs/tags/ots-source/' + '3' * 32,
                               submission_root='formal/Submissions/LowerGenerality3')
        other['source_archive'] = dict(other['source_archive'], track=other['track'], submission_root=other['submission_root'])
        self.git.set_registry({'version': 1, 'records': {other['track']: other}})
        record_snapshot.publish_record(self.sub)
        self.assertEqual(self.git.registry()['records'][other['track']], other)
        self.assertIn(self.sub.track, self.git.registry()['records'])

    def test_same_registry_identity_repairs_a_changed_root(self):
        record_snapshot.publish_record(self.sub)
        altered = self.git.tree({'Solution.lean': self.git.blob(b'changed by maintainer')})
        tree = self.git.replace(self.git.commits[self.git.head], self.git.root, self.git.directory(altered))
        self.git.head = identity(['altered', tree])
        self.git.commits[self.git.head] = tree
        self.assertTrue(record_snapshot.publish_record(self.sub)['published'])
        self.assertEqual(self.git.at(self.git.root)['sha'], self.git.source_tree)

    def test_unverified_or_unpinned_inputs_fail_before_network(self):
        for changes in [{'status': 'publishing'}, {'is_record': False}, {'claim': True}]:
            with self.subTest(changes=changes):
                sub = self.submission()
                for key, value in changes.items():
                    setattr(sub, key, value)
                self.git.requests.clear()
                with self.assertRaises(record_snapshot.SnapshotError):
                    record_snapshot.publish_record(sub)
                self.assertEqual(self.git.requests, [])
        self.sub.detail = json.dumps(self.sub.detail_dict | {'source_ref': 'refs/heads/main'})
        with self.assertRaises(record_snapshot.SnapshotError):
            record_snapshot.publish_record(self.sub)

    def test_checked_root_cannot_escape_its_configured_track(self):
        detail = self.sub.detail_dict
        detail['receipt']['submission_root'] = '.github/workflows'
        self.sub.detail = json.dumps(detail)
        with self.assertRaises(record_snapshot.SnapshotError):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.git.requests, [])

    def test_source_tree_must_match_archive_layout(self):
        self.git.trees[self.git.source_tree]['outside'] = self.git.blob(b'unsafe')
        with self.assertRaisesRegex(record_snapshot.SnapshotError, 'archive layout'):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.writes(), [])

    def test_branch_rule_rejection_with_unchanged_head_does_not_make_repeated_commits(self):
        self.git.before_patch = lambda: None
        with self.assertRaises(httpx.HTTPStatusError):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(sum(r.method == 'PATCH' for r in self.git.requests), 1)
        self.assertEqual(sum(r.method == 'POST' and r.url.path.endswith('/git/commits')
                             for r in self.git.requests), 1)

    def test_continuous_head_changes_have_a_bounded_retry_limit(self):
        sequence = []
        def advance():
            sequence.append(len(sequence))
            tree = self.git.commits[self.git.head]
            self.git.head = identity(['concurrent', sequence])
            self.git.commits[self.git.head] = tree
            self.git.before_patch = advance
        self.git.before_patch = advance
        with self.assertRaisesRegex(record_snapshot.SnapshotError, 'kept changing'):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(len(sequence), record_snapshot.MAX_ATTEMPTS)
        self.assertEqual(sum(r.method == 'PATCH' for r in self.git.requests), record_snapshot.MAX_ATTEMPTS)

    def test_new_contract_may_replace_an_older_epoch_but_never_a_newer_event(self):
        old = self.old_entry(id='2' * 32, source_ref='refs/tags/ots-source/' + '2' * 32,
                             contract='c' * 64, claim=999, finished_at='2026-09-19T11:00:00Z')
        old['source_archive'] = dict(old['source_archive'], contract=old['contract'])
        self.git.set_registry({'version': 1, 'records': {self.sub.track: old}})
        self.assertTrue(record_snapshot.publish_record(self.sub)['published'])
        old['finished_at'] = '2026-09-19T13:00:00Z'
        self.git.set_registry({'version': 1, 'records': {self.sub.track: old}})
        self.git.requests.clear()
        self.assertEqual(record_snapshot.publish_record(self.sub)['reason'], 'superseded')
        self.assertEqual(self.writes(), [])

    def test_symlink_in_checked_root_is_rejected_without_writes(self):
        self.git.trees[self.git.source_tree]['Solution.lean']['mode'] = '120000'
        with self.assertRaisesRegex(record_snapshot.SnapshotError, 'flat-root policy'):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.writes(), [])

    def test_existing_ancestor_file_is_never_replaced_to_create_the_root(self):
        tree = self.git.replace(self.git.commits[self.git.head], 'formal', self.git.blob(b'outside-root file'))
        self.git.head = identity(['ancestor-file', tree])
        self.git.commits[self.git.head] = tree
        with self.assertRaisesRegex(record_snapshot.SnapshotError, 'not a Git directory'):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.writes(), [])

    def test_invalid_existing_registry_is_never_replaced(self):
        self.git.set_registry({'version': 999, 'records': {}})
        with self.assertRaises(record_snapshot.SnapshotError):
            record_snapshot.publish_record(self.sub)
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
