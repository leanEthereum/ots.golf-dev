# The upper-bound proof: architecture

The forest proof (the core's internal Generality 2/3 witness, `formal/Witnesses/Generality2/`) proves,
for `forestScheme : Dag.Scheme` (Section 7 of the paper: 63 chains of length 14, 21 group digests,
7 subtree digests, one root) with

```
theorem forestScheme_secure : forestScheme.Secure
theorem forestScheme_verifyCost (i) : forestScheme.verifyCost i = 106
```

(combined into `OptimalOTS.Witnesses.generality2` in `formal/Witnesses/Generality2.lean`).

The `UpperCompressions` reference root runs the same proof on a smaller forest: 54 chains of length
14, 18 group digests, 6 subtree digests and a root of six (2396 nodes, root input 784 bits at two
compressions, key generation 782). With the 5504-bit signature limit a cut may reveal 42 values,
and three shapes of reconstruction cost 103 give more than `2^115` cuts, so it verifies in
`1 + 103 = 104` compressions with `Pr[forge] ≤ (B − 782)/2^127`:

| e revealed | g revealed | active chains | chain cost | nodes | count |
|---|---|---|---|---|---|
| 1 | 2 | 39 | 83 | 42 | C(6,1)·C(15,2)·comp(39,83) |
| 0 | 6 | 36 | 83 | 42 | C(6,0)·C(18,6)·comp(36,83) |
| 1 | 3 | 36 | 84 | 40 | C(6,1)·C(15,3)·comp(36,84) |

Only the shape-specific modules differ (`Names`, `Cuts`, the index types elsewhere, the keygen
constant); the potentials, the signing lemma and the row inequality are unchanged. The numbers
below are those of the 63-chain witness.

The contract offers a single random oracle on bit strings: no labels, no tweaks. The scheme therefore
prepends a 16-bit tweak `tw h` (the index of the hash node `h`) to every hash input, through one extra
deterministic node `ci k t` per chain step and inside the existing concatenation nodes `gc`, `ec`, `rc`
(2795 nodes in all). Revealed values stay the 128-bit nodes, so signatures and costs are unchanged. In
the proof, what a label used to say is read off the string: an index query is a query of length 384
(`encQuery`), and the hash node a query belongs to is the number in its 16 high bits (`tagNat`,
`Graph.Tagging` in `Keygen.lean`, `tagging` in `Values.lean`). The bad event `Spr` (a cached answer at a
non-keygen point that begins with an honest value) only counts strings carrying the node's tweak, so a
fresh answer threatens one node, not every node with that input length: this is where a scheme without
tweaks would lose its 127 bits to a multi-target attack. `Scheme.Secure` demands: for every adversary `A` and every `B` with
`CostAtMost (experiment S A) B`, `probTrue (experiment S A) < B / 2^127`.

## A correction to the paper

The first version of the paper defined `D = {cuts of cost 105}` and claimed every such cut has at most 41 nodes.
This is false: cutting all 63 chains gives cost-105 cuts with 63 nodes.  The stated count
43124494150885380367098178978085896 is the number of cost-105 cuts with **at most 41 nodes**.
The paper now defines `D := {cuts : cost = 105 ∧ |A| ≤ 41}` (so its reveals stay within 5248 bits), and in fact only
the three most common shapes (97.5% of `D`, still > 2^115):

| e revealed | g revealed | active chains | chain cost | nodes | count |
|---|---|---|---|---|---|
| 2 | 3 | 36 | 86 | 41 | C(7,2)·C(15,3)·comp(36,86) |
| 1 | 7 | 33 | 86 | 41 | C(7,1)·C(18,7)·comp(33,86) |
| 2 | 4 | 33 | 87 | 39 | C(7,2)·C(15,4)·comp(33,87) |

where `comp n s` = number of `(c_1..c_n) ∈ [0,14]^n` with sum `s`.

## The proof (paper Section 7.3, reorganized for formalization)

Notation: `ε = 2^-128`, `M = 2^115`, `L = 2^20`, `N = B - 912` (budget after key generation).
`ξ : G.Rec` ranges uniformly over records (sources + hash outputs); `c₀ ξ` is the cache after
key generation (keygen point `P_v ξ = (node τ_v, input_v ξ) ↦ ξ.2 v` for every hash node).

1. **Key generation** (`Keygen.lean`): running `S.keygen` under the lazy oracle from
   `∅` outputs `((pk ξ, evalRec ξ), c₀ ξ)` with probability `|Rec|⁻¹` for each `ξ`, and the
   remaining budget is `N` for every record.

2. **Identical-until-bad** (`IUB.lean`): for a cache `c` disjoint from a cache `f`,
   `E[φ | run oa from (extend c f)] ≤ E[if Hits d f then 1 else φ (x, extend d f) | run oa from c]`
   for `φ ≤ 1`.  Applied twice: stage A (`A.choose`, `f = c₀ ξ`) and stage B
   (`A.forge >>= verify`, `f = fHid i ξ` = points of hash nodes not evaluated at the signed cut).

3. **Supermartingale master lemma** (`Master.lean`): for a potential `Φ` on caches with
   `E_u Φ(c.cacheQuery q u) ≤ Φ c + κ · cost q` at fresh queries, and any continuation bound,
   `CostAtMost (oa >>= k) b → E[F | run oa from c] ≤ Φ c + κ b`.

4. **Events** (`Events.lean`): if the verifier accepts a forgery in the stage-B
   (hidden points removed) run, then the final cache `d` satisfies one of
   * `Spr d ξ`: some entry `(τ_v, u ↦ w)` with `u ≠ input_v ξ` and `trunc w = trunc (ξ.2 v)`;
   * `Hits d (fHid i ξ)`: a hidden keygen point was queried;
   * `IdxPre d_A (u₁, i)`: a pre-signing encoding entry `u ≠ u₁` has index `i`;
   * `IdxPost d' d i`: a post-signing encoding entry has index `i`.

5. **Charges** (`Potentials.lean`), per compression:
   * node-labelled query: `ε` (hidden-point hit, by resampling a hidden coordinate) + `ε` (Spr);
   * encoding query before signing: `κ = 2ε` for the row potential `θ Ψ` (`RowPotential.lean`,
     `psi_charge`): `Ψ = r + Σ_m max(b_m − r a_m, 0) / D_m`, with `r` the fraction of accepted
     indices already held, `a_m` the accepted entries of message `m`, `b_m` those sharing their
     index, `D_m = a_m + q N_m`, `q = M/2^128`, `N_m` the uncached nonces of `m`, and
     `θ = 2^128/(2^128 − 2L)`. One fresh answer raises `Ψ` by at most `11/6 · ε` on average
     (`sum_gCls_le`, from the real inequality `RowIneq.charge_le`), and `θ · 11/6 ≤ 2`;
   * encoding query after signing: `ε` (index equals `i`).
   Total `≤ 2ε` per compression, so `Pr[forge] ≤ 2ε N = (B-912)/2^127 < B/2^127`.

6. **Signing** (`SignRho.lean`, `signRho_bound`): at every trial the signer stops on a bad index
   (one held by another entry) with at most `ρ` times the probability that it stops at all, for
   any `ρ` with `b + c·v/2^128 ≤ ρ (a + c·q)` over the possible numbers `c` of fresh nonces.
   `ρ = θ Ψ` satisfies this (`psi_dom`), so the bad signing event costs at most the current
   encoding term. This disjoint split replaces the earlier union bound
   `|V|/M + L·pairs/(2^nonceBits − L)`, which needed a 256-bit nonce; the argument holds for the
   128-bit nonce and every budget up to `2^127` ([the 128-bit nonce analysis](nonce-128-analysis.md)).

The case `B > 2^127` is trivial (`probTrue ≤ 1 < B/2^127`), so all counting invariants may
assume `N ≤ 2^127`.

## Files

See the table in [the witness README](../formal/Witnesses/Generality2/README.md); the module names are
`Witnesses.Generality2.<File>`.
