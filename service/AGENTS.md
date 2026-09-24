# Live maintenance and optional local development

The current maintainer workflow is commit, push, then update the live deployment on `h2`.
No localhost preview or post-commit refresh is required. Do not start local web or worker processes
unless the user requests local development. Run isolated tests before publishing changes, stop the
live worker before replacing its trusted checkout, and verify the deployed pages after an update.
The deployment guide owns host prerequisites, acceptance checks and recovery.

`OTS_PHONY=0` is the default for both web and worker: show real submissions only. Existing demo
rows keep their IDs and dates but remain hidden and cannot affect records. All three boards start
without records when there are no real verified submissions. Reference proofs reach the site as
ordinary pull requests; no baseline scores belong to the contract.

For explicitly requested local development, `./run-local.sh` starts the worker and web process.
Set `OTS_PHONY=1` to opt into the labeled demo fixtures. Preserve fixture IDs/dates when refreshing.
`seed_demo.py` refuses production mode and non-loopback site URLs, even with `--force`; never force
it against production. `demo/README.md` owns the fixture policy: each track's best demo claim equals
a claim proven in the reference proofs, and older rows may be worse. Keep fixtures, metadata,
admission status, charts, leaderboards and rules aligned.

GitHub holds durable source tags `refs/tags/ots-source/<submission-id>` and the bot's frozen
receipt/verdict comments. After a new verified record's verdict is durable, the bot commits only
its checked root and the corresponding root `records.json` entry to submissions `main`. Preserve
other tracks and repository files. This is a current-record snapshot, never a PR merge; source tags
and comments remain the historical authority. Record commits include `Co-authored-by` trailers
for every Git author and co-author of the admitted PR commits. Freeze the deduplicated identities
in the GitHub admission receipt and preserve them during recovery; never substitute the authors
of a newer head when publishing an older checked revision. Keep snapshot publication retryable through the
outbox without rerunning verification. Older-base PRs remain eligible when they change only their
own admitted root. The server needs no backups: the database and exact source ZIPs are
rebuildable caches; original logs are disposable. Preserve the admission and verdict publication
gates, reporting retries, immutable source identity and digest checks. `python -m app.rebuild`
restores metadata; `--sources` also reconstructs ZIPs, without compiling historical submissions.
The primary Code link opens the submitted folder on GitHub at its original checked SHA. Do not
replace it with a moving `main` link, a ZIP download or a shell fetch command. ZIPs remain optional
compatibility artifacts. Never create replacement logs by rerunning an already published verdict.
See `deploy/README.md`.

The lower-bound track covers whole-word DAGs. Its public name is “Whole-word DAGs”; keep
the stable slug/root `lower-generality-1`/`LowerGenerality1`. There is no lower-framework selector.
Keep the compression lower bound separate in scope from the unrestricted upper constructions.
Removed tracks are not admitted or displayed on active boards, including stored historical and demo rows.
The Hall of Fame separately preserves real verified submissions retired by rule changes.
Preserve `#lower` and `#upper` links.

Upper tracks are admitted through the top-level `upper_tracks` metadata, independently of the
whole-word lower track. Derive the set of upper tracks from that metadata — `contract.upper_tracks()`
— and never from a hard-coded list: a registered track that the service does not derive is
refused at admission while appearing everywhere else. Each upper track's own metadata drives its
presentation: `focus` is the phrase that distinguishes it wherever the site names it (“Upper
bound · {focus}”, “By {focus}”), `tab_label` is its segmented-control button, `cost_unit` its
unit, and `cost_note` an optional sentence rendered under its card. Every admitted upper track
has a distinct non-empty `focus`.

`upper-compressions` is “Upper bound”, measured in compressions. `upper-riscv` is “RISC-V upper
bound” and `upper-leanisa` is “leanISA upper bound”, both measured in cycles; a cycle track gets
its own card, chart panel, leaderboard panel and rules section, all rendered only while the track
is admitted, and its chart has an independent cycle axis. DOM hooks are derived from the slug
(`data-upper`, `data-chart`, `{slug}-dashboard`, `{slug}-chart-points`,
`{slug}-record-chart`), so adding a track needs no JavaScript change.

The two cycle tracks differ in what their claim covers. `upper-riscv` bounds every execution,
accepting or rejecting; every execution must terminate and refine the Lean oracle specification.
`upper-leanisa` bounds every *completing* execution over every prover-committed memory — rejecting
runs do not exist in that model and are not charged — and every leanISA claim carries a fixed
surcharge for re-deriving the public statement inside the machine. Both cycle tracks also carry
a proved instance-size bound the score cannot see, exported as a second theorem and checked by
the comparator: `image_size` for RISC-V, `seeded_rows` for leanISA. State that surcharge wherever
the score appears, and never present the two cycle totals as comparable: the per-hash prices
differ by a factor of ten, which no constant absorbs.

Show the current whole-word lower record as a dotted cycle reference only on a track that
declares `cycles_per_compression`, linked to its original submission, at
`cycles_per_compression · claim + fixed_cycles`. That reading is sound only where a whole-word
DAG verifier is implementable: RISC-V's `HASH` takes an input of any length, so it declares the
price; leanISA's `BLAKE2S` fixes every query at 896 bits, so it declares none and gets no line.
Label the whole-word scope explicitly; it is not a lower bound for unrestricted submissions on
that track. Derive the value from the eligible record, omit it when there is none, and mark demo
references as demos. The compression upper line remains solid. Upper leaderboards stay outside
the lower-framework filter. The lower-bound witnesses (`formal/Witnesses/`, checked with `lake build Witnesses`) are an
internal maintainer check, not tracks: they have no slug, submission root, demo rows or leaderboard.
When demos are explicitly enabled, include the lower demo rows.
Preserve every fixture row with its ID and dates. A track's card, chart point, leaderboard,
submission page and solver profile refer to the same record row. Demo rows are clearly marked and
never receive verified badges or fabricated commit links.

Keep a small `llms.txt` link in the footer beside the GitHub links. Keep the homepage paragraph
beginning “Start with the rules” removed. The rules and exact proof PR destination remain at the
top of `/llms.txt` and above the rules page's collapsed sections. `/rules.md` serves the submission specification
from the deployed root `AGENTS.md`, ending before its maintainer section. Keep that boundary and
its regression check aligned; do not duplicate the specification in a second hand-maintained file.

Keep the rules concise and independent of current scores, candidate results and proof history.
Keep all key admissibility, cost, security and submission requirements available on the rules page;
use titled sections that are all collapsed on a fresh visit, beginning with “What is a one-time
signature?”. Teach the concepts before the exact requirements, and keep diagrams inside the
relevant sections. Combine overlapping topics and keep introductory explanations brief, linking
to reliable background reading (such as Wikipedia for Lamport and ePrint 2025/055 for target-sum Winternitz) instead of
repeating tutorials. Keep competition-specific requirements on the page. Preserve direct links
that open the requested section. Whole words uses independent
128-bit sources, fixed public 128-bit words, 256-bit hash outputs with two selectable halves, and
concatenation of whole-word sequences. Concatenations can reorder, repeat or be empty; no other
deterministic operations, smaller fragments or encodings are admitted. Hashing an empty input is
allowed and charged. Hash inputs have no fixed arity;
charge their complete length. A 5,376-bit payload fits at most 42 words, plus the 128-bit nonce.
The framework definitions use prose; keep the removed DAG and whole-word diagrams out of the rules.
Whole-word lower uses the slug/root `lower-generality-1`/`LowerGenerality1`, with
explicitly labeled demo rows. Do not leave the old 46-origin rule on the site.
`seed_demo.py --refresh` preserves existing rows. Run isolated checks with
`.venv/bin/python -m unittest discover -s tests -v` from `service/` after changing this behavior.

After deploying worker code, restart the live worker as well as the web service. Keep one worker
per data directory. Production web and worker run as different Unix users; only the web process
receives GitHub credentials. The bot creates retention tags, writes receipt/verdict comments and
commit statuses, and commits new record snapshots to submissions `main`. It never merges or closes
pull requests or changes an existing source tag. The bot's authorized `main` ruleset bypass must
not grant bypass of source-tag update/deletion protection.
On production web startup, synchronize the submissions `.contract` pin to the deployed core in
a separate bot commit. Retry publication failures and preserve concurrent edits. Never repin from
local previews, overwrite proof roots, or automatically roll a pin back to an older/divergent core.
Verify synchronization in the deployment journal and on GitHub after each deployment.
Draft PRs are not admitted, including during startup resync. The `ready_for_review` webhook
admits the current head through the same checks as a new PR. Recheck draft status before queueing.
A verified improvement becomes public only after the verdict comment is durable, with record
ordering determined by verification-finish time under the results lock. Preserve reporting retries. Never bypass Linux isolation or bounded-storage
checks to make a host pass. See `deploy/README.md` for the launch gates.

Use `browser_check.py` for repeatable Firefox checks of the seeded local preview. Keep demo labels
on individual entries and submission/profile pages; fictional rows must not present kernel
verification badges or fabricated commit links. A passing macOS proof check does not establish
production sandbox safety.

Keep the homepage headline “Think one-time signatures are easy? Prove it.” The mandala forms
the iris of a shaded, lit eye whose pupil is the root. Each cycle, current leaves every revealed
value and flows along the recomputed edges to the root at one constant speed; a node lights when
all its inputs arrive. Once the root is reached the eye blinks, and a fresh uniform signature is
lit only while the eye is fully closed. The eye fills its illustration column. Reduced motion
shows a static lit signature; pause automatic motion when the page is hidden.
Keep the homepage concise: each upper card shows
its linked title, attributed record and cost; detailed requirements belong in the rules.
Do not restore the removed paragraph beginning “Each lower-bound class has its own optimum.”
Keep the heading “One upper bound. Three lower bounds.” removed from the homepage.
Keep the “Local demo leaderboard” explanatory banner removed; retain individual demo tags.

Use “Upper bound” as the public track name throughout the site, not “Generic upper”. Use the
`upper-compressions` identifier for URLs, data and verification. Show its score card before
the lower card and draw its chart line solid. Explain in the rules that any oracle algorithm
is allowed. Introduce the competition through fixed size, security and key-generation/signing
budgets, with worst-case verification cost as the quantity to minimize. Present the upper tracks and lower direction,
then the whole-word lower class; do not invent percentages for their degree of generality. Keep the
target-sum Winternitz illustration as a list of chains from secret to public endpoint: the message is encoded as
digits with a fixed sum, one per chain, the signature reveals the value each digit selects, and
the verifier hashes forward to the endpoint. Do not restore
the removed background-reading disclaimer or historical-certificate paragraph in the rules.
Keep the compression-cost rationale crediting Justin Drake: a per-key public parameter can be
absorbed once as a full prefix block and its hash state reused. This motivates no implicit
per-query surcharge; it does not exempt bits explicitly present in an oracle input from cost.

Keep the public lower name “Whole-word DAGs” and the upper model name “Oracle algorithms”.
The oracle model remains necessary for both upper certificates; it is not a lower-bound track.

Keep the homepage score cards compact, with the correct cost unit beside every score.
Oracle-algorithm signatures are plain bit strings; say so directly in public prose.
Name the bound direction explicitly in each score-card and framework rule heading. The algorithm
rule section covers upper constructions; the RISC-V section states
its machine, refinement, termination and cycle requirements, the cycle bound covering every
execution.

## Maintainer workflow

The Hall of Fame is a frozen historical catalog in `service/hall-of-fame.json`, grouped by
rule change. Preserve every real verified submission affected, including earlier records and
non-record submissions; exclude demos and failed attempts. Freeze authorship, original score,
checked source SHA/root, verdict contract ID and verification date. Link the original rules
and the retirement commit. Append future rule changes rather than rewriting prior results.
This display catalog is independent of admission, current records and the server database;
a fresh checkout can render it without reconstructing the database. Old submission-page URLs
redirect to their catalog entry when they are no longer visible on the active site.

Preserve the approved compact RISC-V table: Instruction, Count, Share of run, with HASH price
in parentheses beside its input length. Do not add summary bars, metrics or explanatory prose.
Owner profiles come only from `riscv-profiles.json` on the configured submissions repository's
`main`, keyed by submission ID and pinned to its checked source SHA and contract. Keep this
display metadata separate from proof intake, verdicts, records and the checked roots. The
record bot must preserve it, including concurrent owner edits. Refresh it in the background;
never fetch GitHub while rendering a submission page. GitHub is the durable store, and removal
of an entry removes its table. The demo fixture is confined to its explicitly enabled demo row.

Show two separate RISC-V image metrics on the record card, leaderboard and submission page:
the static instruction count and embedded-data bytes. These do not change cycle scores or ranking.
After a successful certificate check, `verifier/MeasureRiscv.lean` re-exports and checks the
certificate with the pinned comparator, then counts the image lists by kernel reduction.
Its optional, separately bounded sandbox cannot change a proof verdict. Read measurements
only from the trusted driver's output file; candidate stdout is never a metadata channel.
New measurements travel in the bot's durable GitHub verdict and are restored by resync.
`riscv-program-sizes.json` preserves measurements of pre-feature submissions, pinned to
their original source SHA and contract. Missing or invalid measurements remain absent.

Show leanISA bytecode instruction counts on its record card, leaderboard and submission page.
Count the full fixed table (`2 ^ program.logSize`), including padding and the halt slot.
Do not invent a serialized byte size or a separate embedded-data section for this machine.
`verifier/MeasureLeanIsa.lean` replays the certificate through the same trusted export boundary
before reducing the log-size. Optional measurement failures never change the proof verdict.
Persist `leanisa_program_size` in GitHub verdicts, pinned to source and contract, and restore it
during resync. Missing measurements stay absent, never zero. Demo counts are preview data only.
`leanisa-program-sizes.json` preserves the six pre-feature counts from reviewed, retained source
definitions; `tools/check_historical_leanisa_sizes.py` checks their exact source hashes and literal
log-size bindings. This display-only catalog neither rechecks nor changes historical verdicts.

New RISC-V submissions export `image_size`, proving `submission.image.byteSize < 1048576`.
This is four bytes per instruction plus embedded-data bytes, with a strict upper bound.
The comparator checks this required theorem; optional display measurements never enforce admission.
The image-limit migration preserves only the audited historical images in the frozen size catalog,
bound to both source and contract. `tools/check_historical_riscv_sizes.py` rechecks their lengths
and strict bounds with Lean. Other tracks' statements are unchanged; preserve their compatible
results and prior proof ports. Do not rewrite receipts, source links, attribution or dates.

Ask the user before making substantial visible website changes. Permission to improve documentation
or agent discovery does not authorize changing navigation or the visible page layout. Explicitly
requested feature previews stay local and uncommitted until the user validates them.

Owner signature diagrams use `signature-diagrams.json` and static SVGs under `signature-diagrams/`
on submissions `main`. They may attach to either upper track, pinned to ID, checked source SHA
and contract. Fetch the registry and images at one immutable main revision in the background;
never insert owner SVG as page markup or fetch it while rendering a page. Serve images under
the sandbox CSP and preserve the approved drawing format. Metadata remains outside proof intake;
the record bot preserves owner files, including concurrent edits. Keep local diagram previews
gated to development with phony fixtures enabled. GitHub holds the durable drawings.

For the authorized live-maintenance workflow, commit, push and update `h2`; do not start or refresh
localhost. Other publication actions still require the user's authorization. Commits changing RISC-V formal verification credit
`Derek Sorensen <d@dhsorens.com>` as co-author.

Rule migrations must preserve original achievement credit and dates. An administrative proof port
never makes its maintainer the new record holder. Stage and verify replacement certificates before
switching public rules. Audited compatibility and individually checked proof ports belong in the
trusted contract/revalidation catalogs; never rewrite old receipts or claim a lower bound is valid
merely because an upper resource ceiling increased. Do not retire compatible budget-change results
to the Hall of Fame. Verify the complete board before ending temporary maintenance.
