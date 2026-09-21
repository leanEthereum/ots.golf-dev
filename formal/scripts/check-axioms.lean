/-
Audit of the protected contract: the definitions that a certificate's meaning depends on must
use only `propext`, `Classical.choice` and `Quot.sound`, and no module of the protected library
may declare an axiom.

    lake env lean scripts/check-axioms.lean
-/
import Lean
import OptimalOTS.Model
import OptimalOTS.Dag
import OptimalOTS.WholeWords
import OptimalOTS.OracleAlgorithm
import OptimalOTS.Riscv
import OptimalOTS.LeanIsa

open Lean

/-- The declarations whose meaning fixes what a certificate says. -/
def contractDecls : List Name :=
  [``OptimalOTS.hashBits, ``OptimalOTS.blockBits, ``OptimalOTS.pkBits, ``OptimalOTS.msgBits,
   ``OptimalOTS.securityBits, ``OptimalOTS.maxSignatureBits, ``OptimalOTS.keygenBudget,
   ``OptimalOTS.signBudget, ``OptimalOTS.verifyBudget, ``OptimalOTS.signingFailureBits,
   ``OptimalOTS.probTrue, ``OptimalOTS.CostAtMost, ``OptimalOTS.CostAtMost.mono,
   ``OptimalOTS.Deterministic,
   ``OptimalOTS.queryCost, ``OptimalOTS.blockCost, ``OptimalOTS.oracleImpl,
   ``OptimalOTS.Dag.nonceBits, ``OptimalOTS.Dag.idxBits, ``OptimalOTS.Dag.idxCost,
   ``OptimalOTS.Dag.trials, ``OptimalOTS.Dag.numCuts,
   ``OptimalOTS.Dag.Graph, ``OptimalOTS.Dag.Scheme,
   ``OptimalOTS.Dag.Scheme.verifyCost, ``OptimalOTS.Dag.Graph.reconstructCost,
   ``OptimalOTS.Dag.Scheme.Secure, ``OptimalOTS.Dag.experiment,
   ``OptimalOTS.Dag.Scheme.keygen, ``OptimalOTS.Dag.Scheme.sign,
   ``OptimalOTS.Dag.Scheme.verify, ``OptimalOTS.Dag.index,
   ``OptimalOTS.Dag.Graph.WholeWords, ``OptimalOTS.Dag.wordBits,
   ``OptimalOTS.LowerBoundGenerality1,
   ``OptimalOTS.OracleAlgorithm.Scheme, ``OptimalOTS.OracleAlgorithm.Adversary,
   ``OptimalOTS.OracleAlgorithm.experiment,
   ``OptimalOTS.OracleAlgorithm.Scheme.Admissible, ``OptimalOTS.OracleAlgorithm.Scheme.Correct,
   ``OptimalOTS.OracleAlgorithm.Scheme.SigningFailureAtMost,
   ``OptimalOTS.OracleAlgorithm.Scheme.SignatureSizeAtMost,
   ``OptimalOTS.OracleAlgorithm.Scheme.RejectsOversized,
   ``OptimalOTS.OracleAlgorithm.Scheme.KeygenCostAtMost,
   ``OptimalOTS.OracleAlgorithm.Scheme.SignCostAtMost,
   ``OptimalOTS.OracleAlgorithm.Scheme.VerifyCostAtMost,
   ``OptimalOTS.OracleAlgorithm.Scheme.VerifyCostAtMost.mono,
   ``OptimalOTS.OracleAlgorithm.Scheme.VerifyDeterministic,
   ``OptimalOTS.OracleAlgorithm.Scheme.Secure,
   ``OptimalOTS.Riscv.Image, ``OptimalOTS.Riscv.Image.Valid,
   ``OptimalOTS.Riscv.admittedInstruction, ``OptimalOTS.Riscv.initialState,
   ``OptimalOTS.Riscv.hashInput, ``OptimalOTS.Riscv.hashArgumentsValid,
   ``OptimalOTS.Riscv.writeHash, ``OptimalOTS.Riscv.execute,
   ``OptimalOTS.Riscv.Submission, ``OptimalOTS.Riscv.Submission.run,
   ``OptimalOTS.Riscv.Submission.Implements, ``OptimalOTS.Riscv.Submission.CyclesAtMost,
   ``OptimalOTS.Riscv.Submission.Certificate,
   ``OptimalOTS.LeanIsa.weight, ``OptimalOTS.LeanIsa.cellBits, ``OptimalOTS.LeanIsa.cellOfBits,
   ``OptimalOTS.LeanIsa.cellBits_cellOfBits, ``OptimalOTS.LeanIsa.eq_of_cellBits_eq,
   ``OptimalOTS.LeanIsa.execute_eq_leanerVM,
   -- The two decision procedures are audited too: a sorried instance is the one shape
   -- typeclass synthesis can pull into a submitter's proof with no syntactic trace.
   ``OptimalOTS.LeanIsa.instDecidableBytecodeValid,
   ``OptimalOTS.LeanIsa.instDecidableOracleCompressCells,
   ``OptimalOTS.LeanIsa.hashInput, ``OptimalOTS.LeanIsa.blake2sQuery,
   ``OptimalOTS.LeanIsa.OracleCompressCells, ``OptimalOTS.LeanIsa.execute,
   ``OptimalOTS.LeanIsa.runCost, ``OptimalOTS.LeanIsa.maxProgramLogSize,
   ``OptimalOTS.LeanIsa.sentinelSlot, ``OptimalOTS.LeanIsa.BytecodeValid,
   ``OptimalOTS.LeanIsa.maxSeededRows, ``OptimalOTS.LeanIsa.Submission.seededRows,
   ``OptimalOTS.LeanIsa.statementBits, ``OptimalOTS.LeanIsa.statementBitLength,
   ``OptimalOTS.LeanIsa.statementBlocks, ``OptimalOTS.LeanIsa.boundaryCycles,
   ``OptimalOTS.LeanIsa.signatureCells, ``OptimalOTS.LeanIsa.inputCells,
   ``OptimalOTS.LeanIsa.inputWord, ``OptimalOTS.LeanIsa.loadInput,
   ``OptimalOTS.LeanIsa.Submission, ``OptimalOTS.LeanIsa.Submission.exec,
   ``OptimalOTS.LeanIsa.Submission.Sound, ``OptimalOTS.LeanIsa.Submission.honestRun,
   ``OptimalOTS.LeanIsa.Submission.Faithful, ``OptimalOTS.LeanIsa.Submission.CyclesAtMost,
   ``OptimalOTS.LeanIsa.Submission.Certificate]

def whitelist : List Name := [``propext, ``Classical.choice, ``Quot.sound]

open Elab.Command in
run_cmd liftCoreM do
  let env ← getEnv
  let mods := env.header.moduleNames
  let mut bad : Array (Name × Name) := #[]
  for (name, ci) in env.constants.toList do
    if let some idx := env.getModuleIdxFor? name then
      let modName := mods[idx.toNat]!
      if (`OptimalOTS).isPrefixOf modName && ci.isAxiom then
        bad := bad.push (name, modName)
  unless bad.isEmpty do
    for (n, m) in bad do
      IO.eprintln s!"::error::axiom declaration `{n}` in protected module `{m}`"
    throwError "axiom declarations found in protected modules ({bad.size})"
  IO.println "ok — no axiom is declared in the protected modules"

open Elab.Command in
run_cmd liftTermElabM do
  let mut failed := false
  for decl in contractDecls do
    let axioms ← collectAxioms decl
    let offending := axioms.toList.filter (fun a => !whitelist.contains a)
    unless offending.isEmpty do
      failed := true
      for ax in offending do
        IO.eprintln s!"::error::contract declaration `{decl}` depends on `{ax}`"
  if failed then throwError "the contract depends on non-whitelisted axioms"
  IO.println s!"ok — {contractDecls.length} contract declarations use only propext/Classical.choice/Quot.sound"
