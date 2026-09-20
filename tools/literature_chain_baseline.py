#!/usr/bin/env python3
"""Equal-length chains with the competition's existing nonce-grinding encoding.

Reproduce the website's calculated comparison: python3 tools/literature_chain_baseline.py
Construction 4 and Section 5 of https://eprint.iacr.org/2025/889 supply the
equal-chain, fixed-sum layer construction and its counting formula. Here we
retain the competition's 2^115 cuts and nonce grinding, rather than the paper's
direct encoding of a full security-sized digest. See docs/literature-baseline.md.
All arithmetic is exact; this is a cost calculation, not a Lean certificate.
"""
from __future__ import annotations

import json
import re
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG_BITS = 16


def contract_nat(module: str, name: str) -> int:
    source = (ROOT / "formal/OptimalOTS" / module).read_text()
    match = re.search(rf"^def {name}\s*:\s*ℕ\s*:=\s*(\d+)(?:\s*\^\s*(\d+))?\s*$",
                      source, re.MULTILINE)
    if match is None:
        raise ValueError(f"Cannot read {module}:{name}; review the baseline parameters")
    base, exponent = match.groups()
    return int(base) ** int(exponent) if exponent else int(base)


def layer_size(chains: int, steps: int, depth: int) -> int:
    """Coefficient of x^depth in (1 + x + ... + x^steps)^chains."""
    return sum((-1) ** j * comb(chains, j)
               * comb(depth - j * (steps + 1) + chains - 1, chains - 1)
               for j in range(min(chains, depth // (steps + 1)) + 1))


def calculate() -> dict:
    word = contract_nat("Model.lean", "pkBits")
    block = contract_nat("Model.lean", "blockBits")
    nonce = contract_nat("Dag.lean", "nonceBits")
    index_bits = contract_nat("Dag.lean", "idxBits")
    cuts = contract_nat("Dag.lean", "numCuts")
    signature_limit = contract_nat("Model.lean", "maxSignatureBits")
    keygen_limit = contract_nat("Model.lean", "keygenBudget")
    signing_limit = contract_nat("Model.lean", "signBudget")
    failure_bits = contract_nat("Model.lean", "signingFailureBits")
    index_input = contract_nat("Model.lean", "msgBits") + nonce

    def cost(bits: int) -> int:
        return max(1, (bits + block - 1) // block)

    candidates = []
    for chains in range(1, (signature_limit - nonce) // word + 1):
        root_input = chains * word + TAG_BITS
        root_cost = cost(root_input)
        chain_cost = cost(word + TAG_BITS)
        steps = (keygen_limit - root_cost) // (chains * chain_cost)
        if steps < 1:
            continue
        # Longer chains only add fixed-sum vectors. The longest allowed length
        # therefore gives the smallest feasible depth for this chain count.
        # Coefficients are symmetric/unimodal, so a feasible minimum is <= midpoint.
        for depth in range(chains * steps // 2 + 1):
            count = layer_size(chains, steps, depth)
            if count >= cuts:
                candidates.append({
                    "chains": chains, "steps_per_chain": steps,
                    "chain_compressions": depth * chain_cost,
                    "root_compressions": root_cost, "index_compressions": cost(index_input),
                    "verify_compressions": depth * chain_cost + root_cost + cost(index_input),
                    "keygen_compressions": chains * steps * chain_cost + root_cost,
                    "signature_bits": nonce + chains * word,
                    "layer_size": count, "previous_layer_size": layer_size(chains, steps, depth - 1),
                    "accepted_cuts": cuts,
                })
                break

    best = min(candidates, key=lambda row: row["verify_compressions"])
    # The same signing bound as the forest: each fresh, distinct nonce accepts
    # with probability cuts/2^index_bits. One block misses with probability <=1/2.
    assert (1 << index_bits) % cuts == 0
    trials_per_block = (1 << index_bits) // cuts
    assert 2 * pow(trials_per_block - 1, trials_per_block) <= pow(trials_per_block, trials_per_block)
    assert failure_bits * trials_per_block * cost(index_input) <= signing_limit
    assert failure_bits * trials_per_block <= 1 << nonce
    assert best["chains"] * best["steps_per_chain"] + 1 <= 1 << TAG_BITS
    # These disjoint input lengths keep indexing fresh after key generation.
    assert index_input not in (word + TAG_BITS, best["chains"] * word + TAG_BITS)
    best["signing_trials"] = failure_bits * trials_per_block
    best["failure_bound"] = f"2^-{failure_bits}"
    return best


if __name__ == "__main__":
    print(json.dumps(calculate(), indent=2))
