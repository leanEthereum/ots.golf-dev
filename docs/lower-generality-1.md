# Whole-word DAGs: whole-word DAGs

Whole-word DAGs is `LowerBoundGenerality1 c`, defined in
`formal/OptimalOTS/WholeWords.lean`. It replaces the partial-disclosure class. There are three
upper tracks, all for generic algorithms: compressions, RISC-V cycles and leanISA cycles.

## Exact restriction

Secret sources are independent uniform 128-bit words. Hashing returns 256 bits. Each deterministic
node is a fixed public 128-bit word (a node without parents), selects a fixed low or high 128-bit
half directly from a hash output, or concatenates an ordered list of complete earlier values. Concatenations may repeat, reorder, group or be empty.

Every node carries a sequence of whole words; a signature discloses complete node values. All
original DAG cut, root reconstruction, nonce/index, size and resource requirements remain:
5376 payload bits plus a 128-bit nonce, 128-bit public key, 2^20 key-generation compressions,
2^20 signing trials, 2^115 accepted indices out of 2^128, and 127-bit strong unforgeability.
Hashes accept any number of words. One shared random oracle answers equal inputs equally; each
hash call costs at least one compression and one per started 512-bit input block.

The permitted syntax and existing payload size imply the origin bound proved below.

## Proof on paper

An origin is the first hash reached while tracing a value backwards through deterministic nodes.
A secret source or a constant word has no origins. A 256-bit hash has one origin; either 128-bit half has that same
origin. Concatenation unions origins and adds bit lengths. By induction along the graph,
128 times a value's number of distinct origins is at most its length. Taking the union across
all disclosed values preserves this inequality. The 5376-bit payload therefore has at most
42 origins, including when values are repeated or both halves of the same hash are disclosed.

Suppose all verifications cost at most 89. The index costs one, leaving at most 88 reconstruction
compressions and 87 nonroot hash nodes in a reconstruction pattern. For two different patterns,
the greatest hash in their difference is an origin of the other payload. Splitting the family
at its greatest hash and applying Pascal's recurrence bounds the number of patterns by
K = choose(87+42,42) = 16797745103346487549257982137883200.

Group M=2^115 indices by equal reconstruction pattern. A signature for one index can be
converted into a signature for another index in its class. With T=2^122 nonce trials, a class
of size k has search success at least k/(64+k). The exact signing law and Cauchy–Schwarz give
weighted success at least (256/257) M/(64K+M). Both randomly chosen messages are fresh with
probability at least 99/100; the second also differs from the signed message. Thus success is
at least (99/100)^2 (256/257) M/(64K+M), approximately 0.036318793987.

The entire experiment costs at most B=2^20+2^20+2^122+2*88+2. Its security allowance B/2^127
is just above 0.03125. The Lean proof rounds the weighted success down to 1/28 and obtains
success at least 9801/280000, still strictly greater than B/2^127. This contradicts weak
security and proves that some index costs at least **90 compressions**.

The argument permits all oracle-input collisions, both usable halves, and arbitrarily long
concatenations. Longer hash inputs only increase charged cost. The same fixed attack estimate
fails at 91. The optimal bound remains open.

## Certificate and checks

```lean
OptimalOTS.Challenge.LowerGenerality1.candidate :
  LowerBoundGenerality1 90
```

The proof is the reference proof's `LowerGenerality1` submission root.
`WholeWordOrigins.lean` derives the origin bound. `DisclosurePatterns.lean` and
`OrderedCounting.lean` prove the combinatorial bound. The `Averaged*` modules establish the
exact attack probabilities and cost contradiction. `Solution.lean` assembles the theorem and
checks that its only axioms are `propext`, `Classical.choice`, and `Quot.sound`.

Exact numerical check: `python3 tools/tune_lower_bound.py --method words --claims 90,91`.
Official pipeline, from the core with a submissions checkout:
`python3 verifier/verify.py lower-generality-1 --source ../ots.golf-submissions`.

Constant words matter for the class to be non-empty: without them no hash input can carry a
domain-separation tweak, and a revealed value hashed alone admits cheap second preimages. With
them, the 106-cost forest uses 128-bit tweak words in place of its 16-bit tweaks; the
internal Whole-word DAGs witness (`formal/Witnesses/Generality1/`, checked with `lake build Witnesses`)
proves such a scheme secure.
