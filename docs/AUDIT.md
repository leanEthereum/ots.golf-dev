# Audit of the bare-oracle contract

Scope: the pinned whole-word lower-bound and oracle-algorithm upper-bound contracts, the
RISC-V and leanISA machines, and their shared oracle and cost semantics. The internal whole-word witness
(`formal/Witnesses/Generality1/`) checks that the lower class is non-empty. Reference proofs live
in the submissions repository; current scores are on [ots.golf](https://ots.golf).
Operational launch gates are in [the deployment guide](../service/deploy/README.md).

## What is trusted

| Component | Pinned at | Role |
|---|---|---|
| Lean 4 | `formal/lean-toolchain` (v4.33.1) | kernel checking every claim |
| Mathlib, VCVio and dependencies | `formal/lake-manifest.json` | definitions used by the statement |
| leanprover/comparator | `c0c5a52d` | statement matching, axiom checking, kernel replay |
| lean4export | `15f6055e` (v4.33.0) | export of declaration dependencies |
| landrun + systemd (Linux verifier) | `811cfff5` | build isolation |

Submission proofs are checked by the kernel. Their permitted axioms are only
`propext`, `Classical.choice` and `Quot.sound`.

The import policy checks explicit source headers in every submitted `.lean` file. It permits the
transitive dependencies of allowed modules and does not restrict module loads performed by Lean
metaprograms or certify proof provenance. The build can read the staged contract and warm cache;
passing the header check is not evidence of runtime module isolation. Inspecting candidate
`.olean` import lists would not establish that isolation either: metaprograms can load a separate
environment, and compiled artifacts are candidate-controlled. The independent comparator checks
exported proof terms against the protected statement, allowed axioms and Lean kernel.

## Contract semantics

`CostAtMost` uses VCVio's `IsQueryBound`: a pure computation satisfies any budget;
a query is permitted when its cost is at most the remaining budget, and every
continuation must satisfy the remaining budget after subtraction. Thus the
budget covers every execution path, including branches with negligible
probability. Private uniform sampling is free.

The oracle implementation is `uniformSampleImpl.withCaching`. Its cache key is
`Query := Σ k, BitVec k`: the full length and bits, with no role or node label.
The first query to a string gets a uniform 256-bit answer; all later queries to
that string get the cached answer. Hash-node inputs can coincide with each other
or with message-and-nonce inputs. Such outputs are not independent uniform
record coordinates. No graph separation hypothesis is part of the contract.

| Contract feature | Lean declaration | Audit note |
|---|---|---|
| One random oracle on bit strings | `Query`, `hashSpec`, `oracleImpl` | length is part of a string's identity |
| Cost per started 512-bit block, at least one | `blockCost`, `queryCost` | every bit in an explicit tweak is charged |
| Sources, arbitrary deterministic nodes, hash nodes | `NodeKind`, `Graph` | hash nodes have one parent and no label |
| Root is a hash node | `Graph.root_isHash` | root is never disclosed |
| Key generation evaluates all nodes, within 2^20 compressions | `Graph.keygen`, `Scheme.keygen_le` | |
| Disclosure sets cut every source-to-root path | `root_not_mem`, `no_hidden_source` | |
| Reconstruction stops at disclosed values | `Graph.Visited`, `evaluated`, `reconstruct` | root is always evaluated |
| Verification cost is index plus reconstruction | `Scheme.verifyCost`, `idxCost` | the 384-bit index input costs one compression |
| Index is low 128 bits of `H(m ‖ η)` | `index`, `setWidth idxBits` | the same oracle handles node inputs |
| Signing samples distinct nonces, at most `2^20` trials | `Scheme.sign`, `signLoop` | fresh nonces need not be fresh oracle strings |
| Public key is low 128 bits of the root | `publicKey`, `Scheme.verify` | |
| Strong forgery differs from the received pair | `experiment`, `Scheme.Secure` | any accepted pair wins when signing fails |
| Security requires `Pr[Forge] < B/2^127` for every valid budget | `CostAtMost`, `Secure` | includes keygen, signing and final verification |
| Unconditional lower certificate | `LowerBoundGenerality1 90` | repeated reconstruction patterns and a forgery on a different message |

The weak experiment (forgery on a different message) is not part of the contract. The whole-word lower
root defines it in `WeakSecurity.lean` and proves that strong security implies weak security. The
lower certificate therefore applies to every secure whole-word scheme and also to schemes permitting
malleability of a signature on the signed message.

## Generic and whole-word contracts

`OracleAlgorithm.lean` supplies arbitrary terminating oracle programs, signatures as bit strings,
perfect correctness, deterministic verification (`Admissible.verifyDeterministic`), signing
availability, pathwise resource limits and oversized-signature rejection. Key generation and
signing may use private randomness; verification is deterministic.

The generic upper challenge fixes signing failure at most `2^-128` and requires separate proofs
of admissibility, strong security, and pathwise verification cost. Its forest certificate uses the
same programs and exact security experiment as the historical DAG construction. Correctness is
proved for every DAG adapter via cache consistency and reconstruction. Availability is proved for
the forest: its key-generation inputs have lengths 144, 400, or 784, so all distinct 384-bit signing
inputs are fresh. Failure is `(8191/8192)^(2^20) ≤ 2^-128`, for every message chosen as a
function of the public key. Its proofs form an independent `UpperCompressions` submission
root, for a 54-chain forest with six subtrees (104); the internal whole-word witness proves
the original 63-chain forest (106) separately. See [the proof map](upper-compressions.md).

`WholeWords.lean` restricts the existing DAG syntax: independent 128-bit sources, fixed public 128-bit
words, 256-bit hashes, fixed low/high output halves, and concatenation of earlier complete values. Repetition, reordering,
grouped values and empty inputs are allowed. The definitions fix this list of node operations.
Cuts disclose complete values. The 5,376-bit payload budget implies the 42-origin property.
The resulting certificate proves 90, using the same weak-security experiment.
The internal whole-word witness (`formal/Witnesses/Generality1/`) is a checked secure whole-word
construction at 106, so the class is non-empty.

`formal/scripts/check-axioms.lean` imports every protected model module, rejects declared axioms
throughout those modules, and audits the declarations (`contractDecls`) fixing the meaning of every
track statement. It supplements each submission's axiom guard and the official comparator; it
does not replace either.

## RISC-V contract

`RiscvMachine.lean` fixes the RV64IM subset, loader, memory layout, cycle costs and the two system
calls (HALT, and HASH on the shared oracle); `Riscv.lean` defines `Submission.Certificate`. A
certificate proves Upper bound admissibility and strong security of the OTS, exact refinement of
its Lean verifier by the machine's oracle computation on every raw input (no trap or fuel
exhaustion), and a cycle bound on every execution, accepting or rejecting.
`formal/scripts/check-riscv.lean` holds kernel-checked boundary tests of the machine. See
[the track notes](upper-riscv.md).

## leanISA contract

`LeanIsaMachine.lean` fixes the cycle weights, the loader, the bytecode caps and the one changed
instruction; `LeanIsa.lean` defines `Submission.Certificate`. The ISA semantics are `leanerVM` at
`8563b05b`, taken as a Lake dependency and reused unchanged except for `BLAKE2S`, which queries
the shared oracle on the exact 896 bits it consumes in place of the concrete RFC 7693
compression — the same idealisation `upper-riscv` makes for `HASH`, and necessary because
`Scheme.Secure` is a random-oracle statement. The other five opcodes are a catch-all arm that
calls `LeanerVM.Semantics.execute`, so they cannot drift from the pin;
`LeanIsa.execute_eq_leanerVM` records this.

leanVM's memory is committed by an untrusted prover and no instruction writes, so the machine has
no accept/reject output and `Riscv.Submission.Implements` has no counterpart. A certificate
instead proves `Faithful` (the honest prover's image reproduces the verifier's decision, both
directions, under the shared cached oracle) and `Sound` (no committed image at any admissible
`κ ∈ [16, 32]` completes on an input the verifier rejects), alongside admissibility, strong
security, `BytecodeValid` and the cycle bound.

Trusted boundaries specific to this track, in full in [the track notes](upper-leanisa.md):

- The semantics is `LeanerVM.Semantics.run`, which tests the sentinel before each fetch. A
  bus-balanced assignment of the arithmetization may contain closed walks `run` does not admit
  (§6.1, Proposition 6.1). `BytecodeValid` forecloses the one case that could execute the halt
  slot; the general gap is trusted, because the theorem that would consume the hypothesis exists
  in `leanerVM` only inside a doc-comment of the blocked Layer 9.
- `maxProgramLogSize = 18` is load-bearing, not hygiene: `Program.code` is a function, so
  `κ_bc ≤ 32` alone would admit a free constant-time lookup table and the score would measure
  only the hashes.
- The public boundary is idealised: `loadInput` pins the 6016-bit statement into 47 cells,
  where leanVM pins 256 bits. Routing it through a digest would make `Sound` unsatisfiable for
  every program, since a `probTrue … = 0` quantifies over oracle assignments and two statements
  collide on some assignment. `CyclesAtMost` charges `boundaryCycles = 120` for the difference.
- `CyclesAtMost` is a `support` statement and `support` has no cache, so the bound must hold on
  incoherent answer paths. The cycle count therefore may not depend on hash binding.
- Nine `leanerVM` modules are admitted as *exact* imports rather than a `LeanerVM` prefix:
  `LeanerVM.Arithmetization.*` reaches `Clean`, which carries a sorried
  `Fact (Nat.Prime BN254_PRIME)` instance that typeclass synthesis could pick up with no
  syntactic trace. The nine admitted modules reach only Mathlib and CompPoly.

A submission also exports `seeded_rows : submission.seededRows < LeanIsa.maxSeededRows`,
bounding `2 ^ κ_bc + 2 ^ κ_mem` by 1,048,576. This is the leanISA counterpart of `upper-riscv`'s
`image_size` and is enforced the same way, by the comparator rather than by a measurement: the
seed and finalize phases flush twice per bytecode slot and twice per memory cell over the whole
table, which no per-opcode weight reflects, so an unbounded announced memory would be an
unbounded prover cost invisible to the score. Proving rather than measuring also keeps the
trusted surface unchanged — no measurement program, sandbox budget or historical catalog.

`formal/scripts/check-leanisa.lean` holds kernel-checked boundary tests of the weights, the
boundary arithmetic, the bytecode caps and the loop, and the derived facts
`probTrue_eq_zero_iff`, `Submission.cyclesAtMost_of_no_completion`,
`Submission.sound_of_never_completes`, `Submission.sound_adaptive` (soundness against an
oracle-adaptive prover, via a cache-weakening lemma proved there because VCVio ships only the
forward direction), `mem_support_of_mem_support_run` and `Submission.boundaryCycles_le` (the
converse: on a submission whose honest run completes, the claim really is bounded below). Unlike `check-riscv.lean` it cannot execute a program:
`gLog?` is `Classical.choose`-based, so no run reduces in the kernel.

## Whole-word lower-bound proof

The 90-compression reference proof uses at most 42 disclosed hash origins. If every verification
cost at most 89, it would have at most 87 non-root hashes, giving at most `Nat.choose 129 42`
reconstruction patterns. The averaged signature-conversion attack then contradicts security.
The argument includes the key-generation and signing budgets and accounts for shared oracle
inputs. See [the proof guide](lower-generality-1.md).

## Model details retained

- The graph need not have a unique sink, and nodes need not reach the root.
  Verification follows the root's dependencies; other nodes still consume
  key-generation or disclosure budgets.
- An empty hash input costs one compression.
- `sampleAssignment` samples values for all nodes, but only source samples are
  used. Sampling is free.
- Index and public-key truncation use the low bits, matching `setWidth`.
- The adversary's other computation and private randomness are unbounded and free.
- The internal 106-compression whole-word witness establishes non-vacuity of the lower-bound
  class under strong (and hence weak) security. The separate 104-compression generic upper
  certificate also proves admissibility, including correctness and signing availability.

## Contract changes and verification

Protected files are pinned by `verifier/protected.sha256`. Changes to protected model definitions or track metadata require re-pinning and official
verification of all affected certificates. The service audit does not alter any of these models or
claims. Local checks do not constitute deployment or a public leaderboard promotion.
