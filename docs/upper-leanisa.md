# leanISA verification track

The third upper track scores a proved upper bound on the cycles of **every completing
execution** of a leanISA bytecode that verifies a one-time signature. It exists for two reasons:
to put leanISA and RISC-V on one leaderboard in one unit for one problem, and to stress the
leanISA specification against submitters who are rewarded for the cheapest program that still
has to be proved fully constrained.

This guide is written for engineers who know leanISA and leanVM-b but are new to ots.golf, Lean
and VCVio. Every object it names is introduced.

## 1. What a submission is made of

ots.golf checks claims by replaying Lean proofs in the Lean kernel. A track fixes a *contract*:
a set of hash-pinned Lean files the submitter may not edit, declaring the objects a submission
must produce and the theorem it must prove. A submission is a flat directory of `.lean` files
plus a `claim.txt`, exporting declarations whose statements must match the contract's rendered
stub exactly.

Four contract files matter here.

| File | What it holds |
|---|---|
| [`Model.lean`](../formal/OptimalOTS/Model.lean) | the shared constants and the one random oracle |
| [`OracleAlgorithm.lean`](../formal/OptimalOTS/OracleAlgorithm.lean) | `Scheme`, `Admissible`, `Secure` — the OTS layer |
| [`LeanIsaMachine.lean`](../formal/OptimalOTS/LeanIsaMachine.lean) | the machine: weights, the `BLAKE2S` oracle arm, the loader, the loop |
| [`LeanIsa.lean`](../formal/OptimalOTS/LeanIsa.lean) | `Submission` and `Submission.Certificate` |

**The oracle.** There is exactly one random oracle, on bit strings of any length
(`Query := Σ k, BitVec k`). `hash u : OracleComp Spec (BitVec 256)` queries it. Equal strings
always get equal answers; there are no free tweaks, and a scheme that wants a domain separator
pays for its bits. An `OracleComp Spec α` is a free monad over "query the oracle" and "sample
uniformly": a syntax tree of queries, not a function.

Two different semantics are read off that tree, and the difference is load-bearing here.

- `support oa` is the set of values `oa` can produce **for some answers**, with *no cache*: each
  query independently ranges over all `2^256` answers, so the same query may return different
  answers at two points on one path.
- `probTrue oa : ℝ≥0∞` runs `oa` under a lazily sampled, **cached** random oracle and takes the
  probability of `true`. Repeated queries agree, as they do in reality.

`probTrue oa = 0` is not a measure-zero statement: every coherent answer assignment has positive
probability, so it says the event happens on *no* coherent path. Precisely,
`probTrue oa = 0 ↔ true ∉ support ((simulateQ oracleImpl oa).run' ∅)`, proved as
`probTrue_eq_zero_iff` in [`check-leanisa.lean`](../formal/scripts/check-leanisa.lean). Note this
is the support of the *simulated* computation; it is weaker than `true ∉ support oa`, which
would also quantify over incoherent paths.

## 2. Why this track's certificate has six clauses and RISC-V's has four

`upper-riscv` bundles its whole obligation into one equation:

```lean
S.image.Valid ∧ ∀ pk m σ,
  Option.map Prod.fst <$> S.run pk m σ = some <$> S.scheme.verify pk m σ
```

An equality of two free-monad trees forces the same query sequence *and* the same decision, and
the always-`some` right-hand side rules out traps and fuel exhaustion in one stroke.

That equation is unavailable for leanISA, for two independent reasons.

**Memory is committed, not written.** Per §2 of the specification and
`LeanerVM.Semantics.Memory`, the memory is an immutable image `MemImage κ = Fin (2 ^ κ) → E`
committed by an untrusted prover before execution, at a log-size `κ ∈ [16, 32]` the prover also
chooses. No instruction writes. Every instruction reads the cells it names and *asserts* a
relation — `XOR` asserts `m[fp·o_C] = m[fp·o_A] + m[fp·o_B]`, `BLAKE2S` asserts the committed
output pair is the compression of the committed inputs. A violated assertion is not a
rejection; it means this execution does not exist. So **acceptance is "there exists a committed
image driving the run to the sentinel"**, an existential over `Fin (2 ^ κ) → E` that cannot be
written inside an `OracleComp`. The machine has no accept/reject output to equate with anything.

**The honest trees differ anyway.** The prover queries each hash to learn what to commit, and
the machine re-queries it to check the committed cell. The combined tree carries every query
twice where `verify`'s carries it once. They agree under a cached oracle and not as syntax,
which is why the clauses below go through `probTrue`.

So the single equation splits:

```lean
structure Submission.Certificate (S : Submission) (c : ℕ) : Prop where
  admissible : S.scheme.Admissible   -- a correct, budgeted OTS
  secure     : S.scheme.Secure       -- 127-bit strong unforgeability
  valid      : BytecodeValid S.program
  faithful   : S.Faithful            -- honest image ⟹ machine decision = verifier decision
  sound      : S.Sound               -- NO image makes the machine complete on a rejected input
  cycles     : S.CyclesAtMost c
```

- **`Faithful`** is the direct counterpart of `Implements`: under the shared cached oracle, the
  submitted `prover`'s image drives the run to the sentinel exactly when `scheme.verify`
  accepts, both directions, on every raw input. Without it a bytecode no image can run to
  completion satisfies every other clause.
- **`Sound`** is the clause this track exists for. It quantifies over every admissible `κ` and
  every image — not the submitted prover's — and says no execution completes on an input
  `scheme.verify` rejects. An under-constrained program has a second image that completes on a
  bad signature and fails here.
- **`CyclesAtMost`** quantifies over every image and every step count too, so `prover` and
  `steps` are witnesses only and cannot lower the score.

`cyclesAtMost_of_no_completion` and `sound_of_never_completes` in `check-leanisa.lean` are
machine-checked statements of what each clause does *not* say on its own: both are vacuous on a
bytecode nothing completes. `Submission.boundaryCycles_le` is the converse, and is what makes
"`Faithful` is the clause that makes them bite" a theorem rather than a remark — given a
submission whose honest run completes on some input along some coherent oracle path, the claim
is at least the public-boundary surcharge. The step between the two oracle semantics is
`mem_support_of_mem_support_run`: simulating a computation only shrinks its support, so a path
of the cached `probTrue` world is a path of the uncached `support` world. VCVio has that one
(`OracleComp.support_simulateQ_run'_subset`); it is the easy direction, and the hard one is
§8's cache weakening.

### Why the cost model cannot be gamed

The cost function is contract-side. `weight`, `runCost`, `loadInput`, `boundaryCycles`,
`BytecodeValid`, the three clauses and the stub are all hash-pinned in
`verifier/protected.sha256`; `verify.py` checks the pin *before* anything compiles, copies the
trusted tree and overlays only the submission root, and the claim integer comes from `claim.txt`
and is substituted into the stub, after which the comparator requires the submitted declarations
to match the rendered statements exactly.

## 3. The machine

The semantics are `leanerVM` at
[`8563b05b`](https://github.com/Verified-zkEVM/leanerVM/tree/8563b05b03434851badc19715f6162fb70ffc093),
taken as a Lake dependency. Reused unchanged: `K`, `E`, `g`, `gpow`, `IsInK`, `IsCanonical128`,
`Instr`, `DerefMode`, `Opcode`, `Program`, `Program.fetch`, `MemImage`, `MemImage.read`, `Regs`,
`Regs.next`, `Regs.initial`, `Program.finalPc`, and the instance caps. (`runCost` inlines
`Regs.final`'s condition rather than using it, so that the arrival test is visible at the
recursion's base case.)

Exactly two things change.

**`BLAKE2S` is the competition's oracle.** `leanerVM` implements the concrete RFC 7693
compression. That cannot be used here, because `Scheme.Secure` is a random-oracle statement and
is unprovable against a fixed hash function. `LeanIsa.execute`'s `BLAKE2S` arm reads the same
nine cells in the same order, queries the one shared oracle on the exact 896 bits the
instruction consumes — the 256-bit chaining pair, the 512-bit message block, the 128-bit
metadata cell, in that order — and asserts the committed output pair against the 256-bit answer.
The six canonicality conditions on the nine cells are unchanged.

**Nothing else.** The other five arms are a catch-all that *calls*
`LeanerVM.Semantics.execute`, so they cannot drift from the pin by construction;
`execute_eq_leanerVM` records the fact and breaks if the arm is ever specialised.

## 4. Cost model

One cycle per executed instruction, as for each ordinary RISC-V instruction, except `BLAKE2S`
at ten. The score is therefore the executed-instruction count plus nine per `BLAKE2S`, plus the
public-boundary surcharge of §5.

| | `XOR` | `MUL_NATIVE` | `SET_CONSTANT` | `DEREF` | `JUMP` | `BLAKE2S` |
|---|---:|---:|---:|---:|---:|---:|
| **cycles** | 1 | 1 | 1 | 1 | 1 | 10 |

Ten prices the Flock BLAKE2s R1CS over a Boolean witness, which no bus-flush count sees. It is
the maintainers' standing choice pending a measured Flock cost, and repricing it is a
one-constant change to `weight`.

**Two weightings were considered and not adopted.** Counting bus flushes and constraints from
§5.1 and §7 of the specification — two for the state, two for the bytecode read, two per memory
read, plus constraints, with `BLAKE2S` doubled for its Flock cost — gives:

| | `XOR` | `MUL_NATIVE` | `SET_CONSTANT` | `DEREF` | `JUMP` | `BLAKE2S` |
|---|---:|---:|---:|---:|---:|---:|
| Flushes | 10 | 10 | 6 | 10 | 10 | 22 |
| Constraints | 0 | 0 | 0 | 0 | 2 | 0 |
| Weight | 10 | 10 | 6 | 10 | 12 | 44 |

That prices the row's bus traffic but not the R1CS that dominates it, and it makes the totals
incomparable with RISC-V's flat per-instruction cycle. Charging `blockCost` of the 896-bit
query, as `Riscv` charges `HASH`, gives 2, which prices the message bits and nothing else.

**The block boundaries line up; the prices do not.** One `BLAKE2S` consumes exactly one 512-bit
message block, and RISC-V's `HASH` costs `max(1, ⌈bits/512⌉)`, so the two ISAs need the same
*number* of hash steps for the same work: a 5440-bit hash is 11 chained `BLAKE2S`, or one
11-cycle RISC-V `HASH`. At weight 10, leanISA charges 110 where RISC-V charges 11. Cross-track
totals are therefore not directly comparable; the comparable and interesting number is the
non-hashing instruction count.

**The two tracks' schemes are also different objects.** A RISC-V submission's `Scheme` may query
the oracle once on a long string; a leanISA submission's must query it in 896-bit
Merkle–Damgård steps. Those queries cost `blockCost 896 = 2` in the shared compression metric,
so the same construction scores 2× per hash on `upper-compressions`. That is a true reading of
leanISA's 384 bits of chaining and metadata overhead per call, not an artifact.

## 5. The public boundary and its 120-cycle surcharge

leanVM pins exactly **two** memory cells: its public input is 256 bits
(`LeanerVM.Semantics.HasPublicBoundary`). This competition's statement is 6,016 bits — a 128-bit
public key, a 256-bit message, a 128-bit capped signature length and 5,504 signature bits — so a
real leanISA verifier cannot be handed it as trusted memory. It would receive a digest and
re-derive it from prover-committed cells, one `BLAKE2S` per 512-bit block, before trusting a
single bit.

The contract **idealises the boundary and prices the idealisation.** `loadInput` pins the
statement into the lowest `inputCells = 47` cells, and `CyclesAtMost` adds
`boundaryCycles = statementBlocks * weight .blake2s = 12 * 10 = 120` to every claim.

The reason is not convenience. Routing the statement through a 256-bit digest makes soundness a
*cryptographic* statement: two statements collide under some oracle assignment, the machine
cannot tell them apart because the digest is all it sees, and so "the machine never completes on
a rejected input" is false on that assignment. `Sound` is a `probTrue … = 0`, which quantifies
over assignments rather than over probability, so it would be **unsatisfiable for every
program**. Idealising the boundary keeps soundness finite and dischargeable.

120 is a deliberately generous floor: it counts compressions and nothing else — not the twelve
`SET_CONSTANT` the per-block metadata needs, not the addressing — so a faithful accounting is at
least 132. It is the same for every submission, so it never reorders records. What it changes is
that the boundary cost leanVM really has is charged rather than hidden.

**It does not make the two tracks' totals comparable**, and nothing here should be read as
saying so. §4 already gives the reason: one `BLAKE2S` covers the same 512-bit block as one cycle
of RISC-V's `HASH` and costs ten, so the hash component of a leanISA total is about ten times
the RISC-V one, which no constant absorbs. The leaderboard and the rules state the surcharge so
a reader knows it is there; the quantity that *is* comparable across the two tracks is the
non-hashing instruction count.

What is *not* idealised is the hint soundness this track exists to test: every cell above
`inputCells` is still the prover's, and `Sound` still has to defend against all of them.

## 6. Model boundaries

These are the deliverables for the leanISA team, and they are boundaries of the track, not bugs.

1. **`run` versus the arithmetization.** The track's semantics is `LeanerVM.Semantics.run`, which
   tests the sentinel counter *before* each fetch and so never executes the sentinel slot. A
   bus-balanced assignment could. `BytecodeValid` forecloses the specific case — no `JUMP` in the
   sentinel slot, `JUMP` being the only instruction that can move `pc` anywhere but `g · pc` —
   but the general gap is a trusted boundary. The theorem that would consume the hypothesis
   (`WellFormedBytecode`, `no_row_at_sentinel`, `exists_run_of_balanced`) appears in `leanerVM`
   only inside the doc-comment of the blocked Layer 9.
2. **Closed walks.** Proposition 6.1 lets a balanced bus contain closed walks beyond the one
   walk from `pc_initial` to `pc_final`. `run` admits only the walk.
3. **Bytecode size is load-bearing, not hygiene.** `Program.code` is a *function*
   `Fin (2 ^ κ_bc) → Instr`, not a list, so `κ_bc ≤ 32` alone would let a submission commit a
   four-billion-slot bytecode for free and read it in constant time: a `JUMP` to a prover-chosen
   slot, a `DEREF` in `pc` mode tying the landing slot to an input-derived value, and a
   `SET_CONSTANT` there yields the entry. Digit extraction, checksums and chain-length selection
   could all be tabulated for a handful of cycles and the score would measure only the hashes.
   `maxProgramLogSize = 18` caps the bytecode at 262,144 instructions, matching
   `Riscv.Image.Valid`'s instruction cap. The budgets are not otherwise equal and the difference
   favours leanISA: a RISC-V image carries about 2 MiB of free constants between its 32-bit
   instructions and its 1 MiB data section, while `2 ^ 18` leanISA slots each carry a 192-bit
   immediate — about 6 MiB.
4. **Idealised hash.** `BLAKE2S` is the random oracle here, not RFC 7693 BLAKE2s. This is the
   same idealisation as `upper-riscv`'s `HASH`.
5. **Seed and finalize are invisible to per-opcode weights — so they are bounded separately.**
   No weighting can see the two flushes per memory cell over all `2 ^ κ_mem` cells, or per
   bytecode slot over all `2 ^ κ_bc`; the phases pay for every row whether or not the execution
   touches it. A submission therefore exports a second theorem,
   `seeded_rows : submission.seededRows < LeanIsa.maxSeededRows`, bounding
   `2 ^ κ_bc + 2 ^ κ_mem` by 1,048,576 — the same number `Riscv.Image.byteSize` is capped at.
   Without it a submission could announce `κ_mem = 32`, imposing eight billion flushes, and
   still show a three-digit cycle score. §7 gives the mechanism.

   A cap cannot make seeding cheap, and the guide should not pretend otherwise: at the
   *minimum* memory size the two phases already flush `2 · (2 ^ 16 + 2 ^ κ_bc)` times, which at
   roughly ten flushes per cycle dwarfs a three-digit score. The cycle count is the cost of the
   execution, not of the instance. What the bound does is stop the part the score cannot see
   from growing without limit.
6. **`CyclesAtMost` is a `support` statement, and `support` has no cache.** Each query
   independently ranges over all answers, so the bound must hold on incoherent paths where the
   `BLAKE2S` rows constrain nothing. A submitter must plan for the consequence: **the cycle count
   may not depend on hash binding.** Jump targets and loop lengths have to be pinned by the
   non-`BLAKE2S` constraints. Bytecode size is no help, because `JUMP` reads its destination from
   a memory cell, so `2 ^ κ_bc` bounds the number of distinct slots and not the run length. Any
   loop that advances `fp` into fresh frames and exits on an unpinned cell has completing runs of
   every length and fails this clause.
7. **There is no cost on rejection**, because rejecting runs do not exist. The score is the
   worst case of an *accepted* verification — the right metric for a SNARK, where you pay only
   when you produce a proof, and a real difference from `upper-riscv`'s "every execution,
   accepting or rejecting".

## 7. Writing a submission

A root exports three declarations, and the comparator checks all three the same way — exact
statement comparison against the rendered stub, the axiom audit, and kernel replay:

```lean
noncomputable def OptimalOTS.Challenge.UpperLeanIsa.submission : LeanIsa.Submission := ...
theorem OptimalOTS.Challenge.UpperLeanIsa.certificate : submission.Certificate <claim> := ...
theorem OptimalOTS.Challenge.UpperLeanIsa.seeded_rows :
  submission.seededRows < LeanIsa.maxSeededRows := ...
```

`seeded_rows` is the leanISA counterpart of `upper-riscv`'s `image_size`. The instance size is
*proved*, not measured: nothing has to run to establish it, the bound is a requirement rather
than an annotation, and it applies from the track's first submission rather than from the day a
collector is built.


Header imports admitted in a `UpperLeanIsa` root, beyond `Mathlib` and `VCVio` modules and
siblings of the same root: `OptimalOTS.Model`, `OptimalOTS.Dag`, `OptimalOTS.OracleAlgorithm`,
`OptimalOTS.LeanIsaMachine`, `OptimalOTS.LeanIsa`, and these nine `leanerVM` modules:

```
LeanerVM.Parameters.Field       LeanerVM.Semantics.Memory
LeanerVM.Parameters.Generator   LeanerVM.Semantics.Instruction
LeanerVM.Parameters.Isa         LeanerVM.Semantics.Blake2s
LeanerVM.Parameters.Blake2s     LeanerVM.Semantics.Step
                                LeanerVM.Semantics.Execution
```

They are listed one by one rather than as a `LeanerVM` prefix on purpose:
`LeanerVM.Arithmetization.*` reaches `Clean`, which carries a sorried
`Fact (Nat.Prime BN254_PRIME)` instance. A sorried *instance* is the worst shape, because
typeclass synthesis can pick it up with no syntactic trace in a submitter's proof, leaving only
the comparator's axiom audit between it and a record. The transitive import closure of the nine
modules above was computed and reaches only Mathlib, CompPoly and the standard tooling
(`Lean`, `Std`, `Batteries`, `Aesop`, `Qq`, `Plausible`, `ProofWidgets`, `ImportGraph`,
`LeanSearchClient`) — no `Clean`, no `Arklib`. CompPoly itself contains no `sorry` and no
`native_decide`.

**Expect everything to be noncomputable.** `gLog?` is `Classical.choose`-based, so no run
reduces in the kernel. Unlike `check-riscv.lean`, a leanISA proof cannot `decide` an execution:
address memory as `gpow i`, and go through `Program.fetch_gpow` and `MemImage.read_gpow`.
`LeanerVM.Semantics.run_succ_of_ne`, `run_intermediate` and `run_prefix` are the tools for
peeling a run one step at a time. `LeanerVM.run_intermediate` also proves the step count is
canonically the first arrival at the sentinel, so `steps` is the entirety of the extra witness
data, exactly as in `LeanerVM.Trace`.

Check locally from a submissions checkout:

```sh
python3 .contract/verifier/verify.py upper-leanisa --source .
```

## 8. Soundness against an adaptive prover

`Sound` quantifies the committed image and the step count plainly. A prover that queries the
oracle *before* committing — the realistic one, since the image holds hash outputs — is no
stronger, and `check-leanisa.lean` proves it rather than asserting it:

```lean
theorem Submission.sound_adaptive (S : Submission) (sound : S.Sound)
    (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ)
    (hlo : minLogMem ≤ κ) (hhi : κ ≤ maxLogMem)
    (P : OracleComp Spec (MemImage κ × ℕ)) :
    probTrue (do
      let (L, n) ← P
      let outcome ← S.exec L n pk m σ
      let accepted ← S.scheme.verify pk m σ
      pure (outcome.isSome && !accepted)) = 0
```

A winning path of the adaptive experiment runs `P` from the empty cache to some `(L, n)` and
some cache `c`, then runs the machine and the verifier from `c`. The ingredient is **cache
weakening**: a path from a populated cache is also a path from a smaller one, because the
lazily-sampled oracle is free to sample exactly the entries the larger cache already held. That
restricts the tail to a path from `∅`, which `Sound` at that very `(L, n)` forbids.

Two findings worth passing upstream to VCVio:

- VCVio ships only the **forward** direction, `OracleComp.simulateQ_cachingOracle_cache_le`
  (the cache only grows). The antitone direction is proved here by induction on the free monad
  (`OracleComp.inductionOn`, cases `pure` and `query_bind`), on top of `randomOracle.run_eq`.
- `OracleSpec.QueryCache` is a reducible `def` for a Pi type, so `≤` on it is ambiguous between
  VCVio's `QueryCache.instPartialOrder` and Mathlib's pointwise `Pi`/`Option` order, and
  elaboration picks the Pi one. The proof spells the subcache relation out rather than writing
  `≤`. Anyone reaching for `QueryCache.le_def` in a fresh context can silently get the wrong
  instance.

A consequence worth noting: the proof never uses that `P`'s output is reachable, so the theorem
holds for *every* `P`, with no query-bound or `NeverFail` hypothesis.

## 9. Open items

- Repricing `BLAKE2S` against a measured Flock cost, and the matching open question for RISC-V's
  `HASH` in `NEXT_COMPTETION.md`.
- Layer 9 of `leanerVM`, which would let boundaries 1 and 2 be discharged rather than trusted.
- Displaying `κ_bc` and `κ_mem` on the leaderboard. `seeded_rows` makes them a *bounded and
  proved* quantity, which is the part that matters for cost accounting; showing the exact
  figures beside the score is a presentation improvement on top, and needs the number to reach
  the service — either by a measurement pass or by rendering it into the statement the way
  `claim.txt` is rendered.
