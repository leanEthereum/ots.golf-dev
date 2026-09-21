# Website and hosted verifier

A FastAPI website that receives proof pull requests from
[ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions) and reports their
results, plus a separate worker that checks each proof against the trusted core checkout. The
competition rules are on [ots.golf/rules](https://ots.golf/rules) and, precisely, in
[AGENTS.md](../AGENTS.md); maintainer instructions for the site are in [AGENTS.md](AGENTS.md).

## Live maintenance

The active workflow is commit, push, then update `h2`; no localhost preview or refresh is required.
Follow [deployment and recovery](deploy/README.md) for host checks, exact-commit updates and rebuilding
a disposable server from GitHub. Production web and worker use `OTS_PHONY=0`.

## Optional local development

```sh
cd service
uv sync --frozen
./run-local.sh
```

Open `http://localhost:8000`. The default `OTS_PHONY=0` shows only real submissions; a track
without a verified record shows "No record yet". For a requested demo preview, run
`OTS_PHONY=1 ./run-local.sh`. Startup then refreshes the fictional [demo fixtures](demo/README.md),
preserving their IDs and dates; each row carries a demo label, and real submissions are left alone.

For a deliberately running demo preview, `OTS_PHONY=1 bash refresh-local.sh` updates the
fixtures. The worker does not hot-reload: restart `run-local.sh` after changing worker code.
The startup script removes GitHub credentials from the worker's environment. A post-commit
refresh hook is optional and is not part of the live-deployment workflow.

**Demo rows.** `seed_demo.py --refresh` updates them, plain `seed_demo.py` replaces them and
`--remove` deletes them. The script refuses production mode and non-loopback site URLs, even with
`--force`, and normally accepts only the default local database. Never use fictional data in
production.

**Local proof jobs.** After `verifier/setup_tools.sh` and a warm `formal/` build, queue a commit of
a submissions checkout the way the webhook would:

```sh
.venv/bin/python -m app.queue lower-generality-1 --repo ../../ots.golf-submissions
```

Any track slug works. Local jobs never become records. Only one worker may use a data directory;
lock files enforce this across processes on the same host.

## How it works

RISC-V record cards, leaderboard rows and submission pages show the number of instructions in
the fixed program and the byte length of its embedded data, separately from execution cycles.
The worker automatically collects these after verification. The optional collector reuses the
pinned comparator's export, comparison and kernel checks, then reduces the image's lists in the
kernel; it never imports candidate modules into the trusted process. A separate Linux job limits
collection to 120 seconds, with the verifier's memory and isolation limits. Failure to measure
leaves the proof verdict unchanged and the metrics unavailable. The bot stores successful
measurements in its GitHub verdict so recovery needs no server-only data. The Git-tracked
[`riscv-program-sizes.json`](riscv-program-sizes.json) catalog supplies measurements for older
submissions, matched to their exact checked source SHA and contract.

Owners may add the approved per-instruction table to selected verified RISC-V submission pages
by committing `riscv-profiles.json` to submissions `main`. The web process refreshes its in-memory
copy every 60 seconds; page requests never wait on GitHub. Entries match the exact submission ID,
checked source SHA and contract, and never change proof results or scores. A fresh server fetches
them again. See the [owner guide](../tools/submissions_template/RISCV_PROFILES.md) and validate with
`python3 service/check_riscv_profiles.py ../ots.golf-submissions/riscv-profiles.json` from the core root.

- **Pages.** The homepage has an upper section (Upper bound; RISC-V upper bound, with its own
  cycle axis) and a lower section with one leaderboard per Generality framework.
  `/?framework=generality-1` links to the whole-word lower table; `#lower` and
  `#upper` select the direction.
- **Admission.** A pull request must change exactly one submission root. The service checks the
  repository, files and full head SHA, creates `refs/tags/ots-source/<submission-id>` in the base
  submissions repository, and publishes a pending receipt with frozen attribution and contract
  identity. The worker cannot start until GitHub confirms that receipt. Its serialized metadata
  is capped at 48 KiB; longer prose belongs in `NOTES.md`.
- **Records.** A verified improvement becomes the record only after its verdict comment is durable.
  Decisions follow verification-finish order under the results lock, so a later identical claim
  never takes a record. Demo rows cannot affect records. After the verdict is durable, the bot
  commits only the checked root and its `records.json` entry to submissions `main`, preserving
  other tracks and repository files. Its commit credits all Git authors and co-author trailers
  from the admitted PR revision, with identities frozen in the GitHub receipt. The bot never
  merges or closes PRs. PRs opened from an older
  base remain eligible when their own changes stay inside one admitted root.
- **Reporting.** The local outbox retries GitHub delivery without repeating a finished proof. A
  result awaiting its comment stays `publishing`; later jobs wait. Commit-status updates may retry
  after the durable comment succeeds. Record-snapshot commits also retry through the outbox
  without rerunning a finished proof. Reports retain the submission's original PR repository.
- **Code.** Submission pages link directly to the submitted GitHub folder at the original checked
  SHA. Later record commits on `main` do not move that link. Exact source ZIPs remain optional
  compatibility artifacts, independently reconstructible from the retained commit.
- **Recovery.** GitHub source tags and bot comments are durable state; submissions `main` and
  `records.json` provide the current-record snapshot. SQLite and deterministic
  source ZIPs are rebuildable caches; original logs are disposable. `python -m app.rebuild`
  restores metadata and queued receipts; `--sources` also fetches exact commits and requires any
  recorded archive digest. `--queue-open-heads` additionally admits unseen open heads. Rebuild
  never rechecks historical proofs or manufactures missing logs. See
  [rebuilding the server](deploy/README.md#rebuilding-the-server-from-nothing).

Whenever the contract or an admission status changes, update the metadata, charts, leaderboards,
rules and documentation together, then check the rendered live pages after deployment.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OTS_ENV` | `development` | `development` or `production` |
| `OTS_ROLE` | `web` | `web` or `worker` |
| `OTS_REPO_ROOT` | checkout root | trusted contract checkout |
| `OTS_DATA_DIR` | `service/data` | SQLite and source ZIP caches, disposable logs and process locks |
| `OTS_WORK_DIR` | `<data>/work` | disposable verification jobs; dedicated bounded mount on Linux |
| `OTS_DATABASE_URL` | `sqlite:///<data>/ots.db` | database connection; deployment uses SQLite |
| `OTS_BASE_URL` | `http://localhost:8000` | site origin, without a path |
| `OTS_CONTRACT_REPO` | `leanEthereum/ots.golf-dev` | core repository; source and specification links |
| `OTS_SUBMISSIONS_REPO` | empty | proof PR repository; set to `leanEthereum/ots.golf-submissions` to configure intake |
| `GITHUB_WEBHOOK_SECRET` | empty | webhook authentication; web process only |
| `GITHUB_TOKEN` | empty | GitHub API access and reporting; web process only |
| `OTS_PHONY` | `0` | show real submissions only; `1` opts into labeled demo rows for local development |
| `OTS_RESYNC_ON_START` | `1` | rebuild missing submissions from GitHub when the website starts |
| `OTS_BOT_LOGIN` | token's login | account whose PR comments carry verdicts |
| `OTS_MAX_INFLIGHT_PER_USER` | `2` | admitting, pending, verifying and publishing jobs per user |
| `OTS_QUEUE_CAP` | `20` | in-flight jobs overall |

Production web startup requires HTTPS, two distinct repositories, a token and a webhook secret of
at least 32 characters. Production workers refuse GitHub credentials. Run the web process and the
worker under different Unix identities, sharing only the state group. See
[deployment](deploy/README.md) for storage, isolation, GitHub recovery and launch checks, and
[repository setup](../docs/repositories.md) for the submissions workspace.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
cd ..
python3 service/browser_check.py --output-dir /tmp/ots-ui
python3 tools/check_repo.py --numerics-python .venv-tools/bin/python --formal --paper
```

Service tests use isolated databases. The optional browser check drives Firefox against the seeded
local preview: desktop and mobile layouts, both color schemes, keyboard controls, filters,
tooltips, reduced motion and error pages. See [tools](../tools/README.md) for the NumPy setup and
the repository runner; `--official --submissions PATH` verifies every submission root in a
submissions checkout. Local macOS verification is unsandboxed; the remaining launch gates are in
[deployment](deploy/README.md).
