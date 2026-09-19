# Website and hosted verifier

A FastAPI website that receives proof pull requests from
[ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions) and reports their
results, plus a separate worker that checks each proof against the trusted core checkout. The
competition rules are on [ots.golf/rules](https://ots.golf/rules) and, precisely, in
[AGENTS.md](../AGENTS.md); maintainer instructions for the site are in [AGENTS.md](AGENTS.md).

## Run locally

```sh
cd service
uv sync --frozen
./run-local.sh
```

Open `http://localhost:8000`. Startup refreshes the fictional [demo fixtures](demo/README.md),
preserving their IDs and dates; each row carries a demo label, and real submissions are left alone.
Set `OTS_PHONY=0` to show real submissions only: a track without a verified record shows
"No record yet".

**Refreshing.** This checkout's `post-commit` hook runs `refresh-local.sh`, which re-seeds the
demo rows and reloads the web process, including its cached commit. After every local commit,
check the rendered page. To install the hook in another checkout, from the repository root:

```sh
install -m 755 service/post-commit "$(git rev-parse --git-path hooks/post-commit)"
```

Refresh by hand with `bash service/refresh-local.sh`. The worker does not hot-reload: restart
`run-local.sh` after changing worker code. The startup script removes GitHub credentials from the
worker's environment.

**Demo rows.** `seed_demo.py --refresh` updates them, plain `seed_demo.py` replaces them and
`--remove` deletes them. The script refuses production mode and non-loopback site URLs, even with
`--force`, and normally accepts only the default local database. Never use fictional data in
production.

**Local proof jobs.** After `verifier/setup_tools.sh` and a warm `formal/` build, queue a commit of
a submissions checkout the way the webhook would:

```sh
.venv/bin/python -m app.queue lower-generality-2 --repo ../../ots.golf-submissions
```

Any track slug works. Local jobs never become records. Only one worker may use a data directory;
lock files enforce this across processes on the same host.

## How it works

- **Pages.** The homepage has an upper section (Upper bound; RISC-V upper bound, with its own
  cycle axis) and a lower section with one leaderboard per Generality framework.
  `/?framework=generality-1|generality-2|generality-3` filters the lower tables; `#lower` and
  `#upper` select the direction.
- **Admission.** A pull request must change exactly one submission root. The authenticated webhook
  checks the repository, files and head; the worker verifies that exact commit on the trusted tree.
- **Records.** A verified improvement becomes the record. When the worker stores a verified
  result it decides, under the results lock, whether the claim strictly improves the track's
  current record (or the track has none); records therefore follow the order verifications finish,
  and a later identical claim never takes one. Record decisions ignore demo rows. The bot never
  merges or closes pull requests: it writes only commit statuses and comments.
- **Reporting.** Commit statuses and result comments go through a durable outbox, so a reporting
  outage retries delivery without repeating the proof. Result reports keep their PR's repository.
- **Database.** A disposable cache: the website rebuilds it from GitHub at startup (`app.resync`),
  replaying verified verdicts in finish order to decide records;
  see [rebuilding the server](deploy/README.md#rebuilding-the-server-from-nothing).

Whenever the contract or an admission status changes, update the metadata, charts, leaderboards,
rules and documentation together, then refresh and inspect localhost.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OTS_ENV` | `development` | `development` or `production` |
| `OTS_ROLE` | `web` | `web` or `worker` |
| `OTS_REPO_ROOT` | checkout root | trusted contract checkout |
| `OTS_DATA_DIR` | `service/data` | SQLite database, logs and process locks |
| `OTS_WORK_DIR` | `<data>/work` | disposable verification jobs; dedicated bounded mount on Linux |
| `OTS_DATABASE_URL` | `sqlite:///<data>/ots.db` | database connection; deployment uses SQLite |
| `OTS_BASE_URL` | `http://localhost:8000` | site origin, without a path |
| `OTS_CONTRACT_REPO` | `leanEthereum/ots.golf-dev` | core repository; source and specification links |
| `OTS_SUBMISSIONS_REPO` | empty | proof PR repository; set to `leanEthereum/ots.golf-submissions` to configure intake |
| `GITHUB_WEBHOOK_SECRET` | empty | webhook authentication; web process only |
| `GITHUB_TOKEN` | empty | GitHub API access and reporting; web process only |
| `OTS_PHONY` | `1` | re-seed the invented demo rows at every start; `0` shows real submissions only |
| `OTS_RESYNC_ON_START` | `1` | rebuild missing submissions from GitHub when the website starts |
| `OTS_BOT_LOGIN` | token's login | account whose PR comments carry verdicts |
| `OTS_MAX_INFLIGHT_PER_USER` | `2` | pending and verifying jobs per user |
| `OTS_QUEUE_CAP` | `20` | pending jobs overall |

Production web startup requires HTTPS, two distinct repositories, a token and a webhook secret of
at least 32 characters. Production workers refuse GitHub credentials. Run the web process and the
worker under different Unix identities, sharing only the state group. See
[deployment](deploy/README.md) for storage, isolation, backups and launch checks, and
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
