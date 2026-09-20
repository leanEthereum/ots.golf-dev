"""Attribution is complete, pinned to the admitted head, and safe as Git trailers."""
import unittest
from unittest.mock import patch

import httpx

from app import git_authors


def commit(number, name='Alice', email='alice@example.org', message='Proof'):
    return {'sha': f'{number:040x}', 'commit': {
        'author': {'name': name, 'email': email}, 'message': message}}


class GitAuthorTests(unittest.TestCase):
    def test_all_authors_and_footer_coauthors_deduplicated_by_email(self):
        result = git_authors.from_commits([
            commit(1, message='Proof\n\nCo-authored-by: Bób <bob@example.org>\nSigned-off-by: Other <x@y>'),
            commit(2, name='ALICE', email='ALICE@example.org',
                   message='Followup\n\nco-authored-by: Carol <carol@example.org>'),
            commit(3, name='Bób', email='bob@example.org')])
        self.assertEqual(result, [{'name': 'Alice', 'email': 'alice@example.org'},
                                  {'name': 'Bób', 'email': 'bob@example.org'},
                                  {'name': 'Carol', 'email': 'carol@example.org'}])

    def test_trailer_example_in_prose_is_not_attribution(self):
        result = git_authors.from_commits([commit(1, message=
            'Example\n\nCo-authored-by: Example <example@example.org>\n\nThis is prose.')])
        self.assertEqual(len(result), 1)

    def test_malformed_identity_fails_instead_of_publishing_partial_credit(self):
        for name, email in [('Alice\nInjected', 'a@b'), ('A <B>', 'a@b'), ('', 'a@b'),
                            ('Alice', 'a@b\r\nInjected'), ('Alice', 'no-email')]:
            with self.subTest(name=name, email=email), self.assertRaises(ValueError):
                git_authors.from_commits([commit(1, name=name, email=email)])
        with self.assertRaises(ValueError):
            git_authors.from_commits([commit(1, message='Proof\n\nCo-authored-by: Missing email')])

    def compare(self, batches, total, *, head=101, moved=False):
        base, expected = 'b' * 40, f'{head:040x}'
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.url.path, f'/repos/owner/repo/compare/{base}...{expected}')
            page = int(request.url.params['page'])
            return httpx.Response(200, json={'base_commit': {'sha': base}, 'total_commits': total,
                                           'commits': batches[page - 1]})
        real_client = httpx.Client
        with patch.object(git_authors.github, 'get_pr', return_value={
                'base': {'sha': base}, 'head': {'sha': 'c' * 40 if moved else expected}}), \
             patch.object(git_authors.httpx, 'Client', side_effect=lambda **kw:
                real_client(transport=httpx.MockTransport(handle), **kw)):
            result = git_authors.for_pr('owner/repo', 7, expected)
        return result, requests

    def test_pagination_includes_the_last_commit_author(self):
        result, requests = self.compare([[commit(n) for n in range(1, 101)],
                                         [commit(101, 'Last Author', 'last@example.org')]], 101)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result[-1]['name'], 'Last Author')

    def test_missing_repeated_or_truncated_commits_fail_closed(self):
        for batches, total, head in [([[commit(1)]], 2, 1), ([[commit(1), commit(1)]], 2, 1),
                                     ([[commit(1)]], 1, 2), ([[commit(1)]], 5001, 1)]:
            with self.subTest(total=total, head=head), self.assertRaises(ValueError):
                self.compare(batches, total, head=head)

    def test_head_move_is_refused_before_comparing(self):
        with self.assertRaisesRegex(ValueError, 'PR head changed'):
            self.compare([], 1, head=1, moved=True)


if __name__ == '__main__':
    unittest.main()
