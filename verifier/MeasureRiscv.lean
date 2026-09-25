import Main

/-! Optional display metadata. This trusted driver imports only the pinned comparator.
Candidate modules are exported inside its sandbox, never imported into this process.
The exported certificate is compared and replayed before kernel reduction counts the image.
Run with `lean` (not `lean --run`, which would call the imported comparator entry point).
-/
namespace OtsRiscvSize
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

def listLength (env : Environment) (value : Expr) (limit : Nat) : IO Nat := do
  let mut tail := value
  for count in [:limit + 1] do
    let reduced ← IO.ofExcept <| (Kernel.whnf env {} tail).mapError (fun _ => "kernel reduction failed")
    if reduced.isAppOfArity ``List.nil 1 then return count
    unless reduced.isAppOfArity ``List.cons 3 do
      throw <| IO.userError "image list does not reduce to a constructor"
    tail := reduced.getAppArgs[2]!
  throw <| IO.userError "image exceeds the contract size limit"

/-- The two RISC-V tracks share `Riscv.Image` as the second field of their submission
structure, so one driver measures both; the config names the track. -/
def tracks : List (String × String × Name × Name) :=
  [("Submissions.UpperRiscv.Solution", "OptimalOTS.Challenge.UpperRiscv",
    `OptimalOTS.Riscv.Submission, `OptimalOTS.Challenge.UpperRiscv.submission),
   ("Submissions.UpperRiscvHint.Solution", "OptimalOTS.Challenge.UpperRiscvHint",
    `OptimalOTS.RiscvHint.Submission, `OptimalOTS.Challenge.UpperRiscvHint.submission)]

def measure (structName submissionName : Name) : Comparator.M Json := do
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
  let image := Expr.proj structName 1 (mkConst submissionName)
  let instructions ← listLength env (.proj `OptimalOTS.Riscv.Image 0 image) 262144
  let dataBytes ← listLength env (.proj `OptimalOTS.Riscv.Image 1 image) 1048576
  return Json.mkObj [("instructions", toJson instructions), ("data_bytes", toJson dataBytes)]

def run : IO Unit := do
  let some configPath ← IO.getEnv "OTS_SIZE_CONFIG"
    | throw <| IO.userError "missing config path"
  let some outputPath ← IO.getEnv "OTS_SIZE_OUTPUT"
    | throw <| IO.userError "missing output path"
  let cfg : Comparator.Config ← IO.ofExcept <| fromJson? <| ← IO.ofExcept <|
    Json.parse (← IO.FS.readFile configPath)
  let some (_, _, structName, submissionName) := tracks.find? fun (solution, challenge, _, _) =>
      cfg.solution_module == solution && cfg.challenge_module == challenge
    | throw <| IO.userError "RISC-V config required"
  if cfg.enable_nanoda then throw <| IO.userError "RISC-V config required"
  let result ← Comparator.M.run (measure structName submissionName) cfg
  IO.FS.writeFile outputPath result.compress

end OtsRiscvSize

run_cmd Lean.Elab.Command.liftIO OtsRiscvSize.run
