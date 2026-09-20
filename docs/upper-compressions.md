# Upper bound: arbitrary oracle algorithms

The `upper-compressions` track admits arbitrary oracle algorithms with perfect correctness,
signing failure at most `2⁻¹²⁸`, 127-bit strong unforgeability, and the fixed size and resource
limits. Its forest construction verifies within **104 compressions** on every input and
oracle-answer path. All proofs form the reference proof's `UpperCompressions` submission root, in the
submissions repository; file names below are relative to it.

The lower-bound track covers whole-word DAGs.

## What the challenge requires

A submission chooses an `OracleAlgorithm.Scheme`: a secret-key type and three terminating
oracle programs for key generation, signing, and verification. Signatures are bit strings. Computation is free. Key generation and signing may use private
randomness; verification is deterministic. All programs share the same bare random oracle and
compression-cost model.

`OptimalOTS.Challenge.UpperCompressions` exports exactly:

```lean
noncomputable def scheme : OracleAlgorithm.Scheme

theorem admissible : scheme.Admissible

theorem secure : scheme.Secure

theorem cost : scheme.VerifyCostAtMost 104
```

The challenge substitutes a submission's claim for 104. `Admissible` requires:

- Perfect correctness: whenever honest signing returns a signature, verification accepts with
  probability one.
- Deterministic verification: the verifier uses no private randomness on any input.
- Signing failure at most `2⁻¹²⁸`, averaged over honest key generation and signing, for every
  message chosen as a function of the public key, starting from a fresh oracle.
- Signatures of at most 5,504 bits, and rejection of longer bit strings.
- At most 1,048,576 key-generation compressions and `2²⁰` signing compressions on every path.

Public keys are 128 bits and messages are 256 bits. The separate security theorem gives
strict strong-unforgeability probability below `B / 2¹²⁷` for every pathwise budget `B` of the
entire attack experiment, including honest operations and final verification. The verification
cost theorem covers all inputs, including malformed signatures and rejecting paths.

Both algorithm challenges fix signing failure at most `2^-128`. The upper construction lies
within the class covered by the generic lower bound.

## Correctness proof

The proof establishes correctness for **every DAG adapter**.

Key generation leaves an assignment satisfying every deterministic-node equation and a shared
cache containing every hash-node answer. This holds even when hash inputs coincide. Successful
signing returns the encoding of one disclosure cut and records its index query in that cache.
Subsequent operations only extend the cache, so verification repeats the same index and selects
the same cut.

Decoding recovers every disclosed value. A topological induction over visited nodes recovers
the original assignment: the cut contains every visited source, deterministic nodes obey the
same equations, and hash nodes receive the recorded answers. The reconstructed public key
therefore equals the generated key. This is a statement about every supported execution, so
it also proves probability-zero rejection for every public-key-dependent message choice.

## Signing availability proof

The forest's key-generation queries have lengths 144, 400, or 784 bits. Every 384-bit
message-and-nonce query is therefore fresh after key generation.

Signing samples distinct 128-bit nonces. Each resulting 384-bit index query is fresh, including
when the message depends on the public key. Its low 128 answer bits are uniform; `2¹¹⁵` of the
`2¹²⁸` possible indices are accepted. Every trial therefore fails with probability `8191/8192`.
After `2²⁰` trials, the failure probability is exactly

```text
(8191 / 8192)^(2^20).
```

The reciprocal Bernoulli inequality gives `(8191/8192)^8192 ≤ 1/2`. Since
`2²⁰ = 8192 × 128`, total failure is at most `2⁻¹²⁸`, exactly the challenge allowance. The Lean
proof certifies this bound. A separate exact-integer check confirms
`2 × 8191^8192 ≤ 8192^8192`.

## Security and resource preservation

`Adapter.lean` wraps the original DAG programs unchanged as a `TypedScheme` (`TypedScheme.lean`,
an internal interface of this root with a typed signature and an injective encoding). Translations
of adversaries in both directions establish equality of the typed and DAG oracle experiments
before oracle interpretation. All queries, costs and success probabilities agree exactly.

`WireAdapter.lean` transfers every requirement from the typed scheme to the contract's scheme on
bit strings: signing outputs the encoding, and verification parses its input. `Wire.lean`
instantiates it for the forest. The transmitted signature is the 128-bit nonce followed by at most
5,376 disclosed bits (42 values); every accepted bit string is the canonical encoding of its parse.

The forest has 54 chains of length 14, grouped three by three into 18 group digests, then three
by three into 6 subtree digests under a root of six (the paper's forest with six subtrees instead
of seven). Its explicit 16-bit tweaks are charged in the actual input lengths: 144, 400 and 784
bits, so the root costs two compressions. Its disclosure family takes three cut shapes of
reconstruction cost 103 with at most 42 revealed values: one subtree and two group digests
revealed (chain cost 83), six group digests (83), or one subtree and three group digests (84),
together 45,248,337,822,211,545,881,075,429,737,370,574 ≥ `2¹¹⁵` cuts. The copied security proof
establishes all internal construction properties before proving strong security. The
construction uses 782 key-generation compressions, at most `2²⁰` signing compressions, and at most
`1 + 103 = 104` verification compressions.

`Resources.lean` establishes the size, rejection, and pathwise cost bounds.
`KeygenSupport.lean` and `Correctness.lean` establish correctness. `Deterministic.lean` proves that
every DAG adapter's verifier makes only hash queries. `Availability.lean` establishes signing
availability. `ForestAlgorithm.lean` combines these results for the typed scheme, `Wire.lean`
moves them to bit strings, and `Solution.lean` exports the challenge declarations. The core's internal whole-word witness (`formal/Witnesses/Generality1/`)
proves the original 63-chain forest (106 compressions) as a DAG scheme, with the same proof
architecture, independently of these files.

## Verification

```sh
cd formal
lake build OptimalOTS
lake env lean scripts/check-axioms.lean
cd ..
python3 verifier/verify.py upper-compressions --source ../ots.golf-submissions
```

Comparator checks the four declarations and their shared scheme against the rendered challenge.
Permitted axioms are `propext`, `Classical.choice`, and `Quot.sound`.
