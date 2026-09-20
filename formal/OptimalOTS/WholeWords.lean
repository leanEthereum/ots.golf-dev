import OptimalOTS.Dag

/-!
# Whole-word DAG schemes

Values consist of whole `wordBits`-bit words. Sources are independent words; each oracle output
is two words. A deterministic node may be a fixed public word (no parents), select a fixed low or
high half directly from a hash node, or concatenate any list of earlier values. Concatenation
may repeat, reorder or group values, including the empty list. There are no other deterministic
operations. Disclosure reveals a node's complete value.

Everything else (cuts, signing, verification, the oracle, costs, size limits and security) is
the DAG model of `Dag.lean`; in particular a hash input of any length pays its full
compression cost.
-/

namespace OptimalOTS.Dag

/-- Word length of the whole-word class; a hash output is two words (`hashBits = 2 * wordBits`). -/
def wordBits : ℕ := 128

/-- Sources are words and deterministic nodes are fixed words, concatenate values or select a
fixed half directly from a hash node. A node without parents is constant because its function
depends only on its parents. -/
def Graph.WholeWords (G : Graph) : Prop :=
  ∀ v, match G.kind v with
  | .source => G.len v = wordBits
  | .hash .. => True
  | .det ps _ f _ =>
      (ps = ∅ ∧ G.len v = wordBits) ∨
      (∃ ws : List (Fin G.size), ps = ws.toFinset ∧
        G.len v = (ws.map G.len).sum ∧
        ∀ x, f x = ofBits (G.len v) (ws.flatMap fun w => toBits (x w))) ∨
      (∃ p, ∃ high : Bool, (G.kind p).IsHash ∧ ps = {p} ∧ G.len v = wordBits ∧
        ∀ x, f x = ofBits (G.len v) ((toBits (x p)).drop (if high then wordBits else 0)))

end OptimalOTS.Dag

namespace OptimalOTS

open Dag

/-- Whole-word DAGs: every secure whole-word DAG scheme has a signature index whose verification
costs at least `c` compressions. -/
def LowerBoundGenerality1 (c : ℕ) : Prop :=
  ∀ S : Scheme, S.graph.WholeWords → S.Secure → ∃ i, c ≤ S.verifyCost i

end OptimalOTS
