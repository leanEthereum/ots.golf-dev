# Live maintenance and optional local development

The current maintainer workflow is commit, push, then update the live deployment on `h2`.
No localhost preview or post-commit refresh is required. Do not start local web or worker processes
unless the user requests local development. Run isolated tests before publishing changes, stop the
live worker before replacing its trusted checkout, and verify the deployed pages after an update.
The deployment guide owns host prerequisites, acceptance checks and recovery.

`OTS_PHONY=0` is the default for both web and worker: show real submissions only. Existing demo
rows keep their IDs and dates but remain hidden and cannot affect records. All five boards start
without records when there are no real verified submissions. Reference proofs reach the site as
ordinary pull requests; no baseline scores belong to the contract.

For explicitly requested local development, `./run-local.sh` starts the worker and web process.
Set `OTS_PHONY=1` to opt into the labeled demo fixtures. Preserve fixture IDs/dates when refreshing.
`seed_demo.py` refuses production mode and non-loopback site URLs, even with `--force`; never force
it against production. `demo/README.md` owns the fixture policy: each track's best demo claim equals
a claim proven in the reference proofs, and older rows may be worse. Keep fixtures, metadata,
admission status, charts, leaderboards and rules aligned.

GitHub holds durable source tags `refs/tags/ots-source/<submission-id>` and the bot's frozen
receipt/verdict comments. The server needs no backups: the database and exact source ZIPs are
rebuildable caches; original logs are disposable. Preserve the admission and verdict publication
gates, reporting retries, immutable source identity and digest checks. `python -m app.rebuild`
restores metadata; `--sources` also reconstructs ZIPs, without compiling historical submissions.
Never create replacement logs by rerunning an already published verdict. See `deploy/README.md`.

The three frameworks apply only to lower bounds. All three lower tracks are open, and the homepage
plots three certified lower series from their normal `challenges.json` metadata. Generic lower uses
`lower-generality-3`, with signing failure at most `2^-128` for every public-key-dependent
message selection, matching the upper track. Do not hardcode a separate generic
foundation certificate or show lower admission as pending. If a future framework has no checked
certificate, use a pending lane outside the numeric axis. Never substitute zero or a DAG theorem
for a missing generic certificate. Lower leaderboards have separate
rankings for generic algorithms, DAGs and whole words; `?framework=generality-1|generality-2|generality-3`
filters those lower tables only. Preserve `#lower` and `#upper` links.

Upper tracks are admitted through the top-level `upper_tracks` metadata, independently of the
three lower frameworks. `upper-compressions` is “Upper bound”, measured in compressions. `upper-riscv`
is “RISC-V upper bound”, measured in cycles on every execution, accepting or rejecting; every
execution must terminate and refine the Lean oracle specification. Render the second card, chart,
leaderboard and rules section only while the track is admitted in the metadata. Its chart
has an independent cycle axis: never combine cycles with compression bounds. The
compression upper line remains solid. Both upper leaderboards stay outside the lower-framework
filter. The lower-bound witnesses (`formal/Witnesses/`, checked with `lake build Witnesses`) are an
internal maintainer check, not tracks: they have no slug, submission root, demo rows or leaderboard.
The lower demo rows remain visible by default.
Preserve every fixture row with its ID and dates. A track's card, chart point, leaderboard,
submission page and solver profile refer to the same record row. Demo rows are clearly marked and
never receive verified badges or fabricated commit links.

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
demo rows like DAG lower. Do not leave the old 46-origin rule on the site.
`seed_demo.py --refresh` preserves existing rows. Run isolated checks with
`.venv/bin/python -m unittest discover -s tests -v` from `service/` after changing this behavior.

After deploying worker code, restart the live worker as well as the web service. Keep one worker
per data directory. Production web and worker run as different Unix users; only the web process
receives GitHub credentials. The bot creates retention tags and writes receipt/verdict comments and
commit statuses; it never merges or closes pull requests or changes an existing source tag.
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
the three lower cards and draw its chart line solid. Explain in the rules that any oracle algorithm
is allowed. Introduce the competition through fixed size, security and key-generation/signing
budgets, with worst-case verification cost as the quantity to minimize. Present the upper tracks and lower direction,
then the three lower classes; do not invent percentages for their degree of generality. Keep the
target-sum Winternitz illustration as a list of chains from secret to public endpoint: the message is encoded as
digits with a fixed sum, one per chain, the signature reveals the value each digit selects, and
the verifier hashes forward to the endpoint. Do not restore
the removed background-reading disclaimer or historical-certificate paragraph in the rules.
Keep the compression-cost rationale crediting Justin Drake: a per-key public parameter can be
absorbed once as a full prefix block and its hash state reused. This motivates no implicit
per-query surcharge; it does not exempt bits explicitly present in an oracle input from cost.

Name the lower frameworks “Generality 3/3” (any oracle algorithm), “Generality 2/3” (a DAG with
arbitrary deterministic functions), and “Generality 1/3” (a DAG built from whole words). Use these
names in cards, charts, filters, leaderboards, rules and submission/profile pages; explain the
restrictions in the descriptions. Keep the existing slugs and Lean names. Historical upper
references retain their historical names; the generality levels apply only to lower bounds.

Keep the homepage score cards compact, with the correct cost unit beside every score.
Oracle-algorithm signatures are plain bit strings; say so directly in public prose.
Name the bound direction explicitly in each score-card and framework rule heading. The algorithm
rule section covers upper constructions and Generality 3/3 lower bounds; the RISC-V section states
its machine, refinement, termination and cycle requirements, the cycle bound covering every
execution.

## Maintainer workflow

For the authorized live-maintenance workflow, commit, push and update `h2`; do not start or refresh
localhost. Other publication actions still require the user's authorization. Commits changing RISC-V formal verification credit
`Derek Sorensen <d@dhsorens.com>` as co-author.
