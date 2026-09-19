"""Rules describe the contract independently of leaderboard and candidate claims."""
from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def rules_body(self):
        response = self.client.get('/rules')
        self.assertEqual(response.status_code, 200)
        return re.search(r'<main\b[^>]*>(.*?)</main>', response.text, re.S).group(1)

    def test_rules_do_not_publish_scores_or_candidate_history(self):
        html = self.rules_body()
        self.assertNotRegex(re.sub(r'<[^>]*>', ' ', html), r'\b(?:18|80|93|104|106|987654|876543|765432)\b')
        self.assertNotIn('Certified lower baselines', html)
        self.assertNotIn('Current candidate', html)
        self.assertNotIn('baseline', html)
        self.assertNotIn('proof history', html)

    def test_rules_preserve_framework_links_and_admission_scope(self):
        html = self.rules_body()
        for anchor in ('generic-algorithms', 'upper-compressions', 'graph', 'partial-disclosures', 'whole-words',
                       'legacy-certificates', 'hash', 'security', 'params', 'cut', 'play', 'rules',
                       'generic-admissibility', 'dag-model', 'whole-word-model', 'submission-format'):
            self.assertIn(f'id="{anchor}"', html)
        self.assertIn('What are we optimizing?', html)
        self.assertIn('<h3>Upper bounds</h3>', html)
        self.assertIn('<h3 id="model">Lower bounds</h3>', html)
        self.assertIn('whole 128-bit words', html)
        self.assertIn('A deterministic node may do only three things: output a fixed public word,', html)
        self.assertNotIn('hash origins', html)
        self.assertNotIn('Reed–Solomon', html)
        self.assertIn('Submit an upper-bound construction, or a lower-bound proof', html)
        self.assertNotIn('<strong>Pending:</strong>', html)
        self.assertIn('with probability at most <strong>2<sup>−128</sup></strong>', html)
        self.assertIn('verification accepts with probability one', html)
        self.assertIn('for any message.</p>', html)
        self.assertIn('formal/Submissions/UpperCompressions/', html)
        self.assertIn('formal/Submissions/LowerGenerality3/', html)
        self.assertNotIn('Their submission roots are closed.', html)
        self.assertIn('AGENTS.md#what-a-submission-exports', html)
        self.assertIn('formal/OptimalOTS/Dag.lean', html)
        self.assertIn('formal/OptimalOTS/OracleAlgorithm.lean', html)
        self.assertIn('formal/OptimalOTS/WholeWords.lean', html)

    def test_whole_word_rules_keep_word_sizes_and_two_hash_halves(self):
        html = self.rules_body()
        section = re.search(r'<details id="whole-word-model">.*?</details>',
                            html, re.S).group(0)
        self.assertIn('256 bits', section)
        self.assertIn('whole 128-bit words', section)
        self.assertIn('fixed low or high half of a hash output', section)
        self.assertIn('keeps the <a href="#graph">DAG model of Generality 2/3</a>', section)

    def test_rules_separate_proof_prs_from_core_sources(self):
        with patch.object(settings, 'contract_repo', 'org/core'), \
             patch.object(settings, 'submissions_repo', 'org/entries'):
            html = self.rules_body()
        self.assertIn('href="https://github.com/org/entries">the submissions repository</a>', html)
        self.assertIn('href="https://github.com/org/core/blob/main/formal/OptimalOTS/Dag.lean"', html)
        self.assertNotIn('https://github.com/org/entries/blob/', html)
        self.assertIn('python3 .contract/verifier/verify.py lower-generality-2 --source .', html)

    def test_localhost_links_use_the_new_repositories_without_opening_admission(self):
        with patch.object(settings, 'submissions_repo', ''):
            html = self.rules_body()
            self.assertEqual(settings.submissions_repo, '')
        self.assertIn('https://github.com/leanEthereum/ots.golf-submissions', html)
        self.assertIn('https://github.com/leanEthereum/ots.golf-dev/blob/main/', html)
        self.assertNotIn('TomWambsgans', html)


if __name__ == '__main__':
    unittest.main()
