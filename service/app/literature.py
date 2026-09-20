"""Calculated comparisons, separate from certified submission records."""

# Reproduced by tools/literature_chain_baseline.py and checked in tools/tests.
EQUAL_CHAINS = {
    "slug": "equal-chains",
    "label": "Literature",
    "value": 105,
    "url": "https://eprint.iacr.org/2025/889",
    "description": "Calculated literature adaptation with nonce grinding: 42 equal chains of 24 steps; "
                   "93 chain hashes + 11 public-key compressions + 1 message-and-nonce hash. "
                   "Not Lean-certified.",
}
