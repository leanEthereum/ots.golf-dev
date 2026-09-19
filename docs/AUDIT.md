# Audit of the bare-oracle contract

Scope: the pinned DAG, generic-algorithm, whole-word and RISC-V contracts, their oracle/cost
semantics, the internal lower-bound witnesses kept in this core (`formal/Witnesses/`), and the
reference proofs (submission roots kept in the submissions repository). The lower bounds are
generic **1**, unrestricted DAG **18**, and whole-word DAG **90**. Generic upper has a complete
**104** certificate, including perfect correctness, deterministic verification and signing failure
at most `2^-128`; RISC-V upper has a **702**-cycle certificate. Both witnesses are secure schemes
at **106**. This
document covers mathematical scope; operational launch gates are in
[the deployment guide](../service/deploy/README.md). The archived
[Lean statement review](archive/lean-statement-review.md) covers an earlier state of every
project-owned Lean file.

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
| Key generation evaluates all nodes, within 1024 compressions | `Graph.keygen`, `Scheme.keygen_le` | |
| Disclosure sets cut every source-to-root path | `root_not_mem`, `no_hidden_source` | |
| Reconstruction stops at disclosed values | `Graph.Visited`, `evaluated`, `reconstruct` | root is always evaluated |
| Verification cost is index plus reconstruction | `Scheme.verifyCost`, `idxCost` | the 384-bit index input costs one compression |
| Index is low 128 bits of `H(m ‖ η)` | `index`, `setWidth idxBits` | the same oracle handles node inputs |
| Signing samples distinct nonces, at most `2^20` trials | `Scheme.sign`, `signLoop` | fresh nonces need not be fresh oracle strings |
| Public key is low 128 bits of the root | `publicKey`, `Scheme.verify` | |
| Strong forgery differs from the received pair | `experiment`, `Scheme.Secure` | any accepted pair wins when signing fails |
| Security requires `Pr[Forge] < B/2^127` for every valid budget | `CostAtMost`, `Secure` | includes keygen, signing and final verification |
| Unconditional lower certificate | `LowerBoundGenerality2 18` | repeated reconstruction patterns and a forgery on a different message |

The weak experiment (forgery on a different message) is not part of the contract. Each DAG lower
root defines it in `WeakSecurity.lean` and proves that strong security implies weak security. The
lower certificate therefore applies to every secure scheme and also to schemes permitting
malleability of a signature on the signed message.

## Generic and whole-word contracts

`OracleAlgorithm.lean` supplies arbitrary terminating oracle programs, signatures as bit strings,
perfect correctness, deterministic verification (`Admissible.verifyDeterministic`), signing
availability, pathwise resource limits, oversized-signature rejection and the generic lower
statement. The fresh-message experiment used by the generic lower proof lives in its submission
root. Key generation and signing may use private randomness. Both algorithm challenges fix
signing failure at most `2^-128` for every public-key-dependent message choice, averaged over
honest key generation and signing from a fresh oracle. The verified lower bound of 1 specializes a proof covering every failure allowance at most one half.

The generic upper challenge fixes signing failure at most `2^-128` and requires separate proofs
of admissibility, strong security, and pathwise verification cost. Its forest certificate uses the
same programs and exact security experiment as the historical DAG construction. Correctness is
proved for every DAG adapter via cache consistency and reconstruction. Availability is proved for
the forest: its key-generation inputs have lengths 144, 400, or 784, so all distinct 384-bit signing
inputs are fresh. Failure is `(8191/8192)^(2^20) ≤ 2^-128`, for every message chosen as a
function of the public key. Its proofs form an independent `UpperCompressions` submission
root, for a 54-chain forest with six subtrees (104); the internal Generality 2/3 witness proves
the original 63-chain forest (106) separately. See [the proof map](upper-compressions.md).

`WholeWords.lean` restricts the existing DAG syntax: independent 128-bit sources, fixed public 128-bit
words, 256-bit hashes, fixed low/high output halves, and concatenation of earlier complete values. Repetition, reordering,
grouped values and empty inputs are allowed. The definitions fix this list of node operations.
Cuts disclose complete values. The 5,376-bit payload budget implies the 42-origin property.
The resulting certificate proves 90, using the same weak-security experiment.
The internal Generality 1/3 witness (`formal/Witnesses/Generality1/`) is a checked secure whole-word
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

## DAG certificate status and open proof work

The lower certificate proves 18 for every weakly secure scheme. Under the contrary
assumption that every verification costs at most 17, each reconstruction uses at
most 15 non-root hash nodes among at most 1023. There are fewer than `2^110`
possible such node sets. Most of the `2^115` indices therefore lie in classes of
at least eight indices with the same reconstruction pattern. A deterministic
candidate construction converts a valid signature to any index in its class.

The attack samples messages uniformly to avoid previously queried message-prefix
domains, then tests `2^122` distinct nonces for its new message. Its proven success
is at least `9/200`; its total cost is at most
`1024 + 2^20 + 2^122 + 34`, whose ratio to `2^127` is smaller than `9/200`.
This contradicts weak security. No assumption about distinct hash inputs or
independent node outputs is used. The elementary index-plus-root bound 2 remains
available as a separate lemma.

The upper certificate is 104. Its concrete scheme prepends a 16-bit tweak
to every node input; those bits are included in the charged input lengths (144,
400 and 784 bits). This is a choice made by that scheme, not a restriction on
schemes considered by the lower theorem.

The former lower bound 25 relied on distinct oracle labels. Two proposed
fresh-coordinate replacements fail in the bare model. An earlier hidden hash
can query the same string as a later reconstructed hash, placing the information
weight outside the reconstructed set; the corresponding construction bound can
also charge outside its target set. A Bell-number correction does not repair
these counterexamples. Details:

- [Information analysis](research/bare-oracle-information-analysis.md).
- [Construction analysis](research/bare-oracle-construction-analysis.md).
- [Conditional numerics](research/bare-oracle-numerics.md): the simple proposed-24 point has
  numerical slack, but its missing mathematical hypotheses prevent certification.
- [Final bare-oracle report](archive/bare-oracle-lower-report.md) and [proof map](lower-generality-2.md).

The repeated-pattern proof establishes 18. Bounds 19 through 25 remain open in
the bare model. In particular, the number of subsets of at most 16 non-root hash
nodes already exceeds `2^115`, so the same counting argument does not directly
prove 19. Conditional numerical searches do not establish a stronger bound.

## Model details retained

- The graph need not have a unique sink, and nodes need not reach the root.
  Verification follows the root's dependencies; other nodes still consume
  key-generation or disclosure budgets.
- An empty hash input costs one compression.
- `sampleAssignment` samples values for all nodes, but only source samples are
  used. Sampling is free.
- Index and public-key truncation use the low bits, matching `setWidth`.
- The adversary's other computation and private randomness are unbounded and free.
- The secure DAG upper certificate establishes non-vacuity of the DAG strong and weak security
  classes. Its generic adapter separately proves admissibility, including correctness and signing
  availability. No whole-word upper construction is claimed.

## Contract changes and verification

Protected files are pinned by `verifier/protected.sha256`. Changes to protected model definitions or track metadata require re-pinning and official
verification of all affected certificates. The service audit does not alter any of these models or
claims. Local checks do not constitute deployment or a public leaderboard promotion.
