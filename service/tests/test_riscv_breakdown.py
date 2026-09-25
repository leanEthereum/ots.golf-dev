"""Manual profiles are pinned to checked submissions and never become proof claims."""
import json
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import select

from app import riscv_breakdown as breakdown
from app.config import settings
from app.db import Submission
from app.riscv_profile_format import MAX_BYTES, parse_registry, validate_profile
import seed_demo
import test_riscv_track

SID, REPO = '6' * 32, 'owner/submissions'


def profile():
    return json.loads(breakdown.FIXTURE.read_text())['profile']


def registry():
    return json.dumps({'version': 1, 'profiles': {SID: profile()}}).encode()


class ProfileFormatTests(unittest.TestCase):
    def test_measured_totals_and_hash_prices(self):
        result = validate_profile(profile())
        self.assertEqual((result['cycles'], result['executions']), (702, 691))
        self.assertEqual(sum(r['cycles'] for r in result['rows'] if r['instruction'] == 'HASH'), 173)
        self.assertEqual(sorted((r['bits'], r['price']) for r in result['rows'] if r['instruction'] == 'HASH'),
                         [(192, 1), (384, 1), (6080, 12)])
        for bits, price in [(0, 1), (512, 1), (513, 2)]:
            value = profile()
            value['rows'] = [{'instruction': 'HASH', 'count': 2, 'input_bits': bits}, {'instruction': 'HALT', 'count': 1}]
            self.assertEqual(validate_profile(value)['cycles'], 2 * price + 1)

    def test_bad_rows_fail_validation(self):
        for row in [None, {'instruction': '<script>', 'count': 1}, {'instruction': 'LI', 'count': 1},
                    {'instruction': 'ECALL', 'count': 1}, {'instruction': 'ADD', 'count': True},
                    {'instruction': 'ADD', 'count': 0}, {'instruction': 'ADD', 'count': 1.5},
                    {'instruction': 'ADD', 'count': 1, 'input_bits': 12},
                    {'instruction': 'HASH', 'count': 1}, {'instruction': 'HASH', 'count': 1, 'input_bits': -1},
                    {'instruction': 'HASH', 'count': 1, 'input_bits': True},
                    {'instruction': 'HASH', 'count': 1000000, 'input_bits': 513}]:
            value = profile()
            value['rows'] = [row, {'instruction': 'HALT', 'count': 1}]
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_profile(value)
        for rows in [[{'instruction': 'ADD', 'count': 1}], [{'instruction': 'HALT', 'count': 2}],
                     [{'instruction': 'HALT', 'count': 1}] * 2]:
            value = profile()
            value['rows'] = rows
            with self.assertRaises(ValueError):
                validate_profile(value)

    def test_bad_root_and_duplicate_json_keys_fail(self):
        for raw in [b'{"version":1,"version":1,"profiles":{}}', b'{"version":true,"profiles":{}}',
                    b'{"version":2,"profiles":{}}', b'{' + b' ' * MAX_BYTES]:
            with self.assertRaises(ValueError):
                parse_registry(raw)

    def test_invalid_entry_does_not_hide_valid_siblings(self):
        raw = json.dumps({'version': 1, 'profiles': {SID: profile(), '7' * 32: {'rows': []}}}).encode()
        valid, errors = parse_registry(raw)
        self.assertEqual(list(valid), [SID])
        self.assertEqual(list(errors), ['7' * 32])


class ProfileCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = breakdown.ProfileCache()
        self.responses, self.requests = [], []
        real_client = httpx.Client
        for change in [patch.object(settings, 'submissions_repo', REPO),
                       patch.object(breakdown.httpx, 'Client', side_effect=lambda **kw:
                                    real_client(transport=httpx.MockTransport(self.handle), **kw))]:
            change.start()
            self.addCleanup(change.stop)

    def handle(self, request):
        self.requests.append(request)
        self.assertEqual(str(request.url), f'https://api.github.com/repos/{settings.submissions_repo}/contents/riscv-profiles.json?ref=main')
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def load(self):
        self.responses.append(httpx.Response(200, content=registry(), headers={'ETag': '"one"'}))
        self.cache.refresh()
        self.assertIn(SID, self.cache.snapshot[1])

    def test_cold_start_conditional_refresh_and_owner_deletion(self):
        self.load()
        snapshot = self.cache.snapshot
        self.responses.append(httpx.Response(304))
        self.cache.refresh()
        self.assertEqual(self.requests[-1].headers['If-None-Match'], '"one"')
        self.assertIs(self.cache.snapshot, snapshot)
        for response in [httpx.Response(200, json={'version': 1, 'profiles': {}}), httpx.Response(404)]:
            self.responses.append(response)
            self.cache.refresh()
            self.assertEqual(self.cache.snapshot, (REPO, {}))
            self.load()

    def test_outage_preserves_cache_and_invalid_edit_clears_it(self):
        self.load()
        snapshot = self.cache.snapshot
        for response in [httpx.Response(503), httpx.ReadTimeout('unavailable')]:
            self.responses.append(response)
            self.cache.refresh()
            self.assertIs(self.cache.snapshot, snapshot)
        self.responses.append(httpx.Response(200, content=b'{bad'))
        self.cache.refresh()
        self.assertEqual(self.cache.snapshot, (REPO, {}))
        self.assertIsNone(self.cache.etag)

    def test_download_is_bounded_and_repo_switch_drops_old_data(self):
        self.responses.append(httpx.Response(200, content=b' ' * (MAX_BYTES + 1)))
        self.cache.refresh()
        self.assertEqual(self.cache.snapshot, (REPO, {}))
        self.load()
        with patch.object(settings, 'submissions_repo', 'other/submissions'):
            self.responses.append(httpx.Response(503))
            self.cache.refresh()
            self.assertEqual(self.cache.snapshot, ('other/submissions', {}))


class ProfilePageTests(unittest.TestCase):
    setUp = test_riscv_track.RiscvTrackTests.setUp
    tearDown = test_riscv_track.RiscvTrackTests.tearDown

    def test_only_selected_demo_has_approved_table(self):
        seed_demo.refresh(self.session)
        profiled = []
        for sub in self.session.scalars(select(Submission)):
            html = self.client.get(f'/submissions/{sub.id}').text
            if 'Per-instruction breakdown' in html:
                profiled.append(sub)
                self.assertIn('691', html)
                self.assertIn('>Count</th>', html)
                self.assertIn('(12 cycles / instruction)', html)
                for removed in ['Cycles / call', 'About this example', 'cycle-overview', 'cycle-composition']:
                    self.assertNotIn(removed, html)
        self.assertEqual(len(profiled), 1)
        with patch.object(settings, 'phony', False):
            self.assertIsNone(breakdown.for_submission(profiled[0]))

    def real(self):
        seed_demo.refresh(self.session)
        sub = self.session.scalar(select(Submission).where(Submission.track == 'upper-riscv', Submission.claim == 702))
        sub.id, sub.commit = SID, profile()['commit']
        sub.pr_number, sub.pr_url = 5, f'https://github.com/{REPO}/pull/5'
        sub.source_repo = f'https://github.com/{REPO}.git'
        sub.detail = json.dumps({'contract': profile()['contract']})
        sub.status = 'verified'
        self.session.commit()
        return sub

    def test_real_profile_pins_identity_and_never_changes_claim(self):
        sub = self.real()
        value = validate_profile(profile())
        with patch.object(settings, 'submissions_repo', REPO), \
             patch.object(breakdown.cache, 'snapshot', (REPO, {SID: value})), \
             patch.object(breakdown.httpx, 'Client', side_effect=AssertionError('no page-time network')):
            self.assertIs(breakdown.for_submission(sub), value)
            self.assertIn('Per-instruction breakdown', self.client.get(f'/submissions/{sub.id}').text)
            self.assertEqual(sub.claim, 702)
            for key, invalid in [('commit', 'f' * 40), ('status', 'rejected'), ('claim', 701),
                                 ('track', 'upper-compressions'), ('pr_url', 'https://github.com/other/repo/pull/5')]:
                old = getattr(sub, key)
                setattr(sub, key, invalid)
                self.assertIsNone(breakdown.for_submission(sub), key)
                setattr(sub, key, old)
            sub.detail = json.dumps({'contract': 'f' * 64})
            self.assertIsNone(breakdown.for_submission(sub))

    def test_hinted_profiles_preserve_pins_and_accepting_cost_bound(self):
        sub = self.real()
        sub.track = 'upper-riscv-hint'
        self.session.commit()
        value = validate_profile(profile())
        with patch.object(settings, 'submissions_repo', REPO), \
             patch.object(breakdown.cache, 'snapshot', (REPO, {SID: value})):
            self.assertIs(breakdown.for_submission(sub), value)
            self.assertIn('Per-instruction breakdown', self.client.get(f'/submissions/{sub.id}').text)
            sub.claim = 701
            self.assertIsNone(breakdown.for_submission(sub))
            value['accepted'] = False
            self.assertIs(breakdown.for_submission(sub), value)
            value['commit'] = 'f' * 40
            self.assertIsNone(breakdown.for_submission(sub))

    def test_notes_and_other_ids_cannot_create_a_table(self):
        sub = self.real()
        sub.detail = json.dumps({'contract': profile()['contract'], 'riscv_profile': profile(), 'notes': json.dumps(profile())})
        with patch.object(settings, 'submissions_repo', REPO), \
             patch.object(breakdown.cache, 'snapshot', (REPO, {'7' * 32: validate_profile(profile())})):
            self.assertIsNone(breakdown.for_submission(sub))


if __name__ == '__main__':
    unittest.main()
