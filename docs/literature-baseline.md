# Equal-chain comparison

The compression chart's dotted line is **105 compressions**: an adaptation of the
equal-chain, fixed-sum construction in [At the Top of the Hypercube — Better Size-Time
Tradeoffs for Hash-Based Signatures](https://eprint.iacr.org/2025/889), Construction 4
and Section 5. It retains **our existing nonce grinding and 2^115 accepted cuts**.
It is a calculated comparison, not a score quoted from the paper or a Lean-certified
submission. The paper's direct Top Single Layer encoding uses a different layer size.

Run `python3 tools/literature_chain_baseline.py` from the repository root to reproduce
the calculation with exact integers and the current model constants.

Use 42 independent chains, each with 24 hash steps (25 selectable values, including
the starting secret and final endpoint). Each value is 128 bits. Hash all endpoints
together into a single 128-bit public key. Queries include distinct 16-bit node tags,
as in the reference forest; chain hashes cost one compression and the final
5,392-bit root input costs eleven. No intermediate forest nodes are present.

The signature contains one value per chain and the 128-bit nonce: 5,504 bits.
Key generation costs `42 × 24 + 11 = 1,019` compressions. Store the chain values in
the secret key, so signing only pays for message-and-nonce queries.

Let `d` be the sum of the remaining steps to the endpoints. The number of possible
signatures at this depth is the coefficient of `x^d` in `(1 + x + … + x^24)^42`.
At depth 93 this is **51,428,176,517,966,118,854,752,443,891,758,710**, enough to select
2^115 distinct vectors in a fixed public order. Depth 92 is too small. Equal total
depth makes the selected vectors an antichain under forward hashing.

The low 128 bits of the message-and-nonce oracle output select a vector when below
2^115; otherwise the signer tries the next distinct nonce. This is the reference
encoding, with acceptance probability 1/8,192. Each block of 8,192 fresh trials
misses with probability at most 1/2; 128 blocks fit the 2^20 signing budget and
bound failure by 2^-128. Index inputs have a different length from all key-generation
queries. The script checks this arithmetic; it does not prove full unforgeability.

Verification costs **93 chain hashes + 11 root compressions + 1 index compression
= 105**. Invalid encodings can be rejected before reconstruction. The script searches
every chain count allowed by the signature budget and uses the longest chain allowed
by key generation for each count. Increasing length only adds vectors at any fixed
depth, so shorter chains cannot improve this cost. The minimum is for 42 chains.
This optimization is restricted to the specified equal-chain family and encoding.
