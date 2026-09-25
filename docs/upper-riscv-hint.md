# Hinted RISC-V verification track

The fourth upper track scores a proved upper bound on the cycles of **every accepting
execution** of an RV64IM verifier that reads a **prover-chosen view** of the signature instead
of the signature itself. It exists to give the RISC-V track the one thing a zkVM prover really
has and the deterministic track forbids: hints. A prover holds the signature and unlimited free
computation, and may hand the machine anything it derives from them — the signature laid out at
aligned addresses, the digits of the index already split out, jump targets, quotients — as long
as the machine *checks* what it is handed instead of trusting it. The machine is unchanged; what
changes is the third input and the two clauses that tie the machine to the specification.

This guide is written for zkVM engineers who know RISC-V at the level of "loads, stores,
branches and a hash syscall", know Winternitz-style one-time signatures, and are new to Lean and
to the ots.golf contract. Every object it names is introduced before it is used. It is also the
place where the two questions raised when the track was designed are answered precisely: what
happens to strong unforgeability when the machine is no longer a function of the signature
(§6), and how an untrusted expansion is kept from turning a bad signature into an accepted run,
or a good one into a rejected run (§5, `Sound` and `Faithful`).

## 1. What a submission is made of

ots.golf checks claims by replaying Lean proofs in the Lean kernel. A track fixes a *contract*:
hash-pinned Lean files the submitter may not edit, declaring the objects a submission must
produce and the theorem it must prove. A submission is a flat directory of `.lean` files plus a
`claim.txt`, exporting declarations whose statements must match the contract's rendered stub
exactly.

Five contract files matter here.

| File | What it holds |
|---|---|
| [`Model.lean`](../formal/OptimalOTS/Model.lean) | the shared constants and the one random oracle |
| [`OracleAlgorithm.lean`](../formal/OptimalOTS/OracleAlgorithm.lean) | `Scheme`, `Admissible`, `Secure` — the OTS layer, unchanged |
| [`RiscvMachine.lean`](../formal/OptimalOTS/RiscvMachine.lean) | the machine: image, loader, `HASH`, `HALT`, `execute` — unchanged |
| [`Riscv.lean`](../formal/OptimalOTS/Riscv.lean) | the deterministic track's `Submission`; importable here, for porting |
| [`RiscvHint.lean`](../formal/OptimalOTS/RiscvHint.lean) | the view loader, `Submission` and `Submission.Certificate` of this track |

Pins: `riscv-zkvm` at
[`4634e41b`](https://github.com/Verified-zkEVM/riscv-zkvm/tree/4634e41b229da4256e4a1f1688b94133fffa4af0)
for the RV64IM semantics, VCVio at `25f26bfe` for oracle computations, both unchanged from the
RISC-V track. The contract id is the hash of `verifier/protected.sha256`; `RiscvHint.lean`, its
stub and its comparator config are three new entries in it, and no existing protected file moved.

**The claim, in domain words.** A submission is a one-time signature scheme (a specification,
in the oracle-algorithm model), an RV64IM program, a pure map `compress` from views to
signatures, and the honest prover's map `expand` from signatures to views. The certificate says:
the scheme is a correct, budgeted, 127-bit strongly unforgeable OTS; the honest view of any
signature drives the program to exactly the verifier's decision; no view whatsoever drives it to
*accept* unless the verifier accepts the signature that view stands for; and every accepting
run, under every view, takes at most the claimed number of cycles. This is a specification of
intent; there is no external artifact it transcribes.

**Sits between.** Below it: the RISC-V track's machine and the OTS layer, consumed unchanged.
Above it: a submission root `formal/Submissions/UpperRiscvHint/`, and `check-riscv-hint.lean`,
which proves that every deterministic-track certificate is a hinted one.

### The oracle and its two semantics

There is exactly one random oracle, on bit strings of any length. `hash u` queries it and
returns 256 bits; equal strings always get equal answers; a scheme that wants a domain
separator pays for its bits. Every party's program is an `OracleComp Spec α`: a syntax tree of
"query the oracle on this string, then continue with the answer", with free uniform sampling
for the parties that may use randomness.

Two semantics are read off that tree, and this track, like the leanISA one, uses both.

- `support oa` is the set of values `oa` can produce **for some answers, with no cache**: each
  query independently ranges over all `2^256` answers, so the same query may return different
  answers at two points on one path.
- `probTrue oa` runs `oa` under a lazily sampled **cached** random oracle and takes the
  probability of `true`. Repeated queries agree, as they do in reality. `probTrue oa = 0` says
  the event happens on *no* coherent path, not merely with probability zero
  (`probTrue_eq_zero_iff` in `check-riscv-hint.lean`).

The deterministic RISC-V track needs only the first: its single equation equates two trees. This
track has to say "the machine and the verifier, run one after the other, see the same answers",
and only the cached semantics says that. §5 says which clause uses which.

## 2. Two ways to add hints, and the one taken

Two designs were on the table.

**A prover-chosen view in place of the signature.** The loader places a bit string chosen by
whoever runs the machine where the RISC-V track places the raw signature. The submitter says,
with a pure function `compress`, which signature a view stands for, and with an oracle
computation `expand`, which view an honest prover builds from a signature. Nothing about the
machine changes: same image type, same instruction prices, same `HASH` and `HALT`, same
`execute`. **This is the design taken.**

**A read-only hint region or a hint syscall.** The machine gains a second input stream the
program reads with loads or a system call, as SP1's `hint_read` or RISC Zero's `env::read` do.
It was not taken because it changes the machine: a new region or call has to be specified and
priced, the deterministic track's refinement equation would need a hint stream on its
right-hand side, and every theorem about `execute` would have to be redone. The view design
gets the same expressive power — a program is free to read the view as a hint stream, from any
offset it likes — for no change to `RiscvMachine.lean`.

Within the first design there is a further choice: whether the machine also receives the raw
signature, with the view as a separate "hints" input. It does not. If it did, `Sound` would have
to be stated against the raw signature, so a program that reads its data from the hint copy
would have to *bind* the two: compare 5,504 bits, about 86 doublewords, at two loads and a branch
each — roughly 250 cycles on a track whose record is 349. With a submitter-chosen `compress`
that copy *is* the signature, and the binding is free. "Signature plus hints" is the special
case `compress = fun view => view.take n` for a length prefix `n`; nothing is lost by admitting
the general map, and §6 shows nothing is gained by an adversary either.

## 3. Vocabulary

In dependency order. Objects from the RISC-V track are introduced as this track uses them; the
[RISC-V guide](upper-riscv.md) has the ABI in full.

**A bit string**, `List Bool`. Signatures, views and the raw third input of every loader are
lists of bits, least significant first. `OracleAlgorithm.Signature` is this type under another
name.

**A scheme**, `OracleAlgorithm.Scheme`. Three oracle programs — key generation, signing and
verification — with a private-key type. `verify pk m σ` is an oracle computation returning a
`Bool`. Nothing in this track changes it.

**Admissibility**, `Scheme.Admissible`. The checklist of `OracleAlgorithm.lean`: perfect
correctness, deterministic verification (no private randomness), signing failure at most
`2^-128`, signatures of at most `maxSignatureBits = 5504` bits and rejection of longer strings,
and `2^20` compressions each for key generation, signing and verification. Two of its fields
are used by the port theorem of §5: `verifyDeterministic` and `rejectsOversized`.

**Strong unforgeability**, `Scheme.Secure`. The one-signature experiment of
`OracleAlgorithm.lean`: the attacker sees the public key, chooses a message, receives its
signature, and wins by producing an accepted pair other than the one it was given. The
probability of winning is below `B / 2^127` for every budget `B` of the whole experiment.
Signatures are what the attacker outputs; this experiment never mentions views.

**The machine image**, `Riscv.Image`. A list of RV64IM instructions and a list of data bytes.
`Image.Valid` caps them at 262,144 instructions and 1,048,576 bytes and admits only the
instructions of the pinned subset. `Image.byteSize` is `4 · #instructions + #data`, the
quantity the separate `image_size` theorem bounds below 1 MiB.

**The machine state**, `RiscvZkvm.Rv64.MachineState` (riscv-zkvm). 32 registers, a
doubleword-addressed memory, a code map and a program counter. The loader builds one; `execute`
steps it.

**The deterministic loader**, `Riscv.initialState image pk m σ`. Code at `0x1000`, data at
`0x200000`, the 128-bit public key at `0x400000`, the 256-bit message at `0x400010`, the first
5,504 signature bits at `0x400030`, the stack pointer at `0x1000000`, and `a0..a3` pointing at
key, message, signature, and holding the signature's bit length capped at 5,505.

**A run**, `Riscv.execute n s : OracleComp Spec Outcome`. At most `n` instructions from state
`s`. The result, `Outcome = Option (Bool × ℕ)`, is `some (b, cycles)` when the program reached
`HALT` with decision `b` after `cycles` cycles, and `none` on a trap, an unadmitted instruction
or exhausted fuel. Each ordinary instruction and `HALT` costs one cycle; `HASH` costs
`max(1, ⌈bits / 512⌉)` and queries the oracle on its exact input. Given the oracle's answers the
run is a function of the state.

**A deterministic computation**, `Deterministic oa` (`Model.lean`). An oracle computation whose
every query, on every path, goes to the hash oracle and never to the sampler. Admissibility
requires it of `verify`; the port theorem needs it to replay a verification from a cache.

**A query cache**, `hashSpec.QueryCache` (VCVio). A partial map from query strings to 256-bit
answers, the state of the cached simulation. "Subcache" (`Subcache c₂ c₁`) means every entry of
`c₂` is an entry of `c₁`.

## 4. Index

```
formal/OptimalOTS/RiscvHint.lean
  [01] def    View, maxViewBits              a view is a bit string; the loader keeps 1,048,576 bits of it
  [02] def    loadView image pk m view       initialState with the view at 0x400030 and a3 = min(|view|, 1048577)
  [03] def    decision o                     the HALT bit of a completed run; none for a fault
  [04] struct Submission                     scheme, image, compress, expand, fuel
  [05] def    Submission.exec S n pk m view  n instructions from loadView
  [06] prop   Submission.Sound S             no view, no fuel: accept ⟹ verify (compress view), on every coherent path
  [07] prop   Submission.Expands S           compress (expand pk m σ) = σ on every path
  [08] prop   Submission.Faithful S          the honest view's run halts with verify's decision, on every coherent path
       supporting: Submission.honestRun (:146)
  [09] prop   Submission.CyclesAtMost S c    every accepting run, every view, every fuel: at most c cycles
  [10] struct Submission.Certificate S c     admissible, secure, valid, expands, faithful, sound, cycles
formal/OptimalOTS/Challenge/UpperRiscvHint.lean.in
  [11] def    submission, certificate, image_size   the three exports; the claim is substituted into certificate
formal/scripts/check-riscv-hint.lean               (not part of the contract; derived facts)
  [12] thm    Submission.sound_adaptive      a prover that hashes before choosing its view is no stronger
  [13] thm    Riscv.Submission.hinted_certificate   a RISC-V certificate is a hinted one with the identity view
       supporting: loadView_eq_initialState (:36), execute_fuel_agree (:375),
                   subcache_run_grow (:503), replay_deterministic (:523), Submission.hinted (:566)
       vacuity: cyclesAtMost_of_never_accepts (:78), sound_of_never_accepts (:86)
```

The contract module has 12 declarations and every one is load-bearing; none is excluded. The
check script has 33, of which 6 are examples that pin constants and 14 are supporting lemmas
named on the lines above; the remaining 13 are the cache-weakening and path-semantics scaffolding
of [12] and [13].

## 5. Close reading

### [01] `View`, `maxViewBits` — RiscvHint.lean:50, :57

Kind: a type abbreviation and a constant.
It says: a view is a bit string, and the loader keeps at most `maxViewBits = 1048576 = 2^20`
bits of it. The number is the one that caps the RISC-V image in bytes and the leanISA tables in
rows; here it is bits. It is generous: a claim of at most `limits.max_claim = 1,000,000` cycles
cannot read more than 8 MB of doublewords, and an OTS verifier's hints are a few kilobytes.
Check it yourself: `check-riscv-hint.lean` §1 pins the value and `maxSignatureBits <
maxViewBits`, so every admissible signature is itself an admissible view.

### [02] `loadView image pk m view` — RiscvHint.lean:66

Kind: a definition building the initial machine state.
Shape:
    loadView (image : Image) (pk : PublicKey) (m : Message) (view : View) : MachineState
It says: the RISC-V track's loader with the view in the signature's place. Code, data, public
key, message, stack pointer and `a0`, `a1`, `a2` are laid out identically; `a2` points at the
view at `0x400030`; `a3` holds `min(|view|, 1,048,577)`, so a truncated view is distinguishable
from every complete one, as an oversized signature is on the RISC-V track. A program that reads
beyond the view reads zeros. There is no raw signature anywhere in memory.
It rests on: `Riscv.initialState`'s layout and riscv-zkvm's `writeBytesAsWords`.
Check it yourself: `loadView_eq_initialState` (`check-riscv-hint.lean:36`) proves that on a view
of at most 5,504 bits the two loaders build the *same* state — the port theorem [13] depends on
it — and the example below it pins the length register of a truncated view at 1,048,577.

### [03] `decision o` — RiscvHint.lean:79

Kind: an accessor.
It says: the `HALT` bit of a completed run, `some true` or `some false`, and `none` for a trap,
an unadmitted instruction or exhausted fuel. The clauses below say "accepts" as `decision
outcome = some true` and "halts with the verifier's decision" as `decision outcome = some b`.

### [04] `Submission` — RiscvHint.lean:95

Kind: a data structure.
Shape:
    structure Submission where
      scheme   : OracleAlgorithm.Scheme
      image    : Image
      compress : View → Signature
      expand   : PublicKey → Message → Signature → OracleComp Spec View
      fuel     : PublicKey → Message → Signature → ℕ
It says: a scheme, a fixed image, and the two maps between views and signatures. `compress` is
pure and total: every bit string is a view and stands for some signature; it is the object
`Sound` verifies against, and `compress view` is what the 5,504-bit cap applies to. `expand` is
the honest prover; it may query the oracle because a useful view carries hash outputs (the
index digits are bits of `H(pk ‖ m ‖ nonce)`, which the prover has to compute to write them
down). `fuel` bounds the instructions of the honest run.
It rests on: nothing beyond the OTS layer and the image type.
Ask the author: `expand` carries no cost bound, and `compress` no structural constraint beyond
totality. §8 lists both as boundaries; neither affects security (§6) or the score (§7).

### [05] `Submission.exec S n pk m view` — RiscvHint.lean:108

Kind: a definition.
It says: `execute n (loadView S.image pk m view)` — the machine run on a view, with an explicit
fuel `n` rather than the submission's own, because `Sound` and `CyclesAtMost` quantify the fuel.

### [06] `Submission.Sound S` — RiscvHint.lean:127

Kind: a proposition on a submission.
Shape:
    ∀ pk m view n,
      probTrue (do
        let outcome  ← S.exec n pk m view
        let accepted ← S.scheme.verify pk m (S.compress view)
        pure (decide (decision outcome = some true) && !accepted)) = 0
It says: "for every public key, message, view and fuel, on **no** coherent oracle assignment
does the machine halt accepting while the verifier rejects the signature the view stands for."
The view and the fuel are quantified plainly — every bit string, every budget — not the honest
ones. The verifier runs *after* the machine under the same cache, so a hash output the view
carries and the machine re-queries is checked against the same answer the verifier will see. This forbids relying on unchecked hints when doing so could change acceptance under the
shared oracle. It does not require equality of query traces or compression costs (§7).
It rests on: the cached semantics; `S.compress`, which the submitter chooses.
Check it yourself: `sound_of_never_accepts` (`check-riscv-hint.lean:86`) shows the clause is
vacuous on an image nothing accepts, so read it together with `Faithful`. `sound_adaptive`
[12] shows plain quantification loses nothing against a prover who hashes first.

### [07] `Submission.Expands S` — RiscvHint.lean:140

Kind: a proposition on a submission.
It says: "on every path of `expand pk m σ`, the view it produces compresses back to `σ`." This
pins the honest view to the transmitted signature. Without it the certificate is still a
security statement — neither `Sound` nor `Faithful` uses it — but the honest view could stand for
a *different* valid signature than the one the signer produced, and "the machine reads an
expansion of the signature" would be a remark rather than a theorem. It is stated over
`support`, so it holds on incoherent paths too; a real `expand` satisfies it by construction.

### [08] `Submission.Faithful S` — RiscvHint.lean:161

Kind: a proposition on a submission.
Shape:
    ∀ pk m σ,
      probTrue (do
        let outcome  ← S.honestRun pk m σ        -- expand, then exec with S.fuel, then decision
        let accepted ← S.scheme.verify pk m σ
        pure (decide (outcome ≠ some accepted))) = 0
It says: "for every public key, message and raw signature, on every coherent oracle assignment,
the run on the honest prover's view **halts**, and its `HALT` bit is the verifier's decision."
Both directions: accepted signatures are accepted, rejected ones are rejected — not trapped, not
starved of fuel. So the honest prover and this image are together a complete verifier, as the
deterministic image is on its own. This is the counterpart of the RISC-V track's `Implements`
equation, weakened from equality of oracle computations to agreement of decisions under a
cache: the honest tree hashes twice where the verifier's hashes once (`expand` to learn what to
write, the machine to check it), and the two agree under a cache, not as syntax.
It rests on: the cached semantics; `S.expand` and `S.fuel`, which the submitter chooses.
Check it yourself: the rejected direction is the one an under-tested submission gets wrong —
a program that traps on a malformed honest view of a bad signature fails here. The port theorem
[13] needs exactly this on views longer than a signature, and states it as its one hypothesis.

### [09] `Submission.CyclesAtMost S c` — RiscvHint.lean:181

Kind: a proposition on a submission and a claim.
Shape:
    ∀ pk m view n cycles,
      some (true, cycles) ∈ support (S.exec n pk m view) → cycles ≤ c
It says: "every run that halts accepting, under every view and every fuel, on every answer path
including incoherent ones, took at most `c` cycles." Rejecting and faulting runs are not
charged: a view is prover-chosen, so a run that rejects or traps is a prover that produced
garbage and paid for it, and no proof of it is ever made. This is the leanISA track's reading,
and a real difference from the RISC-V track's "every execution, accepting or rejecting"; the
honest prover's rejecting runs are still required to halt by `Faithful`, but their length is
not bounded. Quantifying over every view is what stops a program whose honest run is short but
whose view-controlled loop admits an arbitrarily long accepting run; quantifying over every
fuel is what stops `fuel` from hiding one.
It rests on: the uncached semantics, as the RISC-V track's clause does.
Check it yourself: `cyclesAtMost_of_never_accepts` (`check-riscv-hint.lean:78`) shows it is
vacuous on an image nothing accepts; `Faithful` with `Admissible.correct` is what forces an
accepting honest run to exist.

### [10] `Submission.Certificate S c` — RiscvHint.lean:199

Kind: a proposition-valued structure: seven clauses that must all hold.
Shape:
    admissible : S.scheme.Admissible      secure : S.scheme.Secure
    valid      : S.image.Valid            expands : S.Expands
    faithful   : S.Faithful               sound   : S.Sound
    cycles     : S.CyclesAtMost c
It says: the scheme is a real OTS; the image fits the budgets; the honest view compresses back,
drives the machine to the verifier's decision, and no view drives it to accept a rejected
signature; and every accepting run costs at most `c`. `valid` is what stops a free lookup table
from absorbing every non-hash cost, as on the RISC-V track. The `probTrue` clauses and the
`support` clause are separate obligations in two semantics, not one argument.
Check it yourself: the stub [11] is the only consumer; the comparator compares its statement
with the claim substituted.

### [11] `submission`, `certificate`, `image_size` — UpperRiscvHint.lean.in

Kind: the three exported declarations, rendered with the claim.
It says: `submission : RiscvHint.Submission`, `certificate : submission.Certificate <claim>`,
and `image_size : submission.image.byteSize < 1048576`, the same image bound as the RISC-V
track, checked by the same comparator, axiom audit and kernel replay. The trusted size driver
`verifier/MeasureRiscv.lean` measures both tracks' images, since both fix a `Riscv.Image` as the
second field of their submission.

### [12] `Submission.sound_adaptive` — check-riscv-hint.lean:222

Kind: a theorem.
Shape:
    (sound : S.Sound) (P : OracleComp Spec (View × ℕ)) :
      probTrue (do let (view, n) ← P; ... same experiment as Sound ...) = 0
It says: "if a submission is sound, then for every oracle-adaptive strategy `P` that hashes
first and then chooses a view and a fuel from the answers, the machine still never accepts a
rejected signature." A winning path of the adaptive experiment runs `P` from the empty cache to
some view, fuel and cache, then runs the machine and the verifier from that cache; cache
weakening restricts that tail to a path from the empty cache, which `Sound` at that very view
and fuel forbids. The proof never uses that `P`'s output is reachable, so it holds for every `P`.
It rests on: `subcache_run`, the antitone direction of cache monotonicity, proved in the script
by induction on the free monad because VCVio ships only the forward direction.

### [13] `Riscv.Submission.hinted_certificate` — check-riscv-hint.lean:584

Kind: a theorem, and the one that licenses "this track generalises `upper-riscv`".
Shape:
    (h : S.Certificate c)
    (long : ∀ pk m view, maxSignatureBits < view.length →
       ∀ o ∈ support (S.hinted.exec (S.fuel pk m view) pk m view), decision o = some false) :
    S.hinted.Certificate c
It says: "a RISC-V track certificate at claim `c`, for an image that halts rejecting on every
view longer than a signature, is a hinted certificate at the same claim `c` for the identity
view — `compress = id`, `expand = pure`, the same fuel." The hypothesis covers the only inputs
the deterministic loader never presents: it truncates a long signature to 5,504 bits and sets the
length sentinel, while `loadView` keeps up to 1,048,576 bits and sets a larger one, so the
deterministic certificate says nothing about those states. An image discharges it by rejecting
every `a3` it does not expect: the 349-cycle record compares `a3` with the constant 5,504 it
loads from its data section and rejects on inequality, which covers every longer view. A test
of equality with the deterministic loader's sentinel 5,505 would *not* discharge it, since the
hinted loader reports lengths above 5,505 as themselves.
It rests on three facts about the machine and the oracle, each proved in the script:
- `execute_fuel_agree` (:375): a run that halts under one fuel halts identically under any
  other or runs it out — the machine is a function of the answers, so fuel can cut a run short
  but never change it. Proved once for the uncached and the cached path semantics through the
  three equations they share (`PathSemantics`).
- `subcache_run_grow` (:503): the cached simulation only adds entries.
- `replay_deterministic` (:523): a computation with no private randomness, run again from any
  cache holding every answer of a completed run, returns that run's result and samples nothing.
  This is what turns "the verifier is run after the machine under one cache" into "the verifier
  returns what `Implements` said it returns".
Check it yourself: `#print axioms` on it reports only `propext`, `Classical.choice` and
`Quot.sound` (guarded in the script). To port the 349-cycle RISC-V record, the submitter proves
`long` for that image and applies this theorem; §9 gives the steps.

## 6. Where strong unforgeability lives

The deterministic track's machine is a function of `(pk, m, σ)` and the oracle. This track's
is a function of `(pk, m, view)` and the oracle, and many views stand for one signature. Two
worries follow, and both have exact answers.

**"With several accepted views of one signature, strong unforgeability fails."** At the level
of views it does, and it is not supposed to hold there. Take the honest view `w₁ = expand(σ₁)`
and change a hint bit that the program checks but that has more than one valid value — a jump
target encoded two ways, a padding bit the program ignores. The machine accepts `w₂ ≠ w₁`. That
is a "strong forgery" of views exactly as a second SNARK witness for one statement is a
"forgery" of witnesses: it is not one. The signature is `compress w₂ = σ₁`, the pair
`(m₁, σ₁)` is the one the attacker was given, and `Secure` — stated once, in
`OracleAlgorithm.lean`, on signatures — is untouched. `RiscvHint.lean` does not restate
security and does not need to: `Secure` and `Admissible` are clauses of the certificate exactly
as on the RISC-V track.

What has to be shown is that security *transfers* to the machine, and the transfer is this.
Write `A_M(pk, m, σ)` for "some view compressing to `σ` drives the machine to accept". Then:

- `Sound` gives `A_M ⊆ verify`: an accepted view's projected signature is accepted by the
  verifier, on every coherent assignment.
- `Faithful` with `Expands` gives `verify ⊆ A_M`: if the verifier accepts `σ`, the honest view
  `expand(σ)` is accepted and compresses to `σ`.

So `A_M` and `scheme.verify` are the same predicate on every coherent oracle assignment, and the
winning event of the strong-unforgeability experiment — "an accepted pair other than the given
one" — is the same event whether the pair is judged by the machine (an accepted view, projected)
or by the specification. The budget in `Secure` counts the specification experiment, including its final verifier.
It is not automatically the budget of a machine-only experiment: identical acceptance does
not imply identical oracle costs. Converting a machine attacker by applying `compress` is
oracle-free, but final specification verification can add up to `2^20` compressions. Including
key generation and signing gives at most the attacker's own cost plus `3 · 2^20`.
The general quantitative attacker reduction is not a Lean theorem here. The identity-view
port theorem [13] constructs a certificate from an existing deterministic one; it does not
define or prove a separate machine-budget security experiment.

**"An untrusted view could turn a bad signature into an accepted run, or a good one into a
rejected run."** The first is `Sound`, and it is absolute: no view, no fuel, no coherent
assignment. The second is `Faithful`, and it is also absolute rather than budgeted: the honest
view of an accepted signature is accepted on every coherent path, with probability zero of
failure, not `2^-128`. The signing-failure budget is not spent here; it remains the signer's.
What an *adversarial* view can do to a good signature is make the machine reject or trap — and
that harms only the party who chose the view, which is why rejecting runs are not charged (§7).

**"The prover could grind views."** The score is the maximum over accepting runs, so a view
that makes the program take a shorter path lowers nothing; the bound has to hold on the longest
accepting path any view can reach. A program that accepts only "lucky" views (ones whose hint
hashes to a rare pattern, found by the prover at some cost) would have a shorter worst case —
and `Faithful` forbids it, because the honest `expand` must produce an accepted view of every
valid signature on every coherent path, with no probability of failure to hide a search behind.

## 7. What the score measures

| | `upper-riscv` | `upper-riscv-hint` | `upper-leanisa` |
|---|---|---|---|
| Third input | raw signature, ≤ 5,504 bits | prover-chosen view, ≤ 1,048,576 bits | prover-committed memory, `2^16`–`2^32` cells |
| Machine ↔ spec | one equation, `Implements` | `Expands`, `Faithful`, `Sound` | `Faithful`, `Sound` |
| Runs charged | every run, accepting or rejecting | every **accepting** run, every view, every fuel | every completing run, every image, every step count |
| Fixed surcharge | none | none | 120 cycles for the public boundary |
| Hash price | 1 cycle per 512-bit block | 1 cycle per 512-bit block | 10 cycles per 512-bit block |
| Size bound | `image_size` < 1 MiB | `image_size` < 1 MiB | `seeded_rows` < 1,048,576 |

The two RISC-V tracks share the machine and the hash price, so their scores are in one unit,
but they bound different sets of executions: a hinted score says nothing about the cost of a
rejection. That is why they are separate leaderboards rather than one.

**Decision agreement does not transfer compression costs.** For example, a specification
can query `H(x)` twice and check that both answers match a claimed digest. A machine can query
`H(x)` once and perform the same check. Both decide identically under the cached oracle, but
the specification pays for two calls and the machine pays for one. The regression theorem
`repeated_deterministic_agrees` checks the replay equality used by this example.

`Sound` prevents an unchecked hint from changing acceptance. It does not prove that the
machine performs every compression charged by the specification. A whole-word lower-bound
reference for this track needs a separate cost-preserving reduction to that framework;
`cycles_per_compression` is therefore omitted for this track.

**What hints can replace** is the instructions around the hashes. On the current 349-cycle
RISC-V record about 202 cycles are compressions (189 chain steps, twelve root blocks, one index
query) and the rest is index processing, checksum, dispatch and the root decision. A view can
carry the chain states at whatever alignment the `HASH` call wants, the index digits already
extracted, the per-chain jump targets, and the checksum's intermediate sums; the program still
has to check each of them against the hash outputs it computes, and the score is what remains
after that checking. Whether the remainder is meaningfully below 349 is the track's open
question, and the reason it opens with no baseline.

## 8. What you are asked to trust

| # | What | Stated at | Discharged by | Evidence it is satisfiable |
|---|------|-----------|---------------|----------------------------|
| T1 | The RV64IM semantics and the machine model | `RiscvMachine.lean`, riscv-zkvm `4634e41b` | pinned; unchanged from `upper-riscv` | the RISC-V record verifies under it |
| T2 | `HASH` is the random oracle, not a concrete hash | `RiscvMachine.lean`, `execute` | idealisation shared by every track | — |
| T3 | The view arrives in memory at no cost | `loadView` | design choice | — (see below) |
| T4 | Rejecting and faulting runs are not charged | `CyclesAtMost` | design choice, as on leanISA | — |
| T5 | `expand` carries no cost bound | `Submission` | design choice, as leanISA's `prover` | — |
| T6 | `Sound` and `Faithful` are `probTrue` statements; `CyclesAtMost` is a `support` statement | `RiscvHint.lean` | the two semantics, §1 | `probTrue_eq_zero_iff`; the port theorem [13] moves between them |
| T7 | `long` of [13]: the image halts rejecting on views longer than a signature | `check-riscv-hint.lean:584` | the submitter, per image | every real image tests `a3` first; not yet discharged for any image |
| T8 | Kernel axioms | every export | comparator | `propext`, `Classical.choice`, `Quot.sound` only; `check-axioms.lean` audits 106 contract declarations |

Kernel axioms: `check-axioms.lean` and the `#guard_msgs` blocks of `check-riscv-hint.lean` both
run clean; `execute_fuel_agree` and `loadView_eq_initialState` use only `propext` and
`Quot.sound`.

On T3: a real zkVM charges for hint delivery — a syscall per read, or memory-initialisation
rows — and this track does not. The view is delivered like the public key and message, by the
loader, and the program pays only the loads it performs. The cap `maxViewBits` bounds the free
volume; it does not price it. This is the same idealisation the RISC-V track makes for the
signature, extended to a larger input, and it is the boundary a reader comparing with a
measured zkVM cost should keep in mind. A second unpriced step appears only when a deployment
makes the *signature* public: the SNARK statement is then "`compress view = σ` and the machine
accepts `view`", and `compress` is evaluated in the circuit at a cost the score cannot see.
With `compress = view.take n` that is a public-input equality; with an arbitrary `compress` it
is real work. When the signature is a private witness, as in signature aggregation, `compress`
is never evaluated and only its soundness role (§6) matters.

On T4: the honest prover's rejecting runs must halt (`Faithful`) but may be arbitrarily long.
A submitter who wants the deterministic reading can prove the RISC-V track's `CyclesAtMost` as
well and say so in the notes; the contract does not ask for it.

### Stated but not proved

The certificate states proof obligations; defining it does not establish that any submission
satisfies them. The general-`compress` security transfer in §6 remains a prose argument.
The identity-view port theorem [13] is checked, but its extra long-view hypothesis has not
yet been discharged for a real submission.

### Questions for the author

1. Should `expand` be bounded, in compressions, at `signBudget = 2^20`? The bound would not
   touch security or the score, and non-hash work is free in the model either way, so it would
   say only that the honest prover's hashing is feasible. The leanISA track's `prover` carries
   no such bound, and this track follows it.
2. Is a length prefix on the view worth fixing in the contract, so that `compress` is always
   "the first `n` bits"? It would make the signature visible in the view without reading
   `compress`, at the cost of the aligned-layout freedom §2 argues for. Not done.

### Review validation

The new contract and `check-riscv-hint.lean` pass Lean 4.33.1, including the replay regression.
The optional measurement driver's definitions typecheck against the pinned comparator; the
side-effecting `run_cmd` entry was omitted for this compile check. A real hinted submission
has not yet exercised export, comparison, replay and measurement end to end.

Before launch, the planned single-track replacement still needs reviewed rules, its matching
contract, and verified ports retaining original authorship. This PR's current two-track model,
one-cycle HASH, unbounded expansion and all-accepting-run score are not the beta four-program
interface. Do not deploy it as if that replacement were complete.

## 9. Writing a submission

A root exports three declarations, and the comparator checks all three the same way — exact
statement comparison against the rendered stub, the axiom audit, and kernel replay:

```lean
noncomputable def OptimalOTS.Challenge.UpperRiscvHint.submission : RiscvHint.Submission := ...
theorem OptimalOTS.Challenge.UpperRiscvHint.certificate : submission.Certificate <claim> := ...
theorem OptimalOTS.Challenge.UpperRiscvHint.image_size : submission.image.byteSize < 1048576 := ...
```

Header imports admitted in an `UpperRiscvHint` root, beyond `Mathlib` and `VCVio` modules and
siblings of the same root: `OptimalOTS.Model`, `OptimalOTS.Dag`, `OptimalOTS.OracleAlgorithm`,
`OptimalOTS.RiscvMachine`, `OptimalOTS.Riscv` and `OptimalOTS.RiscvHint`. `OptimalOTS.Riscv` is
admitted so that a deterministic-track development can be reused as is.

Check locally from a submissions checkout:

```sh
python3 .contract/verifier/verify.py upper-riscv-hint --source .
```

**Porting the RISC-V record.** The cheapest first submission is the current `upper-riscv`
record read as a hinted one, at the same claim. Copy the root, keep its `Riscv.Submission` and
certificate, define `submission := RiscvUpperForest.submission.hinted` — the identity view of
`check-riscv-hint.lean:566`, which is not a contract declaration and so has to be restated in
the root — and discharge the `long` hypothesis of [13]: on a view longer than 5,504 bits the
image's `lengthCheck` loads the constant 5,504 from its data section, finds `a3 ≠ 5504`, takes
the reject branch and `HALT`s with `a0 = 0`. Any image ported this way needs a length test that
rejects every unexpected `a3`, not one that tests for the old sentinel 5,505. The port theorem's
supporting lemmas (`execute_fuel_agree`, `replay_deterministic`, `subcache_run_grow`) live in
the script and are copied into the root with it.

**Proving `Sound`.** Structure the program so that every accepting path re-derives from hash
outputs, or from the view bits it hashes, each quantity it took from the view: for a hinted
digit, compare it with the nibble of the index hash; for a hinted jump target, land in a table
whose entries are pinned by the image. The proof is then a case analysis on the view's bits
that ends either in a `HALT` with `a0 = 0` (nothing to show) or in an accepting `HALT` with the
same queries the specification's verifier makes, followed by the replay argument of [13] to
identify the verifier's answer with the machine's.

**Proving `Faithful`.** This is the RISC-V track's refinement proof on the honest view, both
directions, ending with `replay_deterministic` rather than with a syntactic equation. The
rejecting direction must reach `HALT`, so the honest `expand` should produce a well-formed view
of a rejected signature rather than leaving the program to trap on it.

**Proving `CyclesAtMost`.** Every accepting run under every view: loop counts and jump targets
that come from the view have to be bounded by the checks that precede their use, on every path
that can still accept. A loop whose count is a raw view word with no check has accepting runs of
every length and fails this clause.

## 10. Open items

- A first submission, ideally the ported RISC-V record, so the track has a baseline and the
  port theorem has been exercised end to end.
- Pricing hint delivery (T3), if a measured zkVM cost for it is ever wanted; it would be a
  per-view surcharge in `CyclesAtMost`, as `boundaryCycles` is on leanISA.
- The `HASH` price, shared with the RISC-V track (`NEXT_COMPTETION.md`).
- A kernel-checked "`Sound` bites" example, the counterpart of `sound_of_never_accepts`: the
  two-instruction image that loads the view's first byte into `a0` and halts accepts every
  view starting with a 1 byte without hashing, and `Sound` at every `(pk, m)` would force a
  universal signature, contradicting `Secure`. Stating it needs a lemma that `writeBytesAsWords`
  leaves unrelated addresses alone, which `check-riscv.lean` avoids by executing only hand-built
  states; the argument is in prose until then.
