"""Only the audited unchanged statements retain their already verified history."""
import json
import unittest
from unittest.mock import patch

from app import contract
from app.db import Submission


class ContractRetirementTests(unittest.TestCase):
    OLD = 'a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb'
    NEW = 'cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc'

    def test_only_verified_surviving_results_are_compatible_without_rewriting_identity(self):
        with patch('app.contract.contract_id', return_value=self.NEW):
            for slug in ('lower-generality-1', 'upper-compressions', 'upper-riscv'):
                sub = Submission(track=slug, status='verified', detail=json.dumps({'contract': self.OLD}))
                self.assertTrue(sub.current_contract)
                self.assertEqual(sub.detail_dict['contract'], self.OLD)
                for status in ('pending', 'verifying', 'publishing', 'failed', 'rejected'):
                    sub.status = status
                    self.assertFalse(sub.current_contract)
            for slug in ('lower-generality-2', 'lower-generality-3', 'unknown'):
                sub = Submission(track=slug, status='verified', detail=json.dumps({'contract': self.OLD}))
                self.assertFalse(sub.current_contract)

    def test_the_live_contract_carries_every_existing_track_forward(self):
        """Any change to a protected file rotates the contract id. Without an entry keyed on
        the new id, `compatible_result` is False for every stored submission, every board reads
        "No record yet", and the public record roots can be resubmitted verbatim to take the
        records. This is the guard that the entry was not forgotten."""
        live = contract.contract_id()
        self.assertNotEqual(live, 'unpinned')
        self.assertIn(live, contract.RESULT_COMPATIBILITY,
                      'the pinned contract needs an audited RESULT_COMPATIBILITY entry')
        carried = contract.RESULT_COMPATIBILITY[live]
        for slug in ('lower-generality-1', 'upper-compressions', 'upper-riscv'):
            self.assertTrue(any(slug in slugs for slugs in carried.values()), slug)
        # Every key and value names a real contract id and a real track.
        known = {t['slug'] for t in contract.tracks()}
        for previous, slugs in carried.items():
            self.assertRegex(previous, r'^[0-9a-f]{64}$')
            self.assertNotEqual(previous, live)
            self.assertTrue(slugs <= known, slugs - known)

    def test_every_contract_keyed_mechanism_survives_the_live_pin(self):
        """Three separate mechanisms gate on the contract id: `RESULT_COMPATIBILITY`, the
        revalidation adoptions, and the per-source RISC-V image audit. Each one silently drops
        history when a later revision rotates the id without extending it, so each is checked
        against the live pin rather than against a hard-coded one."""
        from app import riscv_program_size
        live = contract.contract_id()
        self.assertTrue(riscv_program_size.image_limit_in_force(),
                        'the audited RISC-V image ports lapsed at the live contract')
        # Every `check_contract` the revalidation registry names still resolves.
        from app import revalidations
        for entry in revalidations.entries():
            with self.subTest(track=entry['track']):
                self.assertTrue(
                    entry['check_contract'] == live
                    or contract.compatible_result(entry['track'], entry['check_contract'])
                    or (entry['track'] == 'upper-riscv'
                        and riscv_program_size.compatible_image_source(
                            entry['check_id'], entry['check_commit'], entry['check_contract'])),
                    f"re-adopted {entry['track']} record lapsed at the live contract")

    def test_any_other_contract_revision_requires_another_audit(self):
        sub = Submission(track='upper-compressions', status='verified',
                         detail=json.dumps({'contract': self.OLD}))
        with patch('app.contract.contract_id', return_value='f' * 64):
            self.assertFalse(sub.current_contract)
        with patch('app.contract.contract_id', return_value=self.NEW):
            sub.detail = json.dumps({'contract': 'e' * 64})
            self.assertFalse(sub.current_contract)

    def test_expanded_keygen_preserves_upper_results_but_requires_new_lower_certificate(self):
        with patch('app.contract.contract_id', return_value=
                   '133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e'):
            for previous in (self.OLD, self.NEW):
                for slug in ('lower-generality-1', 'upper-compressions', 'upper-riscv'):
                    sub = Submission(track=slug, status='verified',
                                     detail=json.dumps({'contract': previous}))
                    self.assertEqual(sub.current_contract, slug.startswith("upper-"))
