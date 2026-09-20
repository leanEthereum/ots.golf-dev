#!/usr/bin/env python3
"""Search forest-shaped schemes for the cheapest equal-cost disclosure family.

A shape: n = b_1 · … · b_d chains of length L (128-bit values), grouped under d levels of digests
with branching factors b_i (an optional digest chain of length m_i on top of every level-i digest),
under a root of b_d children. A cut reveals one value on every source-to-root path; its cost is the
hash cost of everything strictly above it. The family of a cost c is the set of cuts of cost c with
at most 42 nodes (42 · 128 = 5376 revealed bits). We want the least c whose family has at least
2^115 cuts, within a key-generation budget of 2^20 compressions.

    tools/search_forest.py [--overhead 0] [--max-levels 3] [--max-branch 10] [--digest-chains 0]

The search reported in the paper: --max-levels 4 --max-branch 41 --digest-chains 3. Needs numpy.

Cost of a graph hash on `bits` input bits: ceil((bits + overhead) / 512), at least 1.
The overhead represents explicit node tweaks. The separate 384-bit message-and-nonce query
has no node tweak and always costs one compression. This search counts cuts, not security.
Counts are computed as 2-variable polynomials (cost, nodes) in float64 and the winner is recounted
exactly with Python integers.
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys

import numpy as np

VALUE_BITS, BLOCK, MAX_NODES, KEYGEN_BUDGET, INDEX_BITS = 128, 512, 42, 2 ** 20, 384
NEED = 2 ** 115


def blocks(bits: int, oh: int) -> int:
    return max(1, -(-(bits + oh) // BLOCK))


# --- float polynomials: P[cost, nodes] --------------------------------------------------------

def p_zero(cmax):
    return np.zeros((cmax + 1, MAX_NODES + 1))


def p_mul(a, b, cmax):
    out = p_zero(cmax)
    cs, ms = np.nonzero(a)
    for c, m in zip(cs, ms):
        v = a[c, m]
        out[c:, m:] += v * b[: cmax + 1 - c, : MAX_NODES + 1 - m]
    return out


def p_pow(a, k, cmax):
    result = None
    base = a
    while k:
        if k & 1:
            result = base.copy() if result is None else p_mul(result, base, cmax)
        k >>= 1
        if k:
            base = p_mul(base, base, cmax)
    return result


def chain_poly(L, cmax):
    p = p_zero(cmax)
    for t in range(L + 1):          # reveal position t: L - t steps above it, 1 node
        if L - t <= cmax:
            p[L - t, 1] += 1
    return p


def with_digest_chain(inner, m, h, cmax):
    """y·(1 + x + … + x^m) + x^(m+h)·inner : reveal the digest or one of the m nodes above it,
    or evaluate it (cost h) and everything above."""
    p = p_zero(cmax)
    for j in range(m + 1):
        if j <= cmax:
            p[j, 1] += 1
    shift = m + h
    if shift <= cmax:
        p[shift:, :] += inner[: cmax + 1 - shift, :]
    return p


def shape_poly(L, branches, digests, oh, cmax):
    """branches = (b_1, …, b_d) bottom-up, root has b_d children. digests[i] = digest chain length
    on top of level-i digests (levels 1..d-1). Returns (poly of the root's requirement, keygen)."""
    p = chain_poly(L, cmax)
    n = math.prod(branches)
    keygen = n * L
    count = n
    for i, b in enumerate(branches):
        q = p_pow(p, b, cmax)
        h = blocks(VALUE_BITS * b, oh)
        count //= b
        keygen += count * h
        if i == len(branches) - 1:          # the root: never revealed, always evaluated
            root = p_zero(cmax)
            if h <= cmax:
                root[h:, :] += q[: cmax + 1 - h, :]
            return root, keygen
        m = digests[i]
        keygen += count * m
        p = with_digest_chain(q, m, h, cmax)
    raise AssertionError


def best_cost(poly):
    fam = poly.sum(axis=1)
    for c in range(len(fam)):
        if fam[c] >= NEED:
            return c, fam[c]
    return None, None


# --- exact recount ---------------------------------------------------------------------------

def exact_count(L, branches, digests, oh, cost):
    from collections import defaultdict
    def mul(a, b):
        out = defaultdict(int)
        for (c1, m1), v1 in a.items():
            for (c2, m2), v2 in b.items():
                if c1 + c2 <= cost and m1 + m2 <= MAX_NODES:
                    out[(c1 + c2, m1 + m2)] += v1 * v2
        return dict(out)
    def pw(a, k):
        r = None; base = a
        while k:
            if k & 1: r = dict(base) if r is None else mul(r, base)
            k >>= 1
            if k: base = mul(base, base)
        return r
    p = {(L - t, 1): 1 for t in range(L + 1) if L - t <= cost}
    for i, b in enumerate(branches):
        q = pw(p, b)
        h = blocks(VALUE_BITS * b, oh)
        if i == len(branches) - 1:
            return sum(v for (c, m), v in q.items() if c + h == cost)
        m = digests[i]
        p = {(j, 1): 1 for j in range(m + 1) if j <= cost}
        for (c, mm), v in q.items():
            if c + m + h <= cost:
                p[(c + m + h, mm)] = p.get((c + m + h, mm), 0) + v
    raise AssertionError


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overhead", type=int, default=0, help="explicit tweak bits per graph hash; the index query is unchanged")
    ap.add_argument("--max-levels", type=int, default=3)
    ap.add_argument("--max-branch", type=int, default=10)
    ap.add_argument("--min-branch", type=int, default=2)
    ap.add_argument("--digest-chains", type=int, default=0, help="max digest-chain length per level (stage 2)")
    ap.add_argument("--lengths", default="4-24")
    ap.add_argument("--cmax", type=int, default=140)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--check", default=None, help="evaluate one shape: L,b1,b2,...[;m1,m2,...] e.g. 14,3,3,7")
    a = ap.parse_args()
    oh = a.overhead
    idx = blocks(INDEX_BITS, 0)
    if oh < 0 or a.cmax < 1 or a.max_levels < 1 or a.digest_chains < 0 or a.top < 1:
        ap.error("require overhead and digest-chains >= 0, and cmax, max-levels and top >= 1")
    if not 1 <= a.min_branch <= a.max_branch:
        ap.error("require 1 <= min-branch <= max-branch")
    try:
        lo, hi = map(int, a.lengths.split("-"))
        if not 0 <= lo <= hi:
            raise ValueError
    except ValueError:
        ap.error("--lengths must be a non-negative range, for example 4-24")

    if a.check:
        try:
            spec, _, ds = a.check.partition(";")
            nums = [int(x) for x in spec.split(",")]
            L, branches = nums[0], tuple(nums[1:])
            digests = tuple(int(x) for x in ds.split(",")) if ds else (0,) * (len(branches) - 1)
            if (L < 0 or not branches or any(b < 1 for b in branches)
                    or len(digests) != len(branches) - 1 or any(m < 0 for m in digests)):
                raise ValueError
        except ValueError:
            ap.error("--check requires L,b1,... with L >= 0, positive branches and one digest length per nonroot level")
        poly, keygen = shape_poly(L, branches, digests, oh, a.cmax)
        c, fam = best_cost(poly)
        count_display = f"~{fam:.4g}" if fam is not None else "fewer than 2^115"
        print(f"shape L={L} branches={branches} digests={digests} overhead={oh}: keygen {keygen}, "
              f"family cost {c} ({count_display} cuts), verify {c + idx if c is not None else None}")
        if c is not None:
            print("exact count at that cost:", exact_count(L, branches, digests, oh, c))
        return

    results = []
    cmax = a.cmax
    for d in range(1, a.max_levels + 1):
        for branches in itertools.product(range(a.min_branch, a.max_branch + 1), repeat=d):
            n = math.prod(branches)
            for L in range(lo, hi + 1):
                if n * L > KEYGEN_BUDGET:
                    continue
                for digests in itertools.product(range(a.digest_chains + 1), repeat=d - 1):
                    poly, keygen = shape_poly(L, branches, digests, oh, cmax)
                    if keygen > KEYGEN_BUDGET:
                        continue
                    c, fam = best_cost(poly)
                    if c is None:
                        continue
                    results.append((c + idx, c, L, branches, digests, keygen, fam))
                    if c + 2 < cmax:                    # branch and bound: never need more than the best + 2
                        cmax = c + 2
    results.sort(key=lambda r: (r[0], -r[6]))
    print(f"overhead {oh}: index hash {idx} compression(s); {len(results)} shapes within budget; best verification cost "
          f"{results[0][0] if results else None}")
    for verify, c, L, branches, digests, keygen, fam in results[: a.top]:
        print(f"  verify {verify:3d} = {c} + {idx}   L={L:2d} branches={branches} digests={digests} "
              f"keygen={keygen:4d} family≈{fam:.3g} ({math.log2(fam):.2f} bits)")
    if results:
        verify, c, L, branches, digests, keygen, fam = results[0]
        print("exact recount of the best:", exact_count(L, branches, digests, oh, c), ">= 2^115:",
              exact_count(L, branches, digests, oh, c) >= NEED)


if __name__ == "__main__":
    sys.exit(main())
