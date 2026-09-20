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

    def test_any_other_contract_revision_requires_another_audit(self):
        sub = Submission(track='upper-compressions', status='verified',
                         detail=json.dumps({'contract': self.OLD}))
        with patch('app.contract.contract_id', return_value='f' * 64):
            self.assertFalse(sub.current_contract)
        with patch('app.contract.contract_id', return_value=self.NEW):
            sub.detail = json.dumps({'contract': 'e' * 64})
            self.assertFalse(sub.current_contract)

    def test_expanded_keygen_requires_new_certificates_for_all_tracks(self):
        with patch('app.contract.contract_id', return_value=
                   '133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e'):
            for previous in (self.OLD, self.NEW):
                for slug in ('lower-generality-1', 'upper-compressions', 'upper-riscv'):
                    sub = Submission(track=slug, status='verified',
                                     detail=json.dumps({'contract': previous}))
                    self.assertFalse(sub.current_contract)
