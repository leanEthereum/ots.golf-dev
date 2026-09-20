"""A PR's latest checked head determines whether its notes remain published."""
import json
import unittest
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import records
from app.db import Base, Submission, User, utcnow


class JournalHeadsTests(unittest.TestCase):
    def test_latest_head_removing_notes_hides_previous_notes(self):
        self.check_latest(None)

    def test_track_filter_does_not_resurrect_an_older_pr_head(self):
        self.check_latest('New upper notes', track='upper-compressions')

    def check_latest(self, notes, track='lower-generality-1'):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(login='alice')
            session.add(user)
            session.flush()
            now = utcnow()
            for commit, slug, text, at in [('a', 'lower-generality-1', 'Old notes', now - timedelta(seconds=1)),
                                           ('b', track, notes, now)]:
                session.add(Submission(track=slug, user_id=user.id, source_repo='https://github.com/a/b.git',
                    commit=commit * 40, status='verified', pr_number=1,
                    pr_url='https://github.com/a/b/pull/1', finished_at=at,
                    detail=json.dumps({'notes': text})))
            session.commit()
            self.assertEqual(records.journal(session, 'lower-generality-1'), [])
            self.assertNotIn('Old notes', [entry['sub'].notes for entry in records.journal(session)])
            if notes:
                self.assertEqual([entry['sub'].notes for entry in records.journal(session)], [notes])


if __name__ == '__main__':
    unittest.main()
