import OptimalOTS.OracleAlgorithm
import OptimalOTS.RiscvMachine

/-!
# Hinted RISC-V upper submissions

A submission is an oracle-algorithm scheme — the *specification* of a one-time signature —
together with a RISC-V image that is supposed to *implement* its verifier, and a pair of pure
and oracle maps that relate what the machine reads to what the signer produced.

The machine is the one of `RiscvMachine.lean`, unchanged: the same RV64IM subset, the same two
system calls, the same cycle prices, the same deterministic `execute`. What changes is the
**third input**. `Riscv.lean` loads the raw signature and demands, in one equation, that the
machine's oracle computation equal the Lean verifier's. Here the loader places a *view* — a bit
string chosen by whoever runs the machine — and the machine's acceptance is tied to the verifier
by two clauses instead of one. This is the hinting a zkVM prover really has: the prover holds the
signature and unbounded free computation, and may hand the machine anything derived from them
(the signature laid out at aligned addresses, digit decompositions, quotients, jump targets),
provided the machine *checks* what it is handed rather than trusting it.

The tie between `view` and signature is a submitter-chosen pure map `compress : View → Signature`.
The signature the scheme signs and verifies, and whose length the `maxSignatureBits` cap bounds,
is `compress view`; the view itself is bounded only by `maxViewBits` and is never transmitted.
`Faithful` demands that the submitter's honest `expand` — an oracle computation, because a useful
view may contain hash outputs — drives the machine to exactly the verifier's decision; `Expands`
demands that `compress` undoes it; and `Sound` demands that **no** view, honest or not, makes the
machine accept unless `compress view` is a signature the verifier accepts. `Riscv.lean`'s
`Implements` is the special case `compress = id`, `expand = pure`: `Sound` and `Faithful` follow
from the equation for every image that halts rejecting on views longer than a signature, the one
kind of input the deterministic loader never presents (`scripts/check-riscv-hint.lean`,
`Riscv.Submission.hinted_certificate`).

Strong unforgeability is unaffected, and it is worth saying where it lives. `Secure` is a
statement about `scheme`, on signatures, and is stated once in `OracleAlgorithm.lean`. Views are
not signatures: many views compress to one signature, exactly as many SNARK witnesses prove one
statement, so a second accepted view of the honest signature is not a forgery of anything and no
clause here calls it one. What `Sound`, `Expands` and `Faithful` establish together is that the
machine's acceptance predicate — *some* view compressing to `σ` is accepted — agrees with `scheme.verify pk m σ`
on every coherent oracle assignment, and that is what carries `Admissible` and `Secure` onto the
machine, with `compress` as the bridge from an accepted view to the signature it stands for.
-/

namespace OptimalOTS.RiscvHint

open OracleComp Riscv RiscvZkvm.Rv64

/-! ## 1. Views and the loader -/

/-- A view: the bit string the machine reads in place of the raw signature. It is chosen by the
party running the machine, so every clause below that quantifies over it is a clause about an
adversary. -/
abbrev View := List Bool

/-- The greatest number of view bits the loader places in memory. Longer views are truncated,
and the length register says so, as `Riscv.initialState` does for oversized signatures. The
same number bounds the RISC-V image in bytes and the leanISA tables in rows; here it is bits,
and it is generous: a claim below `limits.max_claim` cannot read more than a few megabytes, and
an OTS verifier's hints are a few kilobytes. -/
def maxViewBits : ℕ := 1048576

/-- The loader: `Riscv.initialState` with the view in the signature's place. The public key,
message, code, data, stack pointer and argument registers are laid out identically; `a2` points
at the view at `signatureBase` and `a3` holds its bit length, capped at `maxViewBits + 1` so
that a truncated view is distinguishable from every complete one. On a view of at most
`maxSignatureBits` bits the two loaders agree exactly (`check-riscv-hint.lean`,
`loadView_eq_initialState`), which is what lets a deterministic-track image be read as a hinted
one. -/
def loadView (image : Image) (pk : PublicKey) (m : Message) (view : View) : MachineState :=
  let blank : MachineState :=
    { regs := fun _ => 0, mem := fun _ => 0, code := loadProgram codeBase image.code,
      pc := codeBase }
  let s := (((blank.writeBytesAsWords dataBase image.data).writeBytesAsWords publicKeyBase
    (bytesOfVector pk)).writeBytesAsWords messageBase (bytesOfVector m)).writeBytesAsWords
    signatureBase (bytesOfBits (view.take maxViewBits))
  ((((s.setReg .x2 stackTop).setReg .x10 publicKeyBase).setReg .x11 messageBase).setReg
    .x12 signatureBase).setReg .x13
    (BitVec.ofNat 64 (min view.length (maxViewBits + 1)))

/-- The decision of a completed run: `some true` for an accepting HALT, `some false` for a
rejecting one, `none` for a trap or exhausted fuel. -/
def decision (o : Outcome) : Option Bool := o.map Prod.fst

/-! ## 2. Submissions -/

/-- An OTS specification, the image meant to check it, and the maps relating views to
signatures.

`compress` is the pure projection from a view to the signature it stands for; it is what
`Sound` verifies against, and the object whose length `Admissible.signatureSize` bounds.
`expand` is the honest prover's view of a signature; it may query the oracle because a useful
view contains hash outputs. `fuel` bounds the instructions of the honest run on each raw
signature, witnessing its termination.

Neither `expand` nor `fuel` is an input to the machine, and neither can lower the score: they
appear only in `Expands` and `Faithful`, while `Sound` and `CyclesAtMost` range over every view
and every fuel. -/
structure Submission where
  /-- The one-time signature this submission claims to implement. -/
  scheme : OracleAlgorithm.Scheme
  /-- The fixed RV64IM image. -/
  image : Image
  /-- The signature a view stands for. -/
  compress : View → OracleAlgorithm.Signature
  /-- The honest prover's view of a signature, per raw input. -/
  expand : PublicKey → Message → OracleAlgorithm.Signature → OracleComp Spec View
  /-- The instruction budget of the honest run, per raw input. -/
  fuel : PublicKey → Message → OracleAlgorithm.Signature → ℕ

/-- The machine run on one view for `n` instructions, from the loader's initial state. -/
def Submission.exec (S : Submission) (n : ℕ) (pk : PublicKey) (m : Message) (view : View) :
    OracleComp Spec Outcome :=
  execute n (loadView S.image pk m view)

/-- Soundness: no view makes the machine accept what the verifier rejects.

The view and the fuel are quantified plainly, over every bit string and every instruction
budget, not the submission's own. That is no weaker than quantifying an oracle-adaptive prover
that hashes before choosing its view: `check-riscv-hint.lean` proves `Submission.sound_adaptive`
from this clause by cache weakening, exactly as `LeanIsa.Submission.sound_adaptive` is proved.

`probTrue x = 0` says the bad event occurs on **no** path of the cached simulation, not merely
with probability zero: `probTrue x = 0 ↔ true ∉ support ((simulateQ oracleImpl x).run' ∅)`
(`probTrue_eq_zero_iff`). The cache is essential: the machine and the verifier must see the
same answer for the same query. This constrains acceptance, not the sequence or number of
queries. In particular, the machine may reuse an answer where the specification repeats a
query. No compression-cost lower bound is transferred by this clause alone. -/

def Submission.Sound (S : Submission) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (view : View) (n : ℕ),
    probTrue (do
      let outcome ← S.exec n pk m view
      let accepted ← S.scheme.verify pk m (S.compress view)
      pure (decide (decision outcome = some true) && !accepted)) = 0

/-- The honest view is a view of the signature: `compress` undoes `expand` on every path.

Without this clause the certificate is still a security statement — `Sound` and `Faithful` do
not use it — but the honest view could stand for a *different* valid signature than the one the
signer produced, and "the machine reads an expansion of the transmitted signature" would be a
remark rather than a theorem. -/
def Submission.Expands (S : Submission) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (σ : OracleAlgorithm.Signature) (view : View),
    view ∈ support (S.expand pk m σ) → S.compress view = σ

/-- The machine driven by the submission's own prover: the decision of the run on the honest
view, within the submission's fuel. -/
def Submission.honestRun (S : Submission) (pk : PublicKey) (m : Message)
    (σ : OracleAlgorithm.Signature) : OracleComp Spec (Option Bool) := do
  let view ← S.expand pk m σ
  decision <$> S.exec (S.fuel pk m σ) pk m view

/-- Faithfulness: on every raw signature, the honest prover's run **halts** with the verifier's
decision, under the shared cached oracle. Accepted signatures are accepted, rejected ones are
rejected — not trapped, not starved of fuel — so the honest prover and this image are together
a complete verifier, as the deterministic track's image is on its own.

This is the counterpart of `Riscv.Submission.Implements`: agreement of decisions under the
cached oracle, in place of equality of oracle computations. The equation is unavailable because
the honest tree hashes twice where the verifier's hashes once — `expand` queries to learn what
to put in the view, the machine re-queries to check it — and the two agree under a cache, not
as syntax. -/
def Submission.Faithful (S : Submission) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (σ : OracleAlgorithm.Signature),
    probTrue (do
      let outcome ← S.honestRun pk m σ
      let accepted ← S.scheme.verify pk m σ
      pure (decide (outcome ≠ some accepted))) = 0

/-- Every accepting execution, under every view and every fuel, costs at most `c` cycles.

Rejecting and faulting runs are not charged. A view is prover-chosen, so a run that rejects or
traps is a prover that produced garbage and paid for it; no proof of it is ever made, which is
the leanISA track's reading and differs from `Riscv.Submission.CyclesAtMost`'s "every
execution, accepting or rejecting". The honest prover's rejecting runs are still required to
halt (`Faithful`), just not bounded here.

Quantifying over every view is what stops a program whose honest run is short but whose
view-controlled loop admits an arbitrarily long accepting run, and quantifying over every fuel
is what stops `fuel` from hiding such a run. This clause is stated over `support`, as
`Riscv.Submission.CyclesAtMost` is, so it must hold on incoherent answer paths too; for a
deterministic machine that is the same obligation the existing track already carries. -/
def Submission.CyclesAtMost (S : Submission) (c : ℕ) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (view : View) (n cycles : ℕ),
    some (true, cycles) ∈ support (S.exec n pk m view) → cycles ≤ c

/-- The certificate for claim `c`.

`admissible` and `secure` pin the specification to a real 127-bit strongly unforgeable OTS.
`expands`, `faithful` and `sound` pin the image to that specification: together they make the
machine's acceptance — some view compressing to `σ` is accepted — agree with `scheme.verify`
on every coherent oracle assignment, which is what carries admissibility and security onto the
machine. `valid` bounds the image, without which a free lookup table would absorb every non-hash
cost. `cycles` then measures a program that really has to run the verification:
`Admissible.correct` forces `scheme.verify` to accept something, `faithful` forces an accepting
honest run there, and `secure` forces that run to hash.

`cycles` is stated over `support` while `faithful` and `sound` are stated over `probTrue`, so
the clauses are separate obligations in two oracle semantics rather than one argument; see each
clause for what it does and does not say. -/
structure Submission.Certificate (S : Submission) (c : ℕ) : Prop where
  /-- Correctness, deterministic verification, bounded signing failure, and the size and cost
  budgets of the competition. -/
  admissible : S.scheme.Admissible
  /-- Strong unforgeability in the shared random-oracle experiment. -/
  secure : S.scheme.Secure
  /-- The image fits the instruction and data budgets and uses admitted instructions only. -/
  valid : S.image.Valid
  /-- The honest view compresses back to the signature it was expanded from. -/
  expands : S.Expands
  /-- The honest prover's run halts with the verifier's decision on every input. -/
  faithful : S.Faithful
  /-- No view makes the machine accept a signature the verifier rejects. -/
  sound : S.Sound
  /-- Every accepting execution, under every view and fuel, costs at most `c` cycles. -/
  cycles : S.CyclesAtMost c

end OptimalOTS.RiscvHint
