# ots.golf — submission rules

ots.golf is a Lean-kernel-verified competition on the worst-case verification cost of hash-based
one-time signatures, with one whole-word lower-bound track and two upper tracks: a fully generic
compression bound and a RISC-V implementation bound in cycles. The DAG model is
`formal/OptimalOTS/Dag.lean`; `formal/OptimalOTS/WholeWords.lean` defines the whole-word class.
`challenges.json` lists the tracks; `verifier/` runs the hosted verifier's checks. This file is the
precise specification; [ots.golf/rules](https://ots.golf/rules) presents the same rules for
reading.

## Before preparing a submission

Read [the rules](https://ots.golf/rules), or fetch this submission specification as
[plain text](https://ots.golf/rules.md). Open proof PRs from your fork's branch into
[leanEthereum/ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions),
base branch **main**. The core repository maintains the model, verifier and website.
The [agent guide](https://ots.golf/llms.txt) gives the setup and submission steps.

## Layout

```
formal/                      the Lean project (lake root)
  OptimalOTS/Model.lean      shared model: constants, the random oracle and its costs
  OptimalOTS/Dag.lean        DAG model in namespace OptimalOTS.Dag: signing format, Scheme, Secure, verifyCost
  OptimalOTS/Challenge/      stubs (*.lean.in), rendered with your claim
  Submissions/<Root>/        a submission root; lives in the submissions repository, never here
verifier/                    checks, contract pin, comparator configs, verify.py
challenges.json              tracks, limits, protected files
```

Protected files (listed in `challenges.json`, pinned in `verifier/protected.sha256`) come from
the trusted contract. A submission consists of one submission root's contents. The core holds no
proofs of any track; reference proofs are ordinary submissions.

## Frameworks

All three public tracks are open.

- **Whole-word DAGs** (`lower-generality-1`): whole-word DAGs. Secret sources are independent
  uniform 128-bit words; hashes return 256 bits. Each deterministic node is a fixed public 128-bit
  word, selects a fixed low or high half directly from a hash output, or concatenates an ordered
  list of complete earlier values. Concatenations may repeat, reorder, group or be empty.
  Disclosures reveal complete node values. This syntax and the 5376-bit payload budget imply at
  most 42 disclosed hash origins.
- **Upper bound** (`upper-compressions`): arbitrary oracle programs. The challenge fixes perfect
  correctness, deterministic verification, signing failure at most `2^-128` for every
  public-key-dependent message choice, the size and resource limits of the rules, and 127-bit strong
  unforgeability.
- **RISC-V upper bound** (`upper-riscv`): an OTS meeting the Upper bound requirements, together
  with a fixed RV64IM verifier proved to compute exactly the Lean verifier's oracle computation on
  every raw input. The score is a proved bound on the cycles of every execution, accepting or
  rejecting.

The whole-word DAG model uses the 128-bit nonce, 127-bit security target, cuts, forward reconstruction
and actual-input compression costs. Proof guides for the reference proofs are in `docs/`.

## Oracle model

The contract has one random oracle on bit strings (`Query := Σ k, BitVec k`). Equal input strings
receive the same answer across all uses. A scheme may put a tweak in its input and pays for those
bits. Hashing costs one compression per started 512-bit block, at least one. The 384-bit
message-and-nonce index costs one compression. Claims require Lean-kernel-checked certificates.

## What a submission exports

The verifier renders the track's stub with your claim and compares your declarations against it.
Names and statements must match exactly; copy them from the rendered stub.

**Lower bound · Whole-word DAGs** (`formal/Submissions/LowerGenerality1/`, larger is better; a record
needs claim ≥ record + 1):

```lean
theorem OptimalOTS.Challenge.LowerGenerality1.candidate :
    LowerBoundGenerality1 <claim> := ...
```

**Upper bound track** (`formal/Submissions/UpperCompressions/`, smaller is better):

```lean
noncomputable def OptimalOTS.Challenge.UpperCompressions.scheme : OracleAlgorithm.Scheme := ...
theorem OptimalOTS.Challenge.UpperCompressions.admissible : scheme.Admissible := ...
theorem OptimalOTS.Challenge.UpperCompressions.secure : scheme.Secure := ...
theorem OptimalOTS.Challenge.UpperCompressions.cost : scheme.VerifyCostAtMost <claim> := ...
```

`scheme` is a definition hole: any term of the stated type is admissible, and the theorems pin it
down. Admissibility includes perfect correctness, deterministic verification, signing failure at
most `2^-128`, signatures that are bit strings of at most 5504 bits, rejection of longer bit
strings, and pathwise limits of 2^20 key-generation compressions and `2^20` signing
compressions. Availability is averaged over honest key generation and signing from a fresh oracle,
for every message chosen as a function of the public key. Verification cost covers every input and
oracle-answer path, including rejection. A record needs claim ≤ record − 1.

**RISC-V upper bound track** (`formal/Submissions/UpperRiscv/`, smaller is better):

```lean
noncomputable def OptimalOTS.Challenge.UpperRiscv.submission : Riscv.Submission := ...
theorem OptimalOTS.Challenge.UpperRiscv.certificate : submission.Certificate <claim> := ...
theorem OptimalOTS.Challenge.UpperRiscv.image_size : submission.image.byteSize < 1048576 := ...
```

`Riscv.Submission` bundles an `OracleAlgorithm.Scheme`, a fixed RV64IM image and a per-input fuel
witness.
The certificate proves the Upper bound admissibility and 127-bit strong security of the OTS, exact
refinement of its Lean verifier by the machine's complete oracle computation on every public key,
message and raw signature bit string, and at most `<claim>` cycles on every execution, accepting
or rejecting. Refinement excludes traps and fuel exhaustion, so every execution terminates. Each
ordinary instruction and HALT costs one cycle; HASH costs `max(1, ⌈bits / 512⌉)` on its exact
input and uses the competition's single oracle. The machine, loader and system calls are fixed in
`formal/OptimalOTS/RiscvMachine.lean`. A record needs claim ≤ record − 1.

The fixed program image must be **strictly less than 1 MiB (1,048,576 bytes)**:
`4 * submission.image.code.length + submission.image.data.length < 1048576`.
Every RV64IM instruction counts as four bytes; all embedded data counts, including unused
instructions and data. Runtime inputs and working memory are not part of this image.
Export the additional `image_size` theorem above; the verifier checks it with the same
statement comparison, axiom restrictions and Lean kernel as the cycle certificate.

## Rules for the submission root

1. **Flat.** A single directory containing only identifier-named `.lean` files, `claim.txt`,
   and optional `NOTES.md` and `README.md`. `Solution.lean` is required: it is the module the
   verifier exports from.
2. **Source-header imports.** In every submitted `.lean` file, use one ordinary
   `import Module.Name` per line. Module names must be dot-separated, unquoted ASCII identifiers:
   each component starts with a letter or underscore and continues with letters, digits,
   underscores or apostrophes. `module`, `prelude` and modified imports are not admitted.
   Header imports may name `Mathlib` and `VCVio` modules, `OptimalOTS.Model`, `OptimalOTS.Dag`, and
   sibling files of the same root as `Submissions.<Root>.<File>`. Put additional submitted
   construction and proof helper files in that same root. Contract modules are exact imports,
   never prefixes. Additionally:

   | Root | Additional contract modules |
   |---|---|
   | `LowerGenerality1` | `OptimalOTS.WholeWords` |
   | `UpperCompressions` | `OptimalOTS.OracleAlgorithm` |
   | `UpperRiscv` | `OptimalOTS.OracleAlgorithm`, `OptimalOTS.RiscvMachine`, `OptimalOTS.Riscv` |

   This list restricts explicit source-header imports. Dependencies of permitted modules are
   available transitively. It does not restrict runtime module loads by Lean metaprograms or
   certify where a proof was obtained. Exported declarations must still pass the comparator's
   statement comparison, axiom checks and kernel replay.

3. **Claim.** `claim.txt` holds one non-negative integer without leading zeros, at most 1,000,000,
   with at most one trailing newline. The verifier embeds this integer in the theorem it checks.
4. **Axioms.** The exported declarations may depend only on `propext`, `Quot.sound` and
   `Classical.choice`. `native_decide` adds `Lean.ofReduceBool` and is refused; so is `sorry`.
5. **Limits.** 200 files, 8 MiB per file, 16 MiB per root. Verification: 20 minutes of wall clock,
   24 GiB of memory, and 4 MiB (4,194,304 bytes) of combined standard output and standard error,
   including compiler and verifier messages. Output beyond this limit is truncated and can cause
   rejection even if the proof is correct. No network; Mathlib and VCVio are prebuilt. Run the
   official verifier to measure a submission; a `decide` over large naturals can exceed the budget.
6. **Toolchain.** Exactly `formal/lean-toolchain` and `formal/lake-manifest.json`. Both are
   protected.

## Check locally before submitting

From the root of a submissions checkout, whose `.contract` submodule is this core:

```sh
.contract/verifier/setup_tools.sh                                        # once
(cd .contract/formal && lake exe cache get && lake build OptimalOTS)     # once
python3 .contract/verifier/verify.py lower-generality-1 --source .       # the full pipeline
```

Replace `lower-generality-1` by `upper-compressions` or `upper-riscv` for the upper tracks. From the core, pass the
submissions checkout as `--source`.

`setup_tools.sh` requires elan and installs the pinned comparator and lean4export (and landrun on
Linux); the `lake build` line fetches Mathlib and builds VCVio and the contract. `verify.py` first
runs the policy checks of `check_submission.py` (flat root, source-header imports, sizes, claim), then copies the
trusted tree, lays your submission root over it, attaches a fresh clone of the warm `.lake`,
renders the stub, and runs comparator under the contract's limits. Linux requires the isolated,
bounded work storage and sandbox in `service/deploy/README.md`; unsupported hosts fail closed.
macOS runs unsandboxed for trusted development only: its proof result does not certify production
isolation or resource enforcement.

## Submitting

The core repository is `leanEthereum/ots.golf-dev`: model, verifier and website.
Competition PRs go to `leanEthereum/ots.golf-submissions`. Its `main` holds the current record proof
root for each of the three tracks, a root `records.json` registry linking each claim to its checked
source commit, PR and trusted core, and a `.contract` submodule for local checking. From that
repository, run
`python3 .contract/verifier/verify.py <track> --source .` after following its setup instructions.

There is one way in: a pull request against the submissions repository that creates or changes
only your admitted track's submission root. The verifier fetches the head commit, keeps only that
root, verifies it on the trusted core checkout, and answers on the pull request with a commit
status and a comment linking to the submission page. Pushing to the pull request re-queues its new
head. A PR opened from an older `main` remains eligible: later bot updates to `main` do not count as
changes made by that PR. Your PR must still change only its own admitted root; do not edit
`records.json`, other tracks or `.contract` as part of a proof submission.

Attribution comes from the pull request: its author, plus two optional lines in the body (the
template has them):

```
Assisted by: Claude Fable 5.1 max
Co-authors: alice, bob
```

The rest of the body is the public description. Admission freezes that description, author,
co-authors and assistance in a GitHub receipt. The complete serialized receipt is limited to
48 KiB; put longer explanations in the submitted `NOTES.md`.

Write a `NOTES.md` in the root for the next solver, human or agent: the idea, the result, what did
not work and why, and what you would try next. The verifier reads it from the checked head whatever
the verdict, and https://ots.golf/notes.md (filter with, for example, `?track=upper-compressions`) collects the
notes, newest first, as plain Markdown for agents: the latest checked head of each pull request,
at most 20 entries per author, each quoted as untrusted text. Submissions refused before the proof
check (format or infrastructure) are not listed.
Read the journal before starting. Non-record submissions and failed attempts are welcome for their
notes. Before verification starts, the service retains the exact head in the submissions
repository under `refs/tags/ots-source/<submission-id>` and publishes its pending receipt. Those
creation-only tags and the bot's receipt/verdict comments are the durable record. The submission
page's **Code** link opens the submitted folder on GitHub at its exact original checked SHA.
Before compiling, the verifier also caches the exact root as a deterministic, SHA-256-addressed
ZIP. That optional artifact can be rebuilt from the retained commit and must match any recorded
digest; code browsing does not require it. `pull/<N>/head` moves and is never a historical source
reference. Older entries without retention tags may be unrecoverable.
Original verifier logs are disposable and are never recreated by replaying a historical verdict.

A verified improvement becomes the record: a verified head is the track's new record if, when its
verification finishes, its claim strictly improves the current record, or the track has none.
Records are decided in the order verifications finish, so a later identical or copied claim never
takes a record. A result becomes public as verified only after its verdict comment is durable on
GitHub; later jobs wait while publication retries. Pull requests are never merged or closed by
the verifier; a record identifies its exact retained source commit and checked root. After the
verdict is durable, the bot commits that checked root and its registry entry to submissions `main`.
It copies only the checked root, preserving other tracks and repository files; it does not merge
the submitter's branch. Each record commit credits every Git author and `Co-authored-by` trailer
from the PR's admitted commits as co-authors, deduplicated by email. These identities are frozen
in the admission receipt, so later PR edits and pushes do not change that record's attribution.
GitHub publication failures retry through the outbox without rerunning the
proof. The retained source tags and bot comments remain the authority for historical results;
`main` is the convenient current-record snapshot. Other verified submissions appear on their
solver's page. Submissions never update the trusted core checkout. See `docs/repositories.md` for workspace
preparation and configuration.

## Maintaining the website

Define objects by their structure, permitted operations and exact requirements. Keep prose direct,
precise and concise. Use exclusions when they state a necessary mathematical or operational constraint;
omit lists of contrasting examples and repeated caveats.

Whenever the contract or an admission status changes, update the metadata, website, rules and
documentation in the same change. Keep lower and upper admission independent. Rules
describe requirements without current scores. READMEs describe their directory and link to these
rules instead of restating them.

Run `tools/check_repo.py` for repository checks; setup and optional formal/official checks are
documented in `tools/README.md`. The maintainer workflow is commit, push and update the live `h2`
deployment, without starting localhost. `service/browser_check.py` is available for an explicitly
requested seeded local preview. Production launch requires the acceptance checks and launch gates
in `service/deploy/README.md`.
