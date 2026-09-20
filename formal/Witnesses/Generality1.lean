import Witnesses.Generality1.Main
import Witnesses.Generality1.Words

/-! Internal check, not part of the contract: the Whole-word DAGs lower bound quantifies over a
non-empty class. The forest with 128-bit tweak words is a secure whole-word scheme. -/

namespace OptimalOTS.Witnesses

open OptimalOTS.Dag


theorem generality1 :
    ∃ S : Scheme, S.graph.WholeWords ∧ S.Secure ∧ ∀ i, S.verifyCost i ≤ 106 :=
  ⟨Forest.forestScheme, Forest.graph_wholeWords, Forest.forestScheme_secure,
    fun i => (Forest.forestScheme_verifyCost i).le⟩

end OptimalOTS.Witnesses

/--
info: 'OptimalOTS.Witnesses.generality1' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.Witnesses.generality1
