# Repository review — 17 September 2026

The checked certificates, service regressions, numerical checks and local browser audit pass.
The website and worker run the reviewed code on localhost. **Public deployment still requires
acceptance on the actual Linux host and a staging GitHub repository.** This review does not claim
that macOS testing establishes production isolation. Nothing was pushed or deployed. The original
operational review was committed locally as `1000826` on `main`; the later generic upper addition
is documented in [the generic proof report](../upper-compressions.md).

The review covered the formal contract and exports, verifier, queue/webhook/reporting service,
website, numerical tools, deployment configuration and documentation. Parallel reviewers owned
separate service, verifier and website files. That operational review did not change the protected
contract, certificates, claims, toolchain or pin. The subsequent generic upper addition changes
the challenge metadata and pin, with the underlying generic definitions preserved. The historical `Submissions/Upper` construction is untouched.

## Changes that matter

### Admission and operation

- Webhooks require the configured repository and a valid signature. Oversized or malformed payloads,
  malformed heads, renamed files outside the admitted root and truncated file lists are rejected.
  Admission rechecks the PR head and serializes quota decisions.
- Verification alone no longer promotes a PR. The verified head must also be confirmed merged by
  GitHub's API. A merge received before the result is retained and applied after verification.
- A durable GitHub reporting outbox retries statuses/comments independently of proof verification.
  Stored comment IDs allow updates. A crash between posting a new comment and saving its ID can
  still cause one duplicate on retry; this is documented, not an exactly-once guarantee.
- Process locks prevent concurrent workers and serialize shared database operations. A worker
  restart requeues interrupted work. Timeouts and termination clean up child processes and retain
  logs; malformed or inconsistent pipeline results cannot become verified records.
- Production web and worker processes have separate Unix identities. Only the web process receives
  GitHub credentials. Production settings validate the role, HTTPS origin, repository and secret;
  a credential-bearing worker refuses startup. Local startup also strips its GitHub credentials.
- Deployment now requires a dedicated bounded work filesystem. It leaves the services stopped
  until the acceptance checks pass. The guide covers backups, recovery, upgrades and monitoring.

### Verifier

- Submission exports enforce file types, names, counts and byte limits before copying. They reject
  symlinks, nested trees and special files, guard local file replacement/growth, and read Git blobs
  directly so `.gitattributes` cannot change the submitted bytes through archive attributes.
- Claims and imports receive stricter parsing. Git output is bounded and its subprocess groups
  are registered for cancellation. Existing `--work` directories cannot be overwritten.
- Linux verification refuses root, development shims and missing isolation. It requires Landlock
  ABI 3 or newer, systemd, a clean environment and enforced restrictions on networking, process
  control, `/proc`, `/sys`, devices and shared memory. The in-service launcher checks essential
  restrictions before starting comparator. Read-only system mounts also prevent metadata changes
  to trusted files; only the job’s `.lake` is writable. The actual-host probe tests filesystem, network,
  environment, process-memory and signal denial, including a live canary process.
- Each Linux job must live on a dedicated ext4/xfs or bounded tmpfs filesystem of at most 64 GiB,
  separate from persistent state, the trusted checkout/cache and the system. Nested mounts and
  loop-backed images are refused. Git staging uses that same bounded storage.
- The production memory/time limits remain 24 GiB and 20 minutes for comparator's process tree.
  macOS still uses comparator's development shim and is suitable only for trusted local checks.

### Website and maintenance

- The homepage states the question directly. The demo notice precedes the scores; fictional rows
  are identified on their submission and solver pages, without false verification badges or
  invented commit links. Existing Satoshi/Vitalik rows, dates and IDs are preserved.
- Light/dark contrast, keyboard navigation, narrow tables, chart targets, tooltip placement and
  reduced-motion behavior were checked and improved. Chart ticks stay bounded even for maximum
  allowed claims. Rules remain independent of scores, with the explanatory diagrams intact.
- Three lower frameworks and one generic upper track remain distinct. Legacy upper references
  are not relabeled. The subsequent generic upper certificate completes correctness, signing
  availability, security and cost; its challenge is pinned and the track is open.
- Inline scripts were moved into static files for the content security policy. Readable error
  pages and a database-aware health endpoint were added. Unused diagram code and obsolete CSS
  were removed. Demo tooling now refuses production mode and non-loopback origins.
- `tools/check_repo.py` provides one local regression command; `service/browser_check.py` provides
  a repeatable Firefox audit. Numerical search now charges node tweaks separately from the fixed
  message-and-nonce index, correctly reproducing the existing 106-cost forest.

## Original operational-review evidence

All checks used the existing trusted local Lean/tool caches. Unit tests use isolated databases
and temporary repositories. Browser checks read localhost and exercise its controls.

| Check | Result |
|---|---|
| Protected contract pin | Unchanged, passes |
| `lake build OptimalOTS Submissions` | Passes, 8,899 build jobs |
| `lake env lean scripts/check-axioms.lean` | Passes, expanded to 46 protected declarations |
| Verifier regression suite | 57 tests pass |
| Service regression suite | 56 tests pass |
| Numerical regression suite | 5 tests pass |
| Pinned comparator's upstream suite | 14 tests pass; macOS development shim |
| Static JavaScript and shell syntax | Passes |
| Locked Python environment | Dependency consistency and offline lock check pass |
| Paper | Builds, 9 pages |
| Firefox | Desktop and 320/390-pixel layouts, light/dark, keyboard, filters, tooltips, reduced motion and error pages pass |

The official verifier accepted every pinned certificate:

| Slug | Claim | Wall time |
|---|---:|---:|
| `generic-lower` | 1 | 151.6 s |
| `lower` | 18 | 191.9 s |
| `disclosure-lower` | 93 | 187.6 s |
| `upper` — historical reference | 106 | 250.1 s |
| `disclosure-upper` — historical reference | 106 | 247.3 s |

After the final verifier changes, the official Git-commit path also accepted `generic-lower` at
`1000826ac5bb2526dd3024d137c03a1a88f2bbf4`, claim 1, in 58.8 seconds. This exercises committed-byte
export and the final bounded subprocess helper; the log is
(local log). All five policy checks pass as well.

After the commit hook refreshed localhost, its homepage displayed the new commit, all 26 reachable
internal HTML links returned successfully, and all 19 demo rows retained their IDs, claims and dates.
The web server and worker were both restarted with the reviewed implementation. Documentation links
in the updated READMEs and reports also resolve.

These are macOS proof-pipeline results, not Linux sandbox acceptance. The permitted exported axiom
set remains `propext`, `Quot.sound` and `Classical.choice`; no `sorry` or `native_decide` certificate
was admitted. The numerical tests reproduce whole-word 93 and show that 94 is not established by
that same attack arithmetic. They also reproduce the DAG and historical disclosure calculations.

Local logs are under (local log); the integrated build/audit/paper log is
(local log), final regression results are in
(local log), and final browser screenshots are in
(local log). These are local review artifacts, not committed assets.

To reproduce, prepare the service, numerical and Lean environments described in the READMEs, then:

```sh
python3 tools/check_repo.py --numerics-python .venv-tools/bin/python --formal --official --paper
python3 service/browser_check.py --output-dir /tmp/ots-ui
```

The runner requires Node.js for syntax checks; `--node /path/to/node` selects an existing binary.
The browser runner requires Firefox and a running seeded localhost preview.

## Generic upper admission update

Commit `8a4afb5` adds the complete generic upper certificate and opens the single public upper
track. Perfect correctness is proved for every DAG adapter. The concrete forest's signing failure
is at most `2^-256` for every public-key-dependent message choice, satisfying the pinned `2^-128`
allowance. Strong 127-bit security and the 106-compression verification bound are preserved exactly.
See [the mathematical argument and proof map](../upper-compressions.md).

The new contract pin is `b2b1ffdeb02aa410fe2133b6b7e652f6f55ddf357eb0c5cd58dbb877792303b2`,
covering 22 files. The protected generic definitions have only an introductory comment change;
the three lower statements, original Upper root, toolchain and library manifest are unchanged.
The independent GenericUpper root passes policy with 30 files and 446,047 bytes. All 20 inherited
construction/security modules are exact copies except for sibling import paths.

Current checks pass: 59 verifier tests, 59 service tests, 5 numerical tests, JavaScript and shell
syntax, the complete Lean build (8,927 jobs), and the 46-declaration protected-model axiom audit.
The official verifier accepted every configured certificate against this pin:

| Slug | Claim | Wall time |
|---|---:|---:|
| `generic-upper` | 106 | 157.3 s |
| `generic-lower` | 1 | 66.3 s |
| `lower` | 18 | 107.4 s |
| `disclosure-lower` | 93 | 103.6 s |
| `upper` | 106 | 152.9 s |
| `disclosure-upper` | 106 | 150.3 s |

Two deliberate negative submissions also compiled successfully and were then rejected by
comparator's statement matching: changing only the claim to 105 was rejected at `cost` (127.2 s),
and replacing the admissibility theorem's fixed `2^-128` allowance with a proved one-half allowance
was rejected at `admissible` (120.0 s). The latter leaves security and cost unchanged, confirming
that availability is enforced independently. The test copies were outside the repository.
Results are in (local log) and
(local log).

Current Firefox checks pass on desktop and at 320/390-pixel widths, in light/dark mode, including
keyboard controls, sorting, tooltips, lower-only filters, four normal leaderboard tables, collapsed
rules, both diagrams, reduced motion and the HTML error page. The web process and worker were both
restarted after the implementation commit. The live footer shows that commit; 15 linked local
routes, including health, return successfully. All 19 prior demo rows retain their IDs, claims,
dates and attribution; only two separate generic upper demos were added, at 106 and 105. Fictional
rows remain labeled and are never presented as verified certificates.

Logs: (local log) and
(local log); browser screenshots:
(local log). These results do not replace the actual-host Linux isolation
or staging GitHub acceptance gates below. Nothing was pushed or deployed.

## Generality labels and rules presentation (2026-09-17)

The three lower classes are now displayed as Generality 3/3, 2/3 and 1/3. The Upper bound card
comes first and its chart line is solid. Rules explain the fixed budgets before the two tracks,
retain all admission requirements, and add a WOTS+ chain diagram. All nine sections start folded.

Only display metadata changed in the protected contract: framework titles and a historical title
for the original DAG upper reference. The new 22-file pin is
`491d82d7f56ef5885d2b1da0416063658f0b4cadb9f0c0353aec8a4a0ca6f644`.
Lean sources, challenges, claims and verifier requirements are unchanged; the official proof runs
above used the preceding pin and were not repeated for these presentation changes.

All 59 service tests and 59 verifier tests pass. Firefox checks pass on desktop and at 320/390
pixels, including the new labels, upper-card ordering, solid upper line, folded rules, three
diagrams, tooltips, filters and light/dark themes. Logs are in
(local log), (local log)
and (local log); screenshots are in (local log).

## Shared algorithm availability and concise presentation (2026-09-17)

Both algorithm challenges now fix signing failure at most `2^-128`. The generic lower export
specializes the retained lemma for every allowance at most one half; the certified claim remains 1.
The protected interface's mathematical definitions, both DAG lower statements and all upper proof
files are unchanged. The new 22-file pin is
`fd04517f1f73521d46ca98afb9c7e43d34df60f7d9fded3a1fdcb9817c3023fb`.

The official verifier accepted `generic-lower` at 1 in 53.0 seconds and `generic-upper` at 106
in 152.0 seconds. A temporary lower submission narrowed to failure at most `2^-256` compiled,
then comparator rejected its statement in 58.8 seconds. This checks enforcement of the exact
class quantified over. Results: (local log).

The full Lean build passed (8,927 jobs), as did the 46-declaration protected-model axiom audit,
60 verifier tests and 59 service tests. Logs: (local log)
and (local log).

The website and current proof guides now define objects through their structure and allowed
operations. Public prose calls injective encoding “lossless encoding.” The two framework
diagrams were removed; the WOTS+ list of message and checksum chains remains. All nine rule
sections start folded, with the bound direction explicit in framework headings. The Justin Drake
explanation remains alongside the actual-input cost rule.

Homepage lower cards explicitly say “Lower bound” and show compression units. At 1360 pixels,
the upper card is 24.0% shorter and each lower card is 25.3% shorter. Firefox checks passed
on desktop and at 320/390 pixels, with light/dark themes, controls, filters, tooltips and
horizontal scrolling. Screenshots and logs: (local log) and
(local log). Card measurements: (local log).

## Separate core and proof repositories (2026-09-18)

The core is `leanEthereum/ots.golf-dev`; proof PRs, result reporting and record promotion use
`leanEthereum/ots.golf-submissions`. `OTS_REPO_ROOT` still selects the trusted core checkout.
`OTS_SUBMISSIONS_REPO` is a separate, explicit admission setting. Rules, source links, setup
instructions and PR templates distinguish the repositories. The protected contract is unchanged.

Each PR's base repository is retained in its stored URL. Tests cover core-repository webhook
rejection, a forked submission checked by the core verifier, identical PR numbers and heads in
different repositories, and old outbox jobs remaining separate without blocking new reports.
The workspace preparation tool creates only the four public roots and a pinned core submodule,
refuses dirty sources or existing destinations, and performs no network or publishing operations.

Local validation: `tools/check_repo.py` passes 68 service tests, 60 verifier tests and 7 tooling
tests, plus JavaScript and shell syntax checks. The Firefox audit passes desktop and 320/390-pixel
layouts, rules, filters, keyboard controls and demo presentation. Both localhost processes were
restarted with the new settings. All 21 demo rows retain their IDs, dates and scores.
Evidence: (local log), (local log)
and (local log).

All four exported roots pass policy checks; their 83 files match the core references byte for byte.
The official verifier accepts submissions commit `da16887`, using core commit `402365c`:
`generic-lower` at 1 in 81.8 seconds and `generic-upper` at 106 in 173.3 seconds. These macOS
checks validate the proofs, not production isolation. Results:
(local log).

The empty GitHub submissions repository was cloned locally, then populated with that same
verified commit and pinned core submodule. The new commits remain local; no remote branches
were changed.

These checks use mocked GitHub APIs; webhook installation, token permissions and real GitHub
acceptance remain launch tasks. This change does not deploy or publish either repository.

## Gates before public launch

Follow [the deployment guide](../../service/deploy/README.md) on the intended host. Do not infer any
of the following from a successful local proof check:

1. Run the Linux isolation probe and every configured official certificate under the deployed identities.
   Exercise memory exhaustion, timeout and a full work volume. Confirm complete process cleanup,
   preserved website/database availability and refusal when isolation is unavailable.
2. Confirm web credentials are unreadable to the verifier identity, effective systemd restrictions,
   HTTPS/proxy configuration, private backups and a successful database restore.
3. In a staging GitHub repository, test signed and duplicate webhooks, rejection, verification,
   merge-before-verification, API outage/recovery and worker restart. Only an API-confirmed merged
   head may become a record. The local tests mock GitHub and cannot replace this check.
4. Before upgrading an existing deployment, audit historical real rows marked `is_record` against
   their merged PRs: the previous implementation promoted at verification time. An automatic
   rewrite would risk discarding legitimate history, so this review makes no such migration.

The host bootstrap downloads system tooling and is not a reproducible operating-system image.
No online dependency-vulnerability scan, public load test, live GitHub mutation or Linux runtime
acceptance was performed. This is a single-host deployment; the process locks are not a distributed
queue protocol. Review those constraints before changing the deployment topology.

## RISC-V upper bound track certified and admitted (2026-09-18)

`formal/Submissions/RiscvUpper/` now holds a complete `Riscv.Submission.Certificate` at
**229113 cycles**: the fixed-layout forest OTS, its 114557-instruction RV64IM verifier
image, a proof that the image's complete oracle computation equals the certified Lean verifier on
every public key, message and raw signature bit string (so every execution terminates, including
rejections, with the specified queries in the specified order), and the accepting-execution cycle
bound. `Solution.lean` exports `OptimalOTS.Challenge.RiscvUpper.{submission,certificate}` with
`claim.txt` 229113. The certificate uses only `propext`, `Classical.choice` and `Quot.sound`.
The proof map is in [the track notes](../upper-riscv.md).

The metadata now admits two upper tracks through top-level `upper_tracks`
(`generic-upper`, `riscv-upper`); the three frameworks classify lower bounds only, and
`frameworks.generic.upper_track` was removed. The new track has `cost_unit` "cycles",
baseline 229113, the RISC-V challenge stub and comparator configuration as protected files, and
imports limited to `Mathlib`, `VCVio`, `OptimalOTS.{Statement,Algorithm,RiscvMachine,Riscv}`
plus siblings. The new 26-file pin is
`c5d61d622981c63015fc2215817cdaf16efcc4b1be620dd4aee827cc0f690c41`. The protected Lean
interfaces and every other track's statement, claim and root are unchanged.

The official verifier accepted `riscv-upper` at 229113 against this pin in 547.2
seconds on macOS; the run compiles the whole root, including the kernel-checked image validity
and cycle-cap decisions, well inside the 20-minute limit. The policy check reports 69 files and
816,043 bytes in the root. Every other configured certificate was re-verified against the same pin:

| Slug | Claim | Wall time |
|---|---:|---:|
| `riscv-upper` | 229113 | 547.2 s |
| `generic-upper` | 106 | 142.3 s |
| `generic-lower` | 1 | 70.6 s |
| `lower` | 18 | 119.4 s |
| `disclosure-lower` | 93 | 116.7 s |
| `upper` | 106 | 139.1 s |
| `disclosure-upper` | 106 | 141.7 s |

Results: (local log) and
(local log). The workspace preparation tool and its
test now export five public roots.

The website shows the checked claim as a separate "RISC-V upper bound" card, leaderboard and
chart with an independent cycle axis; compression bounds are never combined with cycles. Rules
gained a folded RISC-V section stating the machine, refinement, termination and accepting-cycle
requirements, without scores. One Satoshi-attributed demo fixture at zero improvement seeds only
when the track is admitted; all 21 earlier demo rows keep their IDs, dates, claims and attribution.

Checks: the complete Lean build (9008 jobs), the 65-declaration protected-model axiom audit and
the RISC-V machine boundary checks pass (local log);
61 verifier tests and 75 service tests pass (local log);
the Firefox audit passes on desktop and phone widths, both themes, the two upper charts and
their tooltips, five leaderboard tables, folded rules and the eye animation
(local log).
These macOS runs validate the proofs and presentation, not production isolation. Nothing was
pushed or deployed; the submissions checkout is pinned to the local core commit.

Hal Finney joins Satoshi and Vitalik as the third fictional contributor, with five fixture rows:
the current Generality 2/3 demo record (21, after Satoshi's 20), a Generality 1/3 attempt at 94
that did not beat the earlier record, an Upper bound row at the checked 106, and one mid-history
102 record on each legacy upper reference. No earlier row, ID, date or record changes; the demo
count tests now expect 27 rows with every track admitted.

## Compact RISC-V certificate at 24053 cycles (2026-09-18)

The RISC-V root now certifies a compact image: `CompactProgram.lean` keeps one 32-byte slot per
chain, group and subtree, hashes in place, runs one guarded hash sweep and one guarded read sweep
per chain level, and assembles the tree inputs in a scratch buffer. The image has 24058
instructions and the same 70272-byte decoder table. `CompactVerifier.image_refines` proves
`Riscv.Refines 24058 (initialState image pk m bits) (some <$> directVerify pk m bits) 24053`:
the observed oracle computation equals the certified verifier on every input, so every
execution terminates, and every terminating execution costs at most **24053 cycles**
(one per instruction, two for the 912-bit root hash; guarded blocks and the 14619-instruction
decoder are charged in full). `Solution.lean` exports the certificate at 24053 with `claim.txt`
24053, using only `propext`, `Classical.choice` and `Quot.sound`. The proof map is in
[the track notes](../upper-riscv.md); the earlier 229113-cycle image and proof remain in the root
as references.

`challenges.json` sets the `riscv-upper` baseline to 24053; the protected pin was regenerated and
the cost unit is now simply "cycles" in the contract docstrings, the metadata, the website and the docs,
the RISC-V chart lost its redundant caption, and the contract id is
`2604d3fe599b404cc4c285f96c2ba984f6bd83b38254480238514f4b59d50e03`. The
Satoshi demo fixture keeps zero improvement, so the local preview shows the new baseline. The
official verifier accepted `riscv-upper` at 24053 in 353.6 seconds on macOS
(local log); the policy check reports 79 files and 1,086,640 bytes.
61 verifier tests, 75 service tests and 7 tooling tests pass. Nothing was pushed or deployed.

The front page was trimmed at the same time: one chart area shows compressions by default with a
segmented switch to the RISC-V cycles chart, the chart headings lost their direction hints and
the RISC-V caption, the tagline no longer mentions the three frameworks, and the RISC-V card
says "Verification cost", and the rules page frames the objective as the worst-case verification
cost in compressions or RISC-V cycles rather than compressions alone. Six fictional RISC-V rows give that chart a history: Hal Finney and
Vitalik Buterin trade records from 30053 down to 25053 cycles with one non-record attempt, and
Satoshi's zero-improvement record stays the current one, so the demo now seeds 33 rows with every
track admitted. The Firefox audit passes with the switch exercised
(local log).

## Signing budget tightened to 2^20 (2026-09-18)

`paperParams.trialLimit` and `paperLimits.signCost` drop from 2^21 to 2^20 compressions. The
forest signer accepts a nonce with probability 2^-13, so the previous cap proved signing failure
2^-256 against a requirement of 2^-128; 128 blocks of 8192 trials give exactly 2^-128, which is what
the two forest availability proofs now state. The lower-bound roots that bounded the fresh-signing
rate by 256/257 now use 128/129, the attack budgets shrink accordingly, and every certificate
rebuilds unchanged otherwise. The protected pin was regenerated (contract id
`b78f6d7d47d3d241df20140f9e5e1a90aa0b5f1f60e58dfc7e15e4b0336e8400`); the rules page, agent
instructions, `llms.txt` and the proof notes say 2^20. The rules page also presents the tracks as
two groups, upper bounds by compressions or RISC-V cycles and lower bounds by generality, and the
one-time-signature figure is a compact monochrome four-chain diagram with a fixed-target encoding.

## Strong unforgeability on every track (2026-09-18)

The three lower-bound statements (`VerificationLowerBound`, `WholeWordVerificationLowerBound`,
`AlgorithmVerificationLowerBound`) now quantify over strongly `Secure` schemes, the notion the upper
track already proves, so the rules describe one security experiment. The lower-bound attacks still
forge on a new message: `Statement.lean` gains `Scheme.Secure.weaklySecure`, a bridge lemma showing
that every strong DAG scheme is weakly secure (mirroring `AlgorithmScheme.Secure.weaklySecure`), and
each lower root applies it once. The certified bounds 18, 93 and 1 are unchanged. The protected pin
was regenerated (contract id `efa16b82ba5760cecc53174860b73e44e6cfd6461b4c56908d9b439713947049`),
and the challenge stubs, rules page, README, agent instructions and proof notes say "secure" instead
of "weakly secure".

## RISC-V certificate at 19627 cycles: exact chain accounting (2026-09-18)

The RISC-V certificate now charges the guarded chain sweeps by the path actually executed instead
of their code length. `PureBlock.cost` and `steps_exact` (StructuredPure) give the exact
instruction count of a structured block, `Refines.block_exact` turns it into a cycle bound, and the
chain segments charge 9 or 4 cycles per guarded read and at most 9 or 3 per guarded hash step. Since
every chain is read once and hashed `14 - position` times, and the positions of a composition sum
to 121, the chain phase costs 4584 cycles on every index (`CompactCost.chainsCost_le`), down from
the 9010 instructions it occupies. The claim drops from 24053 to **19627**; the decoder is still
charged as straight-line code. The whole certificate rebuilds, the baseline and protected pin were
regenerated, and the fixture history keeps the same displayed cycle counts.

## RISC-V certificate at 9041 cycles: exact decoder accounting (2026-09-18)

The position decoder is now charged by the path actually executed. `DecoderCost.lean` defines the
data-semantics cost `decoderCost` of a structured block, proves it equal to `PureBlock.cost`, and
computes one candidate at 23 instructions while the digit is searched and allowed, 4 when it
exceeds the remaining sum (never reached before selection) and 1 once a digit is selected. The
abstract scan cost `scanCost` follows the same `SlotRep` invariant as the correctness proof, so a
slot that selects digit `d` costs `38 + 22 d`, the 36 slots cost `36 · 38 + 22 · 121` because the
selected digits form a composition of 121, and `decoderBlock_cost` gives exactly 4033 cycles on
every index. `CompactVerifier.image_refines` charges it through `Refines.block_exact`; the claim
drops from 19627 to **9041** (36 + 4033 + 4584 + 240 + 100 + 36 + 12). The certificate uses only
`propext`, `Classical.choice` and `Quot.sound`; the official verifier accepted `riscv-upper` at 9041
in 335.8 seconds on macOS, 75 service tests pass, the baseline and protected pin were regenerated
(contract id `d42e3243fec87a692e19f55dec49bf210826556a002eec94904ea37ec068f483`), and the fixture
history keeps the same displayed cycle counts. Nothing was pushed or deployed.

## RISC-V certificate at 5513 cycles: the nibble scheme (2026-09-18)

The RISC-V OTS now reads its chain positions directly from the index instead of unranking a
composition. The index (the 128-bit prefix of `H(message ‖ nonce)`) is accepted when its 32
nibbles are at most 14 and sum to 166; chain `k < 32` is disclosed at position `14 - nibble k`
and chains 32 to 35 at position 14, in the same forest graph and fixed layout as before. Exactly
`comp 32 166 = 42088166900081964050093337199455360 ≥ 2^115` indices are accepted
(`Valid.card_validSet`), so the `2^20` signing trials fail with probability below `2^-128` as
before. Because the contract's paper scheme accepts an index when it is below `numSets`, the root
now carries `GScheme.lean` (the same graph scheme with the acceptance predicate `i ∈ validSet`) and
the forest security proof ported to it; the RISC-V contract (`OptimalOTS.Riscv.Submission`) is
unchanged. The scheme verifies in 186 compressions (was 141).

The machine replaces the 14619-instruction decoder by a 238-instruction straight-line nibble sweep
that checks the index and stores the 36 positions (`Program.nibbleChecks`, proved through the
`Swept` invariant in `IndexChecks.lean`); the chain sweeps now hash 166 steps. The claim drops from
9041 to **5513** (271 + 4854 + 240 + 100 + 36 + 12); the image has 9674 instructions and no table
data. The decoder files (`DecoderArithmetic`, `DecoderProof`, `DecoderCost`, `TableLoader`,
`Unrank`) and the unused earlier-image proofs (`VerifierProof`, `DirectCost`, `LengthGuard`,
`NodeExecution`, `ReconstructionExecution`, `DecisionProof`) were removed. The certificate uses only
`propext`, `Classical.choice` and `Quot.sound`; the official verifier accepted `riscv-upper` at
5513 in 275.8 seconds on macOS; the policy check reports 72 files and 989,283 bytes; 61 verifier
tests and 75 service tests pass; the baseline and protected pin were regenerated (contract id
`445712c7c5c3732ca3e6b3dcab9a07d8e9a04e383d2c825576ca8a513a3b67f5`), and the fixture history keeps
the same displayed cycle counts. Nothing was pushed or deployed.

## Deterministic verification (2026-09-18)

Verification is now deterministic by rule. `OptimalOTS.Deterministic P oa` says that every query of
an oracle program, on every path, goes to the hash oracle; `AlgorithmScheme.VerifyDeterministic`
applies it to `verify` on every input, and `Admissible` gained the field `verifyDeterministic`. The
RISC-V machine lost its RANDOM system call (`RiscvMachine.execute` handles HALT and HASH only, so a
run is determined by the oracle's answers), and the RISC-V cost invariant lost its random step. The
upper roots prove the new requirement in `Deterministic.lean` (bind, map, hash and fold lemmas, then
`Graph.deterministic_reconstruct` and the scheme's `verifyDeterministic`); the wire adapter forwards
it. Key generation and signing keep their private randomness. The lower-bound statements assume
`Admissible`, so they now range over schemes with deterministic verification, the intended class.
The rules say so in one sentence, and the RISC-V paragraph no longer mentions random choices.

Every submission root builds (`lake build` of each `Submissions.<Root>.Solution`; the default target
covers only the contract), the two upper certificates still use only `propext`, `Classical.choice`
and `Quot.sound`, the official verifier accepted `riscv-upper` at 5513 in 282.0 seconds and
`generic-upper` at 106 in 138.7 seconds on macOS, 61 verifier tests and 75 service tests pass, and
the protected pin was regenerated (contract id
`27f6f6075e03a41926be719725ed06703142cca150da380503c0364518661d03`). Nothing was pushed or deployed.

## RISC-V certificate at 1632 cycles: one block per chain (2026-09-19)

The chain phase no longer sweeps level by level with a guard per chain and level. The forest nodes
are numbered chain-major (`src k` at `43k`, `ci k t`, `ch k t`, `cv k t` at `43k + 1 + 3t`,
`43k + 2 + 3t`, `43k + 3 + 3t`; tree nodes unchanged from 2709), and `ForestVerifier.order` lists
each chain completely before the next. The security proof and the explicit verifier needed no
change beyond `Name.idx`, `Name.ofFin` and `order`, and the contract is untouched. Each of the 36
active chains is now one 55-instruction block: a 13-instruction prologue copies the chain's
disclosed word into its slot, loads its position `p` and jumps (`AUIPC`/`JALR`) to entry `p` of
a 14-step hash table, at 3 instructions per step. `CompactChains` proves one block against the
specification (`prefix_run`, `prologue_refines`, `step_refines`, `steps_refines`,
`chain_refines`, `inactive_refines`), and `CompactLevels.chainsFrom_refines` composes the 63
chains. The chain phase costs `7 + 36 · 13 + 3 · 166 = 973` cycles on every accepted index
instead of 4854, so the claim drops from 5513 to **1632** (271 + 973 + 240 + 100 + 36 + 12) and
the image from 9674 to 2651 instructions.

The certificate uses only `propext`, `Classical.choice` and `Quot.sound`; the official verifier
accepted `riscv-upper` at 1632 in 210.9 seconds on macOS; the policy check reports 73 files and
975,211 bytes; 61 verifier tests and 75 service tests pass; the baseline and protected pin were
regenerated (contract id `2461d3b5a189f6ad9d7e730bad5b38ea7c30e2b9d56bc943c9457ee7f6623fe4`). The
invented RISC-V demo history was scaled with the record: it now runs from 2070 down to 1860 cycles,
one non-record at 1890, then Satoshi at 1632, the same 14 to 27 percent above the record as
before. Nothing was pushed or deployed.

## Stateless server: the database is a cache of GitHub (2026-09-19)

**Superseded:** the retention claim in this historical section was incorrect: PR head references
move on later pushes. The current verifier retains exact source archives locally, and operators
must back them up. See the [current recovery procedure](../../service/deploy/README.md#rebuilding-the-server-from-nothing).

The server no longer holds anything that cannot be recreated. Verdicts are written into a hidden,
machine-readable block of the verifier's own pull-request comment (every checked head of that PR:
track, commit, status, claim, duration, finish time, contract id, record flag), submission IDs are
derived from the pull request and commit, and `app.resync` rebuilds the database from GitHub at
startup: authors, descriptions and attribution from the pull requests, `NOTES.md` from each checked
commit (GitHub keeps every head under `refs/pull/<N>/head`), verdicts only from the bot's comments,
and records by replaying the merges in merge order. Open heads without a verdict are queued again.
At every start the website also prepares the board: with `OTS_PHONY=1` (the default while the site
is pre-launch) it re-seeds the invented rows from the fixture file, with `OTS_PHONY=0` it creates the
reference baselines of the public tracks from `challenges.json`.

The earlier branch archiving (`submissions/<id>` branches, which needed contents write) was reverted:
the pull-request refs already keep each checked head, so the GitHub token stays read-only for
contents. Rebuilding a server needs only `secrets.env`; old verifier transcripts are the one thing
lost. 85 service tests cover the verdict block, forged comments from other accounts, the rebuild,
record replay, stable IDs and board preparation. Nothing was pushed or deployed.


## 128-bit nonce (2026-09-19)

The contract moves from a 256-bit to a 128-bit signing nonce: `paperParams.nonceBits := 128`,
`paperLimits.signatureBits := 5376` (the 5,248-bit payload budget `maxRevealBits` is unchanged,
so only the nonce bits leave the signature), and the RISC-V loader reads at most 5376 signature
bits with the length register capped at 5377. The index query `H(message ‖ nonce)` now has 384
bits and still costs one compression.

The old signing charge `trialLimit · pairs / (2^nonceBits − trialLimit)` needed about 148 nonce
bits. It is replaced by a disjoint signing lemma (`SignRho.signRho_bound`) and a row potential
`θ Ψ` whose expected growth per encoding query is at most `(11/6) θ ε ≤ 2ε`
(`RowPotential.psi_charge`, from `RowIneq.charge_le`), with the full proof in
[the analysis](../nonce-128-analysis.md). The security bound `(B − 912)/2^127` holds for every budget, as
before. The proof is ported to `GenericUpper`, `RiscvUpper`, `Upper` and `DisclosureUpper`; the
lower roots build unchanged.

Claims: `generic-upper` 106, `upper` 106, `disclosure-upper` 106, `lower` 18,
`disclosure-lower` 93 and `generic-lower` 1 are unchanged. `riscv-upper` drops from 1632 to
**1628 cycles**: the index prefix copies one nonce block instead of two (2647 instructions, index
phase 267 cycles), and the baseline and demo fixture follow.

All seven roots are kernel-checked with only `propext`, `Classical.choice` and `Quot.sound`. The
protected pin was regenerated (contract id
`de0431ce8bbe4fac4b9d788b0ab5c308bdf45df8c85abb299179ec3754811d69`). 88 service tests, 62 verifier
tests and the policy check of all seven roots pass. The official verifier accepted, on macOS:

| Track | Claim | Wall time |
|---|---:|---:|
| lower | 18 | 39.8 s |
| disclosure-lower | 93 | 45.7 s |
| generic-lower | 1 | 20.0 s |
| generic-upper | 106 | 97.8 s |
| riscv-upper | 1628 | 218.2 s |

Nothing was pushed or deployed.
