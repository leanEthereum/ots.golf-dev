"""Regression checks for numerical tools; these never replace the Lean certificates."""
import math
import re
import runpy
import subprocess
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NumericalToolTests(unittest.TestCase):
    def test_equal_chain_baseline_matches_independent_convolution_and_chart(self):
        tool = runpy.run_path(str(ROOT / 'tools/literature_chain_baseline.py'))
        result = tool['calculate']()
        reference = runpy.run_path(str(ROOT / 'service/app/literature.py'))['EQUAL_CHAINS']
        self.assertEqual(result['verify_compressions'], reference['value'])
        self.assertEqual((result['chains'], result['steps_per_chain'], result['chain_compressions']),
                         (42, 24, 93))
        # Independently multiply polynomials, truncating only terms beyond the depth.
        depth = result['chain_compressions']
        row = [1] + [0] * depth
        for _ in range(result['chains']):
            row = [sum(row[max(0, d - result['steps_per_chain']):d + 1]) for d in range(depth + 1)]
        self.assertEqual(row[-1], result['layer_size'])
        self.assertEqual(row[-2], result['previous_layer_size'])
        self.assertLess(row[-2], result['accepted_cuts'])
        self.assertGreaterEqual(row[-1], result['accepted_cuts'])
        self.assertEqual(result['signature_bits'], 5504)
        self.assertEqual(result['keygen_compressions'], 1019)
        self.assertEqual(result['signing_trials'], 2 ** 20)

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, str(ROOT / 'tools' / tool), *args],
                              capture_output=True, text=True, timeout=30)

    def contract_nat(self, module, name):
        source = (ROOT / 'formal' / 'OptimalOTS' / module).read_text()
        match = re.search(rf'^def {name}\s*:\s*ℕ\s*:=\s*(\d+)(?:\s*\^\s*(\d+))?\s*$',
                          source, re.MULTILINE)
        self.assertIsNotNone(match, f'{module}.{name}: expected a literal or power')
        base, exponent = match.groups()
        return int(base) ** int(exponent) if exponent else int(base)

    def test_lower_bound_parameters_match_the_protected_contract(self):
        tool = runpy.run_path(str(ROOT / 'tools' / 'tune_lower_bound.py'))
        message_bits = self.contract_nat('Model.lean', 'msgBits')
        nonce_bits = self.contract_nat('Dag.lean', 'nonceBits')
        block_bits = self.contract_nat('Model.lean', 'blockBits')
        index_cost = max(1, (message_bits + nonce_bits + block_bits - 1) // block_bits)
        trials = self.contract_nat('Model.lean', 'signBudget') // index_cost
        cuts = self.contract_nat('Dag.lean', 'numCuts')
        indices = 2 ** self.contract_nat('Dag.lean', 'idxBits')
        self.assertEqual((tool['M'], tool['N'], tool['L']), (cuts, indices, trials))
        self.assertEqual(tool['SIGN_SUCCESS_LOWER_BOUND'],
                         Fraction(trials * cuts, indices + trials * cuts))
        self.assertEqual(tool['PAYLOAD_BITS'],
                         self.contract_nat('Model.lean', 'maxSignatureBits') - nonce_bits)

    def test_forest_index_width_matches_the_protected_contract(self):
        tool = runpy.run_path(str(ROOT / 'tools' / 'search_forest.py'))
        self.assertEqual(tool['INDEX_BITS'], self.contract_nat('Model.lean', 'msgBits')
                         + self.contract_nat('Dag.lean', 'nonceBits'))

    def test_whole_word_output_uses_current_budget_and_reciprocal_bound(self):
        result = self.run_tool('tune_lower_bound.py', '--method', 'words', '--claims', '90')
        self.assertEqual(result.returncode, 0, result.stderr)
        trials = self.contract_nat('Model.lean', 'signBudget')  # index cost is one
        cuts = self.contract_nat('Dag.lean', 'numCuts')
        indices = 2 ** self.contract_nat('Dag.lean', 'idxBits')
        budget = self.contract_nat('Model.lean', 'keygenBudget') + trials + 2 ** 122 + 2 * 88 + 2
        signing_success = Fraction(trials * cuts, indices + trials * cuts)
        search_success = Fraction(cuts, 64 * math.comb(87 + 42, 42) + cuts)
        success = Fraction(99, 100) ** 2 * signing_success * search_success
        self.assertIn(f'exact total budget = {budget};', result.stdout)
        self.assertIn(f'exact success lower bound = {success}\n', result.stdout)

    def test_tagged_forest_keeps_the_index_at_one_compression(self):
        result = self.run_tool('search_forest.py', '--check', '14,3,3,7', '--overhead', '16')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('keygen 912, family cost 105', result.stdout)
        self.assertIn('verify 106', result.stdout)
        self.assertIn('43124494150885380367098178978085896', result.stdout)

    def test_small_family_is_reported_without_a_formatting_crash(self):
        result = self.run_tool('search_forest.py', '--check', '1,2', '--cmax', '5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fewer than 2^115 cuts', result.stdout)
        self.assertIn('verify None', result.stdout)

    def test_malformed_shapes_are_usage_errors(self):
        for shape in ('14', '14,0', '14,3,3;1,2', '14,3;-1', 'text'):
            with self.subTest(shape=shape):
                result = self.run_tool('search_forest.py', '--check', shape)
                self.assertEqual(result.returncode, 2)
                self.assertIn('--check requires', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_whole_word_certificate_arithmetic_and_next_claim(self):
        result = self.run_tool('tune_lower_bound.py', '--method', 'words', '--claims', '90,91')
        self.assertEqual(result.returncode, 0, result.stderr)
        positive, negative = result.stdout.split('c=91,')
        self.assertIn('certificate success >= 9801/280000: True', positive)
        self.assertIn('exact success > budget/2^127: True', positive)
        self.assertIn('exact success > budget/2^127: False', negative)

    def test_existing_dag_and_historical_disclosure_points(self):
        for method, claim in [('patterns', '18'), ('disclosure', '80')]:
            with self.subTest(method=method):
                result = self.run_tool('tune_lower_bound.py', '--method', method, '--claims', claim)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = ('exact success bound > cost/2^127: True' if method == 'patterns'
                            else 'exact success > budget/2^127: True')
                self.assertIn(expected, result.stdout)


if __name__ == '__main__':
    unittest.main()
