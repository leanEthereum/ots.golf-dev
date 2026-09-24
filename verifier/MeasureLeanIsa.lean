import Main

/-! Optional display metadata. This trusted driver imports only the pinned comparator.
Candidate modules are exported inside its sandbox, never imported into this process.
The exported certificate is compared and replayed before kernel reduction counts the bytecode slots.
Run with `lean` (not `lean --run`, which would call the imported comparator entry point).
-/
namespace OtsLeanIsaSize
open Lean

def exportModule (module : Name) (targets : Array Name) : Comparator.M String := do
  let ctx ← read
  -- The driver's LEAN_PATH contains only trusted tool libraries. Lake computes the
  -- candidate search path inside the sandbox from the protected project lakefile.
  Comparator.runSandBoxedWithStdout {
    cmd := (ctx.leanPrefix / "bin" / "lake").toString
    args := #["env", ctx.whichLean4Export, module.toString, "--"] ++ targets.map Name.toString
    envPass := #["PATH", "HOME", "LEAN_ABORT_ON_PANIC"]
    envOverride := #[("LEAN_ABORT_ON_PANIC", some "1")]
    readablePaths := #[ctx.projectDir, ctx.projectDir / ".lake"]
    writablePaths := #[]
    executablePaths := #[ctx.leanPrefix, ctx.gitLocation, System.FilePath.mk ctx.whichLean4Export]
  }

def boundedNat (env : Environment) (value : Expr) (limit : Nat) : IO Nat := do
  let mut tail := value
  for count in [:limit + 1] do
    let reduced ← IO.ofExcept <| (Kernel.whnf env {} tail).mapError (fun _ => "kernel reduction failed")
    if let .lit (.natVal n) := reduced then
      if count + n ≤ limit then return count + n
      throw <| IO.userError "bytecode log-size exceeds the contract limit"
    if reduced.isConstOf ``Nat.zero then return count
    unless reduced.isAppOfArity ``Nat.succ 1 do
      throw <| IO.userError "bytecode log-size does not reduce to a natural number"
    tail := reduced.getAppArgs[0]!
  throw <| IO.userError "bytecode log-size exceeds the contract limit"

def measure : Comparator.M Json := do
  let targets := (← Comparator.builtinTargets) ++ (← Comparator.getTheoremNames)
    ++ (← Comparator.getLegalAxioms) ++ (← Comparator.primitiveTargets)
    ++ (← Comparator.getDefinitionNames)
  let challenge ← exportModule (← Comparator.getChallengeModule) targets
  let solution ← exportModule (← Comparator.getSolutionModule) targets
  -- Keep verifyMatch's statement, primitive and axiom checks, but retain the
  -- replayed environment for counting instead of replaying the same proof twice.
  let expected ← Export.parseStream (← Comparator.stringStream challenge)
  let exported ← Export.parseStream (← Comparator.stringStream solution)
  let theorems ← Comparator.getTheoremNames
  let definitions ← Comparator.getDefinitionNames
  let axioms ← Comparator.getLegalAxioms
  IO.ofExcept <| Comparator.compareAt expected exported (theorems ++ axioms)
    definitions (← Comparator.primitiveTargets)
  IO.ofExcept <| Comparator.checkAxioms exported theorems definitions axioms
  let env ← mkEmptyEnvironment
  let env ← env.replay (exported.constMap.erase `Quot.mk |>.erase `Quot.lift |>.erase `Quot.ind)
  let program := Expr.proj `OptimalOTS.LeanIsa.Submission 1
    (mkConst `OptimalOTS.Challenge.UpperLeanIsa.submission)
  let logSize ← boundedNat env (.proj `LeanerVM.Semantics.Program 0 program) 18
  return Json.mkObj [("instructions", toJson (2 ^ logSize : Nat))]

def run : IO Unit := do
  let some configPath ← IO.getEnv "OTS_SIZE_CONFIG"
    | throw <| IO.userError "missing config path"
  let some outputPath ← IO.getEnv "OTS_SIZE_OUTPUT"
    | throw <| IO.userError "missing output path"
  let cfg : Comparator.Config ← IO.ofExcept <| fromJson? <| ← IO.ofExcept <|
    Json.parse (← IO.FS.readFile configPath)
  unless cfg.solution_module == "Submissions.UpperLeanIsa.Solution" &&
      cfg.challenge_module == "OptimalOTS.Challenge.UpperLeanIsa" && !cfg.enable_nanoda do
    throw <| IO.userError "leanISA config required"
  let result ← Comparator.M.run measure cfg
  IO.FS.writeFile outputPath result.compress

end OtsLeanIsaSize

run_cmd Lean.Elab.Command.liftIO OtsLeanIsaSize.run
