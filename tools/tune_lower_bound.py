#!/usr/bin/env python3
"""Check lower-bound attack arithmetic; numerical checks are not certificates.

    tools/tune_lower_bound.py --idx 1 --claims 18
    tools/tune_lower_bound.py --method disclosure --origins 46 --claims 80,81
    tools/tune_lower_bound.py --method words --claims 90,91
    tools/tune_lower_bound.py --method entropy --s-star 5313 --idx 1 --claims 24,25

For a proposed bound c, the attack assumes C_i <= c-1 for all i. Reconstruction
then costs at most v = c-1-idx and evaluates at most a = v-1 hash nodes besides
the root. For q construction attempts, T nonce trials and K target ranks, the
model estimates success as (1-delta) sum omega_l b_l and charges
B = 1024 + L*idx + T*idx + (q+2)*v + 2*idx. A contradiction would need success
(strictly) greater than B/2^127, PLUS all the mathematical attack hypotheses.

The default pattern method and the disclosure method use exact integer and
rational arithmetic. The disclosure method counts bounded-origin traversal
patterns and checks an averaged repetition attack. Its structural counting and
probability hypotheses still require Lean proofs; a positive arithmetic margin
is not a certificate. For the historical origin limit 46, its claim is 80. Whole-word mode derives
42 origins from 5376 payload bits and uses freshness 99/100, certifying the
arithmetic for claim 90. The numerical output alone is not a Lean certificate.

The entropy method is conditional research: its proposed fresh-coordinate lemmas
are false in the bare model, so positive numerical margins do not prove a bound.
Even a Bell(22) union bound would require S* >= 5310 at epsilon=2^-9.
Counting at an integer operating point and its cost are evaluated as exact
fractions. Search, logarithms, and success use floats and the approximation
(1-x)^T ~ exp(-x*T); a positive margin is only numerical evidence. The budget
omits any new bare/separated-oracle coupling loss until that loss is proved.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import math

M, N, L = 2 ** 115, 2 ** 128, 2 ** 20
# (1 - p)^L <= 1 / (1 + L*p), with p = M/N.
SIGN_SUCCESS_LOWER_BOUND = Fraction(L * M, N + L * M)  # 128/129
PAYLOAD_BITS = 5376  # maxSignatureBits 5504 minus the 128-bit nonce
WORD_ORIGINS = PAYLOAD_BITS // 128
EPS = 1 / 512


def beta(a: int, d: float, s_star: int) -> float:
    rho = s_star / d
    return math.prod(((a - 1) * rho / (1 + rho) + k) / (a * rho + k)
                     for k in range(1, a + 1))


def exact_count(a: int, d: int, s_star: int) -> Fraction:
    rho = Fraction(s_star, d)
    return M * math.prod(((a - 1) * rho / (1 + rho) + k) / (a * rho + k)
                         for k in range(1, a + 1))


def bell(n: int) -> int:
    values = [1]
    for j in range(n):
        values.append(sum(math.comb(j, k) * values[k] for k in range(j + 1)))
    return values[n]


def d_min(a: int, K: int, s_star: int) -> float:
    """Threshold for M*beta_a(d) > K; compare with log2(e*q*ln(q))."""
    lo, hi = 1.0, 20000.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if M * beta(a, mid, s_star) > K:
            hi = mid
        else:
            lo = mid
    return hi


def construction_threshold(q: float) -> float:
    return math.log2(math.e * q * math.log(q))


def success(a: int, K: int, T: float) -> float:
    """Estimated rank-integral success, conditional on a feasible threshold."""
    delta = math.exp(L * math.log1p(-2 ** -13))
    total = 0.0
    trial_ratio = T / N
    omega_first = -math.expm1(-trial_ratio)
    for ell in range(1, K + 1):
        omega = math.exp(-(ell - 1) * trial_ratio) * omega_first
        if ell == 1:
            b = 1.0
        else:
            z = (ell - 1) / (K * (1 - EPS))
            b = 0.0 if z >= 1 else (1 - EPS) * (
                1 - a / (a - 1) * z ** (1 / a) + z / (a - 1))
        total += omega * max(b, 0.0)
    return (1 - delta) * total


def cost(idx: int, v: int, q: float | int, T: float | int) -> float | int:
    return 1024 + L * idx + T * idx + (q + 2) * v + 2 * idx


def print_point(c: int, idx: int, s_star: int) -> None:
    """Report the previous proof's simple integer choices, with updated a and v."""
    a, v, K, d0 = c - idx - 2, c - idx - 1, 100, 123
    q, T = 5 * 2 ** 113, 3 * 2 ** 121
    count = exact_count(a, d0, s_star)
    ratio = Fraction(cost(idx, v, q, T), 2 ** 127)
    succ = success(a, K, T)
    print(f"integer point c={c}, S*={s_star}, a={a}, v={v}, K={K}, d0={d0}, "
          "q=5*2^113, T=3*2^121:")
    print(f"  exact count > K: {count > K} (count ~ {float(count):.9f}); "
          f"log2(e*q*ln(q)) ~ {construction_threshold(q):.9f}")
    print(f"  estimated success={succ:.9f}; cost/2^127={float(ratio):.9f}; "
          f"estimated margin={succ - float(ratio):+.9f}")
    print(f"  exact cost < 27/500: {ratio < Fraction(27, 500)}; "
          f"exact count > 100: {count > 100}")


def print_disclosure_point(c: int, origins: int, freshness: Fraction = Fraction(9, 10)) -> None:
    """Exact arithmetic for the proposed bounded-origin repetition attack.

    The hypothesized cost cap c-1 leaves c-3 non-root reconstructed hashes.
    Ordered pattern counting gives the binomial bound from at most that many
    reconstructed hashes and at most `origins` distinct disclosed hash origins. The search uses T=2^122 queries, hence
    N/T=64, and averages k/(64+k) over repetition classes of size k.
    """
    a, v, trials = c - 3, c - 2, 2 ** 122
    count = math.comb(a + origins, origins)
    averaged_search = Fraction(M, 64 * count + M)
    lower = freshness ** 2 * SIGN_SUCCESS_LOWER_BOUND * averaged_search
    budget = 1024 + L + trials + 2 * v + 2
    ratio = Fraction(budget, 2 ** 127)
    margin = lower - ratio
    print(f"c={c}, origins={origins}, a={a}, reconstruction budget={v}, freshness={freshness}")
    print(f"  exact pattern count = choose({a + origins}, {origins}) = {count}")
    print(f"  averaged search success >= {averaged_search}")
    print(f"  exact success lower bound = {lower}")
    print(f"  exact success > 33/1000: {lower > Fraction(33, 1000)} "
          f"(display ~ {float(lower):.12f})")
    if freshness == Fraction(99, 100):
        cutoff = Fraction(9801, 280000)
        print(f"  certificate success >= {cutoff}: {lower >= cutoff}; "
              f"budget/2^127 < {cutoff}: {ratio < cutoff}")
    print(f"  exact total budget = {budget}; budget/2^127 = {ratio}")
    print(f"  exact budget/2^127 < 4/125: {ratio < Fraction(4, 125)} "
          f"(display ~ {float(ratio):.12f})")
    print(f"  exact success > budget/2^127: {margin > 0}")
    print(f"  exact margin = {margin} (display ~ {float(margin):+.12f})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--idx", type=int, default=1)
    ap.add_argument("--method", choices=("patterns", "disclosure", "words", "entropy"), default="patterns")
    ap.add_argument("--origins", type=int, default=46,
                    help="maximum origins for disclosure mode (default: 46); words mode fixes 42")
    ap.add_argument("--s-star", type=int, default=5313,
                    help="conditional entropy information budget (default: 5313)")
    ap.add_argument("--claims", default=None,
                    help="claims to check (default: 18 for patterns, 80 for disclosure, 90 for words, 24,25 for entropy)")
    ap.add_argument("--no-search", action="store_true", help="only report simple integer operating points")
    args = ap.parse_args()
    try:
        defaults = {"patterns": "18", "disclosure": "80", "words": "90", "entropy": "24,25"}
        claims = list(map(int, (args.claims or defaults[args.method]).split(",")))
    except ValueError:
        ap.error("--claims must be comma-separated integers")
    if args.method in ("disclosure", "words"):
        if args.idx != 1 or args.origins < 0 or any(c < 3 for c in claims):
            ap.error("disclosure mode requires --idx 1, origins >= 0, and every claim >= 3")
        print("EXACT DISCLOSURE-ATTACK ARITHMETIC; numerical checks are not certificates.")
        print("The traversal count and averaged attack hypotheses require separate Lean proofs.")
        for c in claims:
            print_disclosure_point(c, WORD_ORIGINS if args.method == "words" else args.origins,
                                   Fraction(99, 100) if args.method == "words" else Fraction(9, 10))
        return 0
    if args.idx < 1 or args.s_star <= 0 or any(c - args.idx - 2 < 2 for c in claims):
        ap.error("require idx >= 1, s-star > 0, and c-idx-2 >= 2 for every proposed claim")
    if args.method == "patterns":
        if args.idx != 1:
            ap.error("the pattern certificate uses the contract constants with --idx 1")
        print("EXACT PATTERN-ATTACK ARITHMETIC; run the official verifier for a certificate.")
        T = 2 ** 122
        for c in claims:
            a, v = c - 3, c - 2
            count = sum(math.comb(1023, k) for k in range(a + 1))
            good = max(Fraction(0), 1 - Fraction(8 * count, M))
            sign_success = SIGN_SUCCESS_LOWER_BOUND
            fresh1 = 1 - Fraction(1024, 2 ** 256)
            fresh2 = 1 - Fraction(1024 + L + 1, 2 ** 256)
            search_success = Fraction(1, 9)
            lower = fresh1 * good * sign_success * fresh2 * search_success
            budget = 1024 + L + T + 2 * v + 2
            ratio = Fraction(budget, 2 ** 127)
            print(f"c={c}, a={a}, reconstruction budget={v}, patterns={count}")
            print(f"  exact pattern count < 2^110: {count < 2 ** 110}")
            print(f"  good-index fraction >= {good}; search success >= 1/9")
            print(f"  exact success bound > cost/2^127: {lower > ratio} "
                  f"(display ~ {float(lower):.9f} > {float(ratio):.9f})")
            if c == 18:
                print(f"  certificate inequalities: success >= 9/200: {lower >= Fraction(9, 200)}; "
                      f"cost/2^127 < 1/25: {ratio < Fraction(1, 25)}")
        return 0
    print("CONDITIONAL NUMERICAL EXPLORATION; no proof or certificate is produced.")
    print(f"index hash = {args.idx} compression(s), S* = {args.s_star}")
    for n in (22, 23):
        value = bell(n)
        ceil_log = (value - 1).bit_length()
        print(f"Bell({n})={value}, log2 ~ {math.log2(value):.9f}, "
              f"5248+9+ceil(log2 Bell({n}))={5257 + ceil_log}")
    print("Historical labeled-model point (not a bare-oracle certificate):")
    print_point(25, 1, 5257)
    for c in claims:
        print_point(c, args.idx, args.s_star)
        if args.no_search:
            continue
        v, a = c - 1 - args.idx, c - 2 - args.idx
        best = None
        for K in (25, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1200, 1600):
            need = d_min(a, K, args.s_star)
            # Success is independent of q once feasible, while cost increases in q.
            # Thus only the first feasible q in the original grid can maximize margin.
            qexp = next((x / 8 for x in range(880, 1000)
                         if construction_threshold(2 ** (x / 8)) >= need), None)
            if qexp is None:
                continue
            q = 2 ** qexp
            for Texp in (x / 8 for x in range(944, 1000)):
                T = 2 ** Texp
                s = success(a, K, T)
                r = cost(args.idx, v, q, T) / 2 ** 127
                margin = s - r
                if best is None or margin > best[0]:
                    best = (margin, K, qexp, Texp, need, s, r)
        if best is None:
            print(f"proposed c={c}: no feasible point in the search ranges")
            continue
        margin, K, qexp, Texp, d0, s, r = best
        print(f"proposed c={c} (a={a}, v={v}): best estimated margin {margin:+.7f}; "
              f"K={K}, q=2^{qexp}, T=2^{Texp}, d0 >= {d0:.6f}, "
              f"success={s:.7f}, cost/2^127={r:.7f}; "
              f"{'POSITIVE' if margin > 0 else 'NONPOSITIVE'} numerical margin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
