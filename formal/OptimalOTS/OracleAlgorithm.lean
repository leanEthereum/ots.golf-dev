import OptimalOTS.Model

/-!
# One-time signatures as oracle algorithms

The model of both upper bounds (compressions and RISC-V
cycles). A scheme is three oracle programs that share the random oracle of `Model.lean` and
pay its compression costs; all other computation is free. Signatures are bit strings. Key
generation and signing may use private randomness; verification may not. `Admissible` collects
every requirement except security.
-/

open OracleSpec OracleComp ENNReal
noncomputable section
open scoped Classical

namespace OptimalOTS.OracleAlgorithm

/-- Signatures are plain bit strings. -/
abbrev Signature := List Bool

/-- Key generation, signing and verification as oracle programs. Signing returns `none` when it
fails. -/
structure Scheme where
  SecretKey : Type
  keygen : OracleComp Spec (PublicKey × SecretKey)
  sign : SecretKey → Message → OracleComp Spec (Option Signature)
  verify : PublicKey → Message → Signature → OracleComp Spec Bool

/-- A one-signature attacker: choose a message after seeing the public key, then forge.
Both stages may query the shared oracle and use private randomness. -/
structure Adversary where
  State : Type
  choose : PublicKey → OracleComp Spec (Message × State)
  forge : State → Option Signature → OracleComp Spec (Message × Signature)

/-- The attacker wins on an accepted message-signature pair other than the signed pair.
If signing fails, any accepted pair wins. All parties share one oracle throughout. -/
def experiment (S : Scheme) (A : Adversary) : OracleComp Spec Bool := do
  let (pk, sk) ← S.keygen
  let (m₁, st) ← A.choose pk
  let σ₁ ← S.sign sk m₁
  let (m₂, σ₂) ← A.forge st σ₁
  let ok ← S.verify pk m₂ σ₂
  return ok && decide (σ₁.map (fun s => (m₁, s)) ≠ some (m₂, σ₂))

namespace Scheme

variable (S : Scheme)

/-- Strong unforgeability: the attacker wins with probability strictly below
`B / 2 ^ securityBits`, for every pathwise budget `B` of the whole experiment (the attacker's
queries, honest key generation and signing, and the final verification). -/
def Secure : Prop :=
  ∀ (A : Adversary) (B : ℕ), CostAtMost (experiment S A) B →
    probTrue (experiment S A) < (B : ℝ≥0∞) / 2 ^ securityBits

/-- Verification costs at most `c` on every input and every oracle-answer path, including rejects. -/
def VerifyCostAtMost (c : ℕ) : Prop := ∀ pk m σ, CostAtMost (S.verify pk m σ) c

/-- Verification uses no private randomness, on any input. -/
def VerifyDeterministic : Prop := ∀ pk m σ, Deterministic (S.verify pk m σ)

/-- Key generation costs at most `b` on every oracle-answer path. -/
def KeygenCostAtMost (b : ℕ) : Prop := CostAtMost S.keygen b

/-- Signing costs at most `b` for every secret key, message, and oracle-answer path. -/
def SignCostAtMost (b : ℕ) : Prop := ∀ sk m, CostAtMost (S.sign sk m) b

/-- Every signature that signing can output has at most `n` bits. -/
def SignatureSizeAtMost (n : ℕ) : Prop :=
  ∀ sk m σ, some σ ∈ support (S.sign sk m) → σ.length ≤ n

/-- Verification rejects every bit string longer than `n`, on every oracle-answer path. -/
def RejectsOversized (n : ℕ) : Prop :=
  ∀ pk m σ, n < σ.length → true ∉ support (S.verify pk m σ)

/-- Perfect correctness: for every message chosen from the public key, an honest signature is
rejected with probability zero. Signing failure is bounded separately. -/
def Correct : Prop := ∀ message : PublicKey → Message,
  probTrue (do
    let (pk, sk) ← S.keygen
    let m := message pk
    let σ ← S.sign sk m
    match σ with
    | none => return false
    | some s => return !(← S.verify pk m s)) = 0

/-- For every message chosen from the public key, signing fails with probability at most `ε`,
over honest key generation and signing. -/
def SigningFailureAtMost (ε : ℝ≥0∞) : Prop :=
  ∀ message : PublicKey → Message,
  probTrue (do
    let (pk, sk) ← S.keygen
    return (← S.sign sk (message pk)).isNone) ≤ ε

/-- Every requirement except security, with the competition's constants. -/
structure Admissible : Prop where
  correct : S.Correct
  verifyDeterministic : S.VerifyDeterministic
  signingFailure : S.SigningFailureAtMost (1 / 2 ^ signingFailureBits)
  signatureSize : S.SignatureSizeAtMost maxSignatureBits
  rejectsOversized : S.RejectsOversized maxSignatureBits
  keygenCost : S.KeygenCostAtMost keygenBudget
  signCost : S.SignCostAtMost signBudget

end Scheme

end OptimalOTS.OracleAlgorithm
