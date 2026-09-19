"""Framework isolation and non-destructive local demo refresh checks."""
from __future__ import annotations

import json
import copy
import re
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import contract, github, records
from app.db import Base, Submission, User, get_session, utcnow
from app.main import app, queue_submission
import seed_demo


class FrameworkTests(unittest.TestCase):
    maxDiff = 1500

    def setUp(self):
        # Preserve the original four-track preview as a compatibility fixture. The
        # RISC-V suite separately checks the expanded contract and the migration.
        cfg = copy.deepcopy(contract.load())
        cfg['tracks'] = [t for t in cfg['tracks'] if t['slug'] != 'upper-riscv']
        if 'upper_tracks' in cfg:
            cfg['upper_tracks'] = [t for t in cfg['upper_tracks'] if t != 'upper-riscv']
        patcher = patch.object(contract, 'load', return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)

        def session_dependency():
            yield self.session

        app.dependency_overrides[get_session] = session_dependency
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_frameworks_have_three_pinned_lower_tracks(self):
        self.assertEqual({k: t["slug"] for k, t in contract.framework_tracks("generality-2").items()},
                         {"lower": "lower-generality-2"})
        self.assertIsNone(records.interval(self.session, "generality-2")["upper"])
        self.assertEqual({k: t["slug"] for k, t in contract.framework_tracks("generality-1").items()},
                         {"lower": "lower-generality-1"})
        self.assertIsNone(records.interval(self.session, "generality-1")["upper"])
        self.assertEqual(contract.framework_tracks('generality-3')['lower']['slug'], 'lower-generality-3')
        self.assertEqual(contract.upper_compressions_track()['slug'], 'upper-compressions')
        self.assertIsNone(records.interval(self.session, "generality-3")["lower"]["record_claim"])
        self.assertEqual(contract.framework("generality-3")["status"], "active")

    def chart(self, html):
        return json.loads(re.search(r'<script id="chart-points" type="application/json">(.*?)</script>',
                                    html, re.S).group(1))

    def chart_svg(self, html):
        return ET.fromstring(re.search(r'<svg[^>]+class="record-chart".*?</svg>', html, re.S).group(0))

    def test_combined_chart_keeps_records_attributed_and_board_filters_independent(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        for framework in ("all", "generality-2", "generality-1", "generality-3"):
            response = self.client.get("/", params={"framework": framework})
            self.assertEqual(response.status_code, 200)
            html = response.text
            points = self.chart(html)
            self.assertEqual({p['framework'] for p in points}, {'generality-3', 'generality-2', 'generality-1'})
            self.assertEqual({p['kind'] for p in points}, {'lower', 'upper'})
            for point in points:
                sub = self.session.get(Submission, point["id"])
                self.assertEqual(contract.track(sub.track)["framework"], point['framework'])
                self.assertEqual(sub.claim, point['claim'])
                self.assertTrue(point['demo'])
            tables = set(re.findall(r'<table class="lb-table" data-track="([^"]+)"', html))
            expected = {t['slug'] for t in contract.tracks() if t['kind'] == 'lower'} | {'upper-compressions'}
            self.assertEqual(tables, expected)
            shown = re.findall(r'<section class="framework-board f-([\w-]+)" data-framework="[\w-]+" aria-labelledby="[^"]+">', html)
            self.assertEqual(shown, [framework if framework != 'all' else 'generality-1'])
            self.assertEqual(re.findall(r'class="lower-btn" data-framework="([\w-]+)" aria-pressed="true"', html), shown)
        html = self.client.get('/').text
        self.assertEqual(len(re.findall(r'<table class="lb-table"', html)), 4)
        self.assertEqual(len(re.findall(r'<article class="framework-card ', html)), 3)

    def test_lower_generality_3_is_certified_and_uses_normal_leaderboard(self):
        response = self.client.get("/?framework=generality-3")
        self.assertEqual(response.status_code, 200)
        svg = self.chart_svg(response.text)
        # No record yet: no series and no reference line, only the empty state.
        self.assertEqual(svg.findall("./g"), [])
        self.assertIn('No records yet', [t.text for t in svg.findall('./text')])
        self.assertEqual(self.chart(response.text), [])
        self.assertIn('<p>Any oracle algorithm.</p>', response.text)
        self.assertIn('<table class="lb-table" data-track="lower-generality-3">', response.text)
        self.assertIn('0 records, 0 solvers', response.text)
        self.assertNotIn('baseline', response.text.lower())
        lower_panel = re.search(r'<div class="board-track" data-track="lower">(.*?)'
                                r'<div class="board-track" data-track="upper"', response.text, re.S).group(1)
        self.assertNotIn('pending', lower_panel.lower())
        self.assertNotIn('foundation', lower_panel.lower())
        self.assertEqual(svg.findall("./g[@data-kind='lower'][@data-status='pending']"), [])
        self.assertEqual(self.client.get("/?framework=unknown").status_code, 404)

    def test_generic_result_is_vitalik_submission_on_board_chart_and_profile(self):
        seed_demo.refresh(self.session)
        sub = self.session.scalar(select(Submission).where(Submission.track == 'lower-generality-3'))
        self.assertEqual((sub.user.login, sub.claim, sub.is_record), ('vitalik-buterin', 1, True))
        self.assertTrue(sub.detail_dict['demo'])
        identity = (sub.id, sub.created_at, sub.record_at)
        self.assertEqual(seed_demo.refresh(self.session), 0)
        self.assertEqual((sub.id, sub.created_at, sub.record_at), identity)
        self.assertEqual(len(list(self.session.scalars(
            select(Submission).where(Submission.track == 'lower-generality-3')))), 1)

        html = self.client.get('/?framework=generality-3').text
        self.assertIn('1 record, 1 solver', html)
        self.assertIn('class="lb-row record current" data-score="1"', html)
        self.assertIn(f'href="/submissions/{sub.id}"', html)
        self.assertIn('href="/solvers/vitalik-buterin"', html)
        self.assertNotIn('baseline', html.lower())
        points = [p for p in self.chart(html) if p['framework'] == 'generality-3' and p['kind'] == 'lower']
        self.assertEqual([(p['id'], p['claim'], p['login']) for p in points],
                         [(sub.id, 1, 'vitalik-buterin')])
        self.assertTrue(points[0]['demo'])
        detail = self.client.get(f'/submissions/{sub.id}').text
        self.assertIn('1 compression', detail)
        self.assertIn('Lower bound · Generality 3/3', detail)
        self.assertNotIn('This claim covers', detail)
        self.assertNotIn('demo', detail)
        self.assertNotIn('DAG framework', detail)
        self.assertNotIn('baseline', detail.lower())
        profile = self.client.get('/solvers/vitalik-buterin').text
        self.assertIn(f'href="/submissions/{sub.id}"', profile)
        self.assertIn('href="/?framework=generality-3#lower">Lower bound · Generality 3/3</a>', profile)
        self.assertNotIn('baseline', profile.lower())

    def test_single_upper_compressions_uses_its_own_records_and_attribution(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        html = self.client.get('/').text
        svg = self.chart_svg(html)
        uppers = svg.findall("./g[@data-kind='upper']")
        self.assertEqual(len(uppers), 1)
        self.assertEqual(uppers[0].get('data-series'), 'upper-compressions')
        self.assertEqual(uppers[0].get('data-status'), 'certified')
        self.assertEqual(''.join(uppers[0].find("text[@class='label']").itertext()), 'Upper bound · 104')
        self.assertEqual(len(uppers[0].findall(".//a[@class='chart-record']")), 15)
        self.assertNotIn('admission pending', html.lower())
        self.assertNotIn('candidate', html.lower())
        self.assertFalse('data-track="disclosure-upper"' in html)
        points = [p for p in self.chart(html) if p['kind'] == 'upper']
        self.assertEqual([(p['claim'], p['login']) for p in points],
                         [(128, 'hal-finney'), (125, 'hal-finney'), (122, 'vitalik-buterin'),
                          (119, 'vitalik-buterin'), (117, 'satoshi-nakamoto'), (115, 'satoshi-nakamoto'),
                          (113, 'hal-finney'), (112, 'hal-finney'), (110, 'vitalik-buterin'),
                          (109, 'satoshi-nakamoto'), (108, 'hal-finney'), (107, 'vitalik-buterin'),
                          (106, 'satoshi-nakamoto'), (105, 'vitalik-buterin'), (104, 'satoshi-nakamoto')])
        for point in points:
            sub = self.session.get(Submission, point['id'])
            self.assertEqual(sub.track, 'upper-compressions')
            detail = self.client.get(f'/submissions/{sub.id}').text
            self.assertIn('Upper bound · compressions', detail)
            self.assertNotIn('must prove', detail)
            self.assertIn('href="/#upper"', detail)
            self.assertNotIn('signing success at least 1/2', detail)
            self.assertIn('href="/#upper">Upper bound · compressions</a>',
              self.client.get('/solvers/satoshi-nakamoto').text)

    def test_lower_records_do_not_initialize_upper_compressions(self):
        seed_demo.add_rows(self.session, seed_demo.BASE_ROWS)
        self.session.commit()
        html = self.client.get('/').text
        self.assertIsNone(self.chart_svg(html).find("./g[@data-series='upper-compressions']"))
        self.assertIsNone(records.current_record(self.session, 'upper-compressions'))

    def test_missing_upper_compressions_metadata_does_not_seed_or_admit(self):
        cfg = copy.deepcopy(contract.load())
        cfg['tracks'] = [t for t in cfg['tracks'] if t['slug'] != 'upper-compressions']
        with patch.object(contract, 'load', return_value=cfg):
            self.assertIsNone(contract.upper_compressions_track())
            self.assertEqual(seed_demo.refresh(self.session), 24)
            self.assertEqual(seed_demo.refresh(self.session), 0)
            html = self.client.get('/').text
            self.assertNotIn('data-track="upper-compressions"', html)
            self.assertFalse(any(p['kind'] == 'upper' for p in self.chart(html)))
            with self.assertRaises(HTTPException) as caught:
                queue_submission(self.session, User(login='tester'), 'upper-compressions', 'local', 'a' * 40,
                                 None, [], None, None, None)
            self.assertEqual(caught.exception.status_code, 400)

    def test_upper_compressions_migration_preserves_all_existing_demo_rows(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS[:-len(seed_demo.UPPER_COMPRESSIONS_ROWS)])
        self.session.commit()
        before = {s.id: (s.created_at, s.finished_at, s.record_at, s.commit, s.claim, s.track)
                  for s in self.session.scalars(select(Submission))}
        self.assertEqual(len(before), 24)
        self.assertEqual(seed_demo.refresh(self.session), 16)
        self.assertEqual(seed_demo.refresh(self.session), 0)
        for identifier, old in before.items():
            s = self.session.get(Submission, identifier)
            self.assertEqual((s.created_at, s.finished_at, s.record_at, s.commit, s.claim, s.track), old)
        self.assertEqual(len(list(self.session.scalars(select(Submission)))), 40)

    def test_refresh_restores_one_missing_fixture_in_an_existing_track(self):
        seed_demo.refresh(self.session)
        sub = self.session.scalar(select(Submission).where(Submission.track == 'upper-compressions'))
        missing_fixture = sub.detail_dict['fixture_id']
        self.session.delete(sub)
        self.session.commit()
        before = {s.id: (s.created_at, s.record_at) for s in self.session.scalars(select(Submission))}
        self.assertEqual(seed_demo.refresh(self.session), 1)
        self.assertEqual(seed_demo.refresh(self.session), 0)
        rows = list(self.session.scalars(select(Submission)))
        self.assertEqual(sum(s.detail_dict.get('fixture_id') == missing_fixture for s in rows), 1)
        for s in rows:
            if s.id in before:
                self.assertEqual((s.created_at, s.record_at), before[s.id])

    def test_refresh_adopts_old_demo_rows_without_replacing_them(self):
        seed_demo.refresh(self.session)
        before = {}
        for sub in self.session.scalars(select(Submission)):
            before[sub.id] = (sub.created_at, sub.record_at, sub.commit)
            detail = sub.detail_dict
            detail.pop('fixture_id')
            sub.detail = json.dumps(detail)
        self.session.commit()
        self.assertEqual(seed_demo.refresh(self.session), 0)
        rows = list(self.session.scalars(select(Submission)))
        self.assertEqual(len(rows), len(before))
        for sub in rows:
            self.assertEqual((sub.created_at, sub.record_at, sub.commit), before[sub.id])
            self.assertIn('fixture_id', sub.detail_dict)

    def test_tracks_without_records_show_no_record_yet(self):
        html = self.client.get('/').text
        self.assertEqual(self.chart_svg(html).findall('./g'), [])
        # Three lower cards, the upper card, and the four boards.
        self.assertEqual(html.count('No record yet'), 8)
        self.assertEqual(html.count('Submit a proof ↗'), 3)
        self.assertEqual(html.count('Submit a construction ↗'), 1)
        self.assertNotIn('class="board-big"', html)
        self.assertFalse('Local demo leaderboard' in html)
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        self.assertNotIn('No record yet', self.client.get('/').text)

    def test_rules_explain_models_without_leaderboard_scores(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        html = self.client.get('/rules').text
        body = re.search(r'<main\b[^>]*>(.*?)</main>', html, re.S).group(1)
        self.assertNotRegex(re.sub(r'<[^>]*>', ' ', body), r'\b(?:18|80|93|104|106)\b')
        self.assertFalse('framework-comparison' in body)
        self.assertTrue('whole 128-bit words' in body)
        self.assertTrue('id="generic-algorithms"' in body)
        self.assertTrue('<h3>Upper bounds</h3>' in body)

    def test_refresh_preserves_existing_rows_and_adds_missing_tracks_once(self):
        seed_demo.add_rows(self.session, seed_demo.BASE_ROWS)
        real_user = User(login="real-solver")
        self.session.add(real_user)
        self.session.flush()
        real = Submission(track="lower-generality-2", user_id=real_user.id, claim=18, status="verified",
                          source_repo="local", commit="a" * 40, finished_at=utcnow())
        self.session.add(real)
        self.session.commit()
        old = {s.id: (s.created_at, s.finished_at, s.record_at, s.commit, s.track)
               for s in self.session.scalars(select(Submission))}
        demo = next(s for s in self.session.scalars(select(Submission)) if s.detail_dict.get("demo"))
        demo.claim = 999
        self.session.commit()
        self.assertEqual(seed_demo.refresh(self.session), 30)
        self.assertEqual(seed_demo.refresh(self.session), 0)
        now = list(self.session.scalars(select(Submission)))
        fixture_claims = {r["id"]: r["claim"] for r in seed_demo.FIXTURES["submissions"]}
        self.assertEqual(len(now), sum(bool(contract.track(r[0])) for r in seed_demo.ROWS) + 1)
        generic = [s for s in now if s.track == "lower-generality-3"]
        self.assertEqual(len(generic), 1)
        self.assertEqual((generic[0].claim, generic[0].user.login), (1, 'vitalik-buterin'))
        self.assertEqual(self.session.get(Submission, real.id).claim, 18)
        for sub in now:
            if sub.id in old:
                self.assertEqual((sub.created_at, sub.finished_at, sub.record_at, sub.commit, sub.track), old[sub.id])
            if sub.detail_dict.get("demo"):
                self.assertEqual(sub.claim, fixture_claims[sub.detail_dict["fixture_id"]])

    def test_disclosure_submission_links_to_its_framework(self):
        seed_demo.add_rows(self.session, [next(r for r in seed_demo.ROWS if r[0] == 'lower-generality-1')])
        self.session.commit()
        sub = self.session.scalar(select(Submission))
        html = self.client.get(f"/submissions/{sub.id}").text
        self.assertTrue('href="/?framework=generality-1#lower"' in html)
        self.assertIn('← Back', html)
        self.assertNotIn('Leaderboard</a> /', html)
        self.assertIn('Lower bound · Generality 1/3', html)
        self.assertNotIn('Fictional local demo', html)

    def test_solver_page_names_framework_and_bound_kind(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        html = self.client.get('/solvers/satoshi-nakamoto').text
        self.assertTrue('href="/?framework=generality-2#lower">Lower bound · Generality 2/3</a>' in html)
        self.assertIn('href="/?framework=generality-1#lower">Lower bound · Generality 1/3</a>', html)
        self.assertNotIn('Any oracle algorithm', html)
        self.assertIn('Upper bound · compressions</a>', html)

    def test_refresh_resets_stale_demo_claims_and_keeps_identifiers_dates_and_other_tracks(self):
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()
        fixture_claims = {r["id"]: r["claim"] for r in seed_demo.FIXTURES["submissions"]}
        for sub in self.session.scalars(select(Submission).where(Submission.track == 'lower-generality-1')):
            sub.claim -= 13
        self.session.commit()
        old = {s.id: (s.claim, s.created_at, s.finished_at, s.record_at, s.commit)
               for s in self.session.scalars(select(Submission))}
        self.assertEqual(seed_demo.refresh(self.session),
                         sum(r[0] == 'lower-generality-1' for r in seed_demo.ROWS))
        for sub in self.session.scalars(select(Submission)):
            self.assertIn(sub.id, old)
            self.assertEqual((sub.created_at, sub.finished_at, sub.record_at, sub.commit), old[sub.id][1:])
            self.assertEqual(sub.claim, fixture_claims[sub.detail_dict['fixture_id']])
        self.assertEqual(seed_demo.refresh(self.session), 0)

    def test_fictional_submissions_carry_no_demo_label_and_hide_their_commit(self):
        seed_demo.refresh(self.session)
        home = self.client.get('/').text
        self.assertNotIn('<span class="tag">demo</span>', home)
        self.assertNotIn('· demo', home)
        for sub in self.session.scalars(select(Submission)):
            detail = self.client.get(f'/submissions/{sub.id}').text
            self.assertNotIn('demo', detail)
            self.assertNotIn(sub.commit_url, detail)
        profile = self.client.get('/solvers/vitalik-buterin').text
        self.assertNotIn('demo', profile)

    def test_dashboard_uses_external_scripts_and_precise_sort_timestamps(self):
        seed_demo.refresh(self.session)
        html = self.client.get('/').text
        self.assertIn('class="skip-link" href="#main-content"', html)
        self.assertNotRegex(html, r'<script\s*>')
        self.assertIn('/static/scheme-art.js?v=', html)
        timestamps = re.findall(r'data-date="([^"]+)"', html)
        self.assertTrue(timestamps)
        self.assertTrue(all('T' in stamp for stamp in timestamps))

    def test_public_submission_queue_admits_both_generic_tracks_and_preserves_scope(self):
        user = User(login="generic-solver")
        self.session.add(user)
        self.session.commit()
        sub = queue_submission(self.session, user, "lower-generality-3", "local", "a" * 40,
                               "Generic lower proof", [], None, None, None)
        self.assertEqual(sub.track, "lower-generality-3")
        self.assertEqual(sub.status, "pending")
        self.assertEqual(sub.user_id, user.id)
        html = self.client.get("/?framework=generality-3").text
        self.assertIn(f'href="/submissions/{sub.id}"', html)
        self.assertIn("1 in verification", html)
        upper = queue_submission(self.session, user, "upper-compressions", "local", "b" * 40,
                                 None, [], None, None, None)
        self.assertEqual((upper.track, upper.status, upper.user_id), ('upper-compressions', 'pending', user.id))
        html = self.client.get('/?framework=generality-2').text
        self.assertIn(f'href="/submissions/{upper.id}"', html)

    def test_webhook_root_mapping_includes_new_tracks_and_rejects_mixed_roots(self):
        with patch("app.github.httpx.Client") as client:
            response = client.return_value.__enter__.return_value.get.return_value
            response.json.return_value = [{"filename": "formal/Submissions/LowerGenerality1/Solution.lean"}]
            self.assertEqual(github.pr_track("local/repo", 1), ("lower-generality-1", []))
            response.json.return_value += [{"filename": "formal/Submissions/LowerGenerality2/Solution.lean"}]
            self.assertEqual(github.pr_track("local/repo", 1), (None, []))
            response.json.return_value = [{"filename": "formal/Submissions/LowerGenerality3/Solution.lean"}]
            self.assertEqual(github.pr_track("local/repo", 1), ("lower-generality-3", []))
            response.json.return_value = [{"filename": "formal/Submissions/UpperCompressions/Solution.lean"}]
            self.assertEqual(github.pr_track("local/repo", 1), ("upper-compressions", []))
            response.json.return_value += [{"filename": "formal/Submissions/LowerGenerality1/Solution.lean"}]
            self.assertEqual(github.pr_track("local/repo", 1), (None, []))


if __name__ == "__main__":
    unittest.main()


class NotesJournalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(app)
        seed_demo.add_rows(self.session, seed_demo.ROWS)
        self.session.commit()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_journal_lists_notes_of_records_and_non_records_newest_first(self):
        self.assertEqual(self.client.get('/notes').status_code, 404)
        self.assertNotIn('href="/notes"', self.client.get('/').text)
        md = self.client.get('/notes.md')
        self.assertIn('Pattern classes: group indices', md.text)
        self.assertIn('Not worth retrying without a different graph order.', md.text)
        self.assertIn('Upper bound · compressions', md.text)
        self.assertTrue(md.headers['content-type'].startswith('text/plain'))
        entries = [line for line in md.text.splitlines() if line.startswith('## ') and ': ' in line]
        self.assertGreaterEqual(len(entries), 6)
        self.assertIn('/submissions/', md.text)
        self.assertLess(md.text.index('A 3-level tree with 9 subtrees'), md.text.index('Pattern classes'))

    def test_journal_filters_by_track_and_rejects_unknown_tracks(self):
        md = self.client.get('/notes.md?track=upper-riscv').text
        self.assertIn('RISC-V cycles', md)
        self.assertNotIn('Pattern classes', md)
        self.assertEqual(self.client.get('/notes.md?track=nope').status_code, 404)

