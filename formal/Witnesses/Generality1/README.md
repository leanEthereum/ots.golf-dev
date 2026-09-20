# Whole-word DAGs witness: the forest with tweak words

An internal maintainer check, not a track and not a submission. The Whole-word DAGs lower bound
quantifies over secure whole-word DAG schemes (`Graph.WholeWords` in
`OptimalOTS/WholeWords.lean`); this proof shows that class is non-empty.
[`../Generality1.lean`](../Generality1.lean) states

```lean
theorem OptimalOTS.Witnesses.generality1 :
    ∃ S : Scheme, S.graph.WholeWords ∧ S.Secure ∧ ∀ i, S.verifyCost i ≤ 106
```

Check it from `formal/` with `lake build Witnesses` (also run by `tools/check_repo.py --formal`).

## Construction

The whole-word witness uses 128-bit tweak words so every deterministic operation fits the
remaining lower-bound class.

| node | value | bits | whole-word kind |
|---|---|---|---|
| `tc k t`, `tg j`, `te l`, `tr` | `tw (ch k t)`, `tw (gh j)`, `tw (eh l)`, `tw rh` | 128 | constant word |
| `src k` | source `z_k` | 128 | source |
| `ci k t` | `tw (ch k t) ‖ c_{k,t}` | 256 | concatenation `[c_{k,t}, tc k t]` |
| `ch k t` | `H(ci k t)` | 256 | hash |
| `cv k t` | `c_{k,t+1}` = low half of `ch k t` | 128 | half |
| `gc j` | `tw (gh j) ‖ c_{3j,14} ‖ c_{3j+1,14} ‖ c_{3j+2,14}` | 512 | concatenation |
| `gh j`, `gv j` | `H(gc j)`, its low half `g_j` | 256, 128 | hash, half |
| `ec l` | `tw (eh l) ‖ g_{3l} ‖ g_{3l+1} ‖ g_{3l+2}` | 512 | concatenation |
| `eh l`, `ev l` | `H(ec l)`, its low half `e_l` | 256, 128 | hash, half |
| `rc` | `tw rh ‖ e_0 ‖ ⋯ ‖ e_6` | 1024 | concatenation |
| `rh` | the root `H(rc)` | 256 | hash |

- 3706 nodes: the 911 tweak words first (indices 0 to 910), then the 2795 forest nodes in the
  topological order.
- A chain step and a grouping hash cost one compression each (256 and 512 bits), the root two
  (1024 bits): key generation costs 882 + 21 + 7 + 2 = 912 compressions. No hash input has the
  384 bits of an index query.
- The disclosure family consists of cuts
  of reconstruction cost 105 with at most 41 revealed values, so every signature verifies in
  `1 + 105 = 106` compressions.
- Security: `Pr[forge] ≤ (B - 912) / 2 ^ 127` for every budget `B ≤ 2 ^ 127`.

## Proof structure

The proof modules in this directory are self-contained and build with `lake build Witnesses`.

* `Names.lean`: 128-bit tweak words as constant nodes; hash inputs of 256, 512 and 1024 bits;
  `tagNat` reads the high 128-bit word; a hash input carries its tweak once its tweak word has its
  value (`tagNat_detVal`).
* `Keygen.lean`: a `Graph.Tagging` only asks the input of a hash node to carry its tag when the
  constant parents of that input have their values (`Graph.ConstAt`); the evaluation invariant
  `Tagged` also records that the constant nodes already evaluated have their values.
* `Tree.lean`, `Cuts.lean`: the tweak words are leaves of the tree; a cut never reveals one
  (`IsCut.notTw`).
* `Values.lean`, `Events.lean`, `Resample.lean`: the tweak words in the node equations; a tweak
  word visited by the verifier is recomputed, so a forged hash input still carries its tweak
  (`tagNat_yv`), and the security argument passes through the tweak words.
* `Words.lean` (new): `graph_wholeWords : graph.WholeWords`.

## Files

| File | Content |
|---|---|
| `Semantics.lean` | records and deterministic evaluation |
| `Cache.lean`, `IUB.lean`, `Master.lean` | the lazy random oracle's cache; the identical-until-bad coupling; the supermartingale master lemma |
| `Keygen.lean`, `Reconstruct.lean`, `SignIdx.lean`, `EncCharges.lean` | key generation as a uniform record; the verifier's run; the signing loop; the encoding-entry count and the `IdxPost` charge |
| `Names.lean`, `Tree.lean` | the 3706-node computation graph; the tree structure, visited sets, costs, cuts |
| `Words.lean` | the graph is a whole-word graph |
| `Count.lean`, `Cuts.lean`, `Scheme.lean` | the disclosure family (more than `2 ^ 115` sets) and `forestScheme` |
| `Values.lean`, `Resample.lean`, `Events.lean` | node values; hidden and exposed keygen points; uniformity of hidden inputs; an accepted forgery is one of the charged events |
| `SignRho.lean`, `Rows.lean`, `RowIneq.lean`, `RowPotential.lean` | the disjoint signing lemma, per-message rows of the cache, the row potential and its charge |
| `Potentials.lean`, `StageB.lean`, `Assembly.lean`, `Main.lean` | the potentials, the two attacker stages, the bound, `forestScheme_secure` |
