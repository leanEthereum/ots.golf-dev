"""Leaderboard links retain their track and work under the site's script policy."""
from __future__ import annotations

from html.parser import HTMLParser
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import contract, records
from app.db import Base, Submission, User, get_session, utcnow
from app.main import app


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(app)
        user = User(login='navigation-tester')
        self.session.add(user)
        self.subs = {}
        for track in contract.tracks():
            sub = Submission(id=track['slug'], user=user, track=track['slug'],
                             source_repo='local', commit='a' * 40, claim=500,
                             status='verified', is_record=True, finished_at=utcnow())
            self.session.add(sub)
            self.subs[track['slug']] = sub
        self.session.commit()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def expected_url(track):
        if track['kind'] == 'lower':
            return f'/?framework={track["framework"]}#lower'
        return f'/?upper={track["slug"]}#upper'

    def test_submission_backlinks_select_their_own_track_without_inline_script(self):
        for track in contract.tracks():
            with self.subTest(track=track['slug']):
                response = self.client.get(f'/submissions/{self.subs[track["slug"]].id}')
                self.assertEqual(response.status_code, 200)
                back = next(link for link in Links(response.text).links
                            if link.get('class') == 'back')
                self.assertEqual(back['href'], self.expected_url(track))
                self.assertNotIn('onclick', back)
                self.assertIn('← Back to leaderboard</a>', response.text)
                self.assertIn("script-src 'self';", response.headers['content-security-policy'])

    def test_solver_profile_track_links_preserve_both_upper_tracks_and_lower_frameworks(self):
        response = self.client.get('/solvers/navigation-tester')
        self.assertEqual(response.status_code, 200)
        hrefs = {link.get('href') for link in Links(response.text).links}
        for track in contract.tracks():
            with self.subTest(track=track['slug']):
                self.assertIn(self.expected_url(track), hrefs)
        self.assertNotIn('/#upper', hrefs)

    def test_progress_and_journal_track_links_use_the_same_explicit_selection(self):
        for track in contract.tracks():
            with self.subTest(track=track['slug']):
                self.assertEqual(records.track_label(track)[1], self.expected_url(track))


if __name__ == '__main__':
    unittest.main()
