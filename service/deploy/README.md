# Deploying the verifier and website

The operational guide for a production host: installation, the Linux acceptance checks, the gates
before public launch, and day-to-day operations. For local development see the
[service README](../README.md).

## Requirements

- **Host.** One x86_64 Linux host running Ubuntu 26.04, with at least 8 cores and 32 GB RAM,
  space for the trusted warm Lean build, and **systemd 257 or newer**: the verifier requires
  [`PrivatePIDs=yes`](https://github.com/systemd/systemd/blob/v259/man/systemd.exec.xml). The production host `h2` runs Ubuntu 26.04 and systemd 259. Ubuntu 24.04's
  standard systemd 255 does not meet this requirement. The worker and all web processes share
  one data directory; workers on separate hosts are not supported. Use the locked Python dependencies.
- **GitHub.** The public submissions repository retains source commits and the bot's receipt and
  verdict comments. The server is disposable; database and source ZIPs are rebuildable caches,
  and original verification logs are disposable. Source fetching uses public HTTPS without a token.
- **Bounded job storage.** Untrusted work needs a **dedicated filesystem of at most 64 GiB**,
  separate from the operating system, trusted checkout, warm Lean cache, account homes and
  persistent website data. Memory and time limits do not prevent a submission from filling a disk;
  the verifier refuses unbounded or shared job storage.
- **Linux acceptance.** **A macOS proof check is not a production sandbox test.** Complete the
  [acceptance checks](#linux-acceptance-checks) on the actual host before connecting the public
  webhook. The installer deliberately leaves the services stopped.

## Install and configure

1. As root, run:

   ```sh
   OTS_REPO_URL=https://github.com/leanEthereum/ots.golf-dev \
     OTS_SUBMISSIONS_REPO=leanEthereum/ots.golf-submissions \
     OTS_DOMAIN=ots.golf bash service/deploy/setup-server.sh
   ```

   The script installs the tools, warms the trusted Lean project, and installs Caddy and the two
   systemd units. Review the downloaded elan, uv, Go and Caddy installers as part of host provisioning;
   this bootstrap is not a hermetic operating-system image. The repository pins the proof tool commits
   and the Python dependency lockfile.

2. Add a fine-grained token for a dedicated bot account to `/etc/ots/secrets.env`, scoped to
   `leanEthereum/ots.golf-submissions` only. Grant commit statuses read/write, pull requests
   read/write for the receipt/verdict comments, and **Contents read/write** to create source
   retention tags. Metadata read-only is implied. The bot never merges or closes PRs and never
   updates a source tag; it creates `refs/tags/ots-source/<submission-id>` pointing at the exact
   admitted commit before verification can start. No core-repository write access is needed.

   Configure repository rulesets for `ots-source/**`: allow tag creation by the bot, and prohibit
   tag updates and deletion. Use separate creation and update/deletion rules so the bot's creation
   bypass does not also permit mutation or deletion. A Contents-write token alone does not express
   this creation-only policy. Protect `main` from direct updates, force pushes and deletion; the
   bot should not bypass its rules. Retain the bot's PR comments as the durable result history.

   Keep `/etc/ots/secrets.env` `root:root 0600`; the installer generates its webhook secret.
   Do not put credentials in `/etc/ots/public.env`, the checkout, Git configuration, the `ots`
   account's home or the verifier environment. A replacement server gets a reissued token for
   the same bot account and a freshly configured webhook secret; no server backup is required.

   `ots-web` owns the website and GitHub reporting; only that service receives `secrets.env`.
   The verifier runs as the different Unix user `ots`, with public settings only. Both use the
   `ots-state` group for the SQLite database, logs and lock files. The data directory is setgid and
   the services use `UMask=0007`. This separates the web process's credentials from submission code,
   including reads of another process's environment. Production worker startup refuses GitHub
   credentials. Do not run both services as the same user.

   Ubuntu restricts unprivileged user namespaces, which the per-user systemd manager needs for
   each job's private namespaces. The installer loads `/etc/apparmor.d/ots-systemd-executor`, an
   **unconfined** profile granting `userns` to `systemd-executor` and inherited by its children.
   It is not an executor-only exception or the candidate sandbox. The actual boundary depends on
   Landlock and the verifier's checked systemd restrictions; run the probe on the deployed host.

3. Job storage at `/srv/ots-work`, at most 64 GiB. The installer creates it: a fully allocated
   48 GiB image, `/var/lib/ots-work.img` (root only, made with `fallocate`, formatted with
   `mkfs.ext4 -E nodiscard,lazy_itable_init=0,lazy_journal_init=0` so no hole is punched into it), mounted through `/etc/fstab` at every boot, root owned by `ots:ots-state` with mode
   `2770`. The verifier accepts a loop-backed volume only when its image is fully allocated, so the
   volume cannot outgrow the space reserved on the system disk. A dedicated block volume or a
   bounded tmpfs also works. Do not put the database, logs, trusted checkout or warm cache on it.

   `OTS_WORK_DIR=/srv/ots-work` and `TMPDIR=/srv/ots-work` in `public.env` put both job directories and
   temporary Git clones on the bounded volume. Each verification checks the mount, filesystem type,
   capacity and separation; nested mounts in a job are refused. Confirm that a full work volume
   fails a job while the website and database continue to work. Reflinks cannot cross filesystems,
   so the warm build is copied onto this separate volume; allow enough disk and startup time.

4. Inspect the installed units and validate Caddy:

   ```sh
   systemd-analyze verify /etc/systemd/system/ots-web.service /etc/systemd/system/ots-worker.service
   caddy validate --config /etc/caddy/Caddyfile
   ```

   The units set `OTS_ENV=production` and their respective `OTS_ROLE=web|worker`. Production web
   startup requires an HTTPS origin, two distinct repositories, token and webhook secret of at least 32 characters.
   The data/work paths, SQLite URL, domain, `OTS_CONTRACT_REPO=leanEthereum/ots.golf-dev` and
   `OTS_SUBMISSIONS_REPO=leanEthereum/ots.golf-submissions` are in `/etc/ots/public.env`.
   New installations set `OTS_PHONY=0` in the shared public environment for both services.
   Existing environment files are preserved: explicitly set `OTS_PHONY=0` and update both
   repository settings when migrating. This hides any retained demo rows without deleting their
   IDs or dates. The trusted checkout and its Git remote must refer to the core repository.

## Linux acceptance checks

Run these with the public webhook disconnected and the production configuration in place:

1. As the verifier user, run the isolation probe, build the internal lower-bound witnesses of the
   trusted core (`lake build Witnesses`, core code only), then verify every track's reference
   proof: `/srv/ots/submissions-check` is a separate checkout of a submissions repository holding
   each track's reference root (before launch, the maintainer's fork), never the trusted checkout.

   ```sh
   sudo -u ots -H bash -c 'set -a; . /etc/ots/public.env; set +a
     export PATH="$HOME/.elan/bin:/usr/local/bin:/usr/bin:/bin"
     cd /srv/ots/repo
     python3 verifier/check_linux_sandbox.py &&
     (cd formal && lake build Witnesses) &&
     for t in lower-generality-1 lower-generality-2 lower-generality-3 upper-compressions upper-riscv; do
       python3 verifier/verify.py "$t" --source /srv/ots/submissions-check || exit 1
     done'
   ```

   The probe must pass actual environment, `/proc`, filesystem, network, process-memory and signal
   denial checks, including a running canary process and forbidden truncation/permission changes. The verifier requires Landlock ABI 3 or newer and systemd, private devices and shared memory, a
   clean environment, masked `/proc`, `/sys`, `/etc/ots` and the service's data directory (database,
   logs and locks; only the job's own work directory stays visible), read-only system mounts with
   only the job’s `.lake` writable, and denied networking and cross-process control.
   An in-service launcher checks that the kernel actually enforces these restrictions before starting
   comparator. Unsupported isolation must reject the job; never remove
   the checks to make a host pass. Also exercise the contract's memory limit and a timed-out malicious
   test submission, and confirm the entire transient service and process group terminate.

2. Start the services, still without a public webhook:

   ```sh
   systemctl start ots-web ots-worker caddy
   curl --fail https://ots.golf/healthz
   ```

   Replace the example domain with yours. Check the journal and confirm different process owners.
   From `ots`, a read of `/proc/<ots-web-pid>/environ` must fail. Inspect the worker environment as
   root without printing secret values and confirm that neither GitHub credential variable is set.
   Test the site on narrow and desktop screens, keyboard navigation and both light/dark schemes.

3. Confirm `OTS_PHONY=0` for both services. Every board without a real verified record shows
   "No record yet"; there are no invented production records or reference baselines. Check all
   three lower boards, Upper bound and RISC-V upper bound. Existing demo rows remain stored but
   hidden and cannot participate in record decisions.

4. In a staging repository, exercise a signed PR webhook, duplicate delivery, a rejected proof,
   a verified improvement, a second PR with the same claim (verified, not a record), and a GitHub
   API outage followed by recovery. Confirm that the bot never merges or closes a PR. Stop and restart
   the worker during a job; it must retry the interrupted job once and refuse a concurrent worker.
   Confirm a retained source tag and frozen pending receipt exist before compilation, and that
   a result remains `publishing` until GitHub confirms its verdict comment. An outage must pause
   subsequent verification while that result awaits publication; delivery retries do not repeat
   a finished proof. Also force-push or close the staging PR, reconstruct its old pending receipt
   and exact source with `app.rebuild --sources`, and compare the recovered archive digest. These
   GitHub mutations are staging tests, never part of local repository tests.

5. On `leanEthereum/ots.golf-submissions`, connect GitHub's **Pull requests** webhook to
   `https://<domain>/webhooks/github`, with JSON content
   and the configured secret. Only `opened`, `synchronize` and `reopened` events are used; closing
   or merging a PR changes nothing. The service ignores other repositories and refuses
   admission when `OTS_SUBMISSIONS_REPO` is missing. Core-repository PRs are not proof submissions.

## Gates before public launch

A successful local proof check establishes none of the following; each must pass on the intended host:

1. The isolation probe and every reference proof from a submissions checkout, run under the deployed
   identities, including memory exhaustion, timeout and a full work volume, with complete process
   cleanup, the website and database still available, and refusal when isolation is unavailable.
2. Web credentials unreadable to the verifier identity, effective systemd restrictions,
   HTTPS/proxy configuration, protected source tags and a successful fresh-directory rebuild
   from GitHub receipts/verdicts and exact commits, with matching source ZIP digests.
3. The staging GitHub flow of acceptance check 4. The local tests mock GitHub and cannot replace it.
4. Before upgrading an existing deployment, check historical record replay and source availability
   as described below; older entries without retention tags have no new source-retention guarantee.

The host bootstrap downloads system tooling and is not a reproducible operating-system image.
This is a single-host deployment; the process locks are not a distributed queue protocol.

## Operations, upgrades and recovery

### Monitoring

`/healthz` checks the web process and database connection; it is not a certificate or worker-health
signal. Monitor `journalctl -u ots-web -u ots-worker`, queue age, free disk space, verification failures
and the `github_reports` outbox. Admission stays `admitting` until its pending receipt comment
is durable. A completed check stays `publishing`, outside public verified results and record
promotion, until its verdict comment is durable; later jobs wait behind that publication. Failed
reports retry with backoff up to an hour. A confirmed comment suffices even if its supplementary
commit-status update must retry. A crash after comment creation but before the local ID is saved
can produce a duplicate comment; rebuild merges the bot's history by receipt/finish time.
Proof verification is not repeated for an ordinary reporting outage.

### Worker

The worker holds a process lock for the shared data directory. At startup it requeues interrupted
`verifying` jobs, then processes one job at a time. Outer pipeline timeouts retain their logs and
terminate the verifier process group; the verifier also cleans up its comparator group and Linux
service. SIGTERM unwinds cleanup and exits 143, which the worker unit treats as a successful stop.
Keep one trusted checkout per worker and update it only while that worker is stopped.

### Rebuilding the server from nothing

GitHub is the durable competition store; no server backups are required. For each new hosted
submission, a creation-only `refs/tags/ots-source/<submission-id>` tag retains its exact commit in
the submissions repository. A bot comment freezes its author ID/login/avatar, admission time,
description, co-authors, assistance, submission root and trusted contract commit. The serialized
receipt is capped at 48 KiB; long prose belongs in the submitted `NOTES.md`. The terminal comment
adds the verdict, claim, finish time, record flag, archive descriptor and bounded failure summary.
Do not delete the retention tags or bot comments. Moving `refs/pull/<N>/head` is never used to
reconstruct an old revision.

The verifier retains a deterministic, uncompressed source ZIP under `OTS_DATA_DIR/sources/` before
running candidate code. ZIPs and their sidecars are local caches. Recovery fetches the full exact
commit from the base submissions repository with a credential-free bounded exporter, recreates the
historical manifest and requires the original digest when recorded. It never compiles a historical
proof to recover its source. A missing or mismatched source is reported unavailable without changing
the historical verdict. Legacy entries without a retention tag are recoverable only while GitHub
still has their exact commit. Missing original logs remain unavailable; they are not recreated by
rechecking a completed proof.

On a new host, install the trusted core and dependencies, recreate `/etc/ots/public.env`, provision
a token for the existing bot account and a new webhook secret, and repeat the Linux acceptance
checks. Keep web and worker stopped while rebuilding. Run this as root so systemd reads the protected
secret file and starts the command as `ots-web`; the verifier user never receives those credentials:

```sh
systemctl stop ots-web ots-worker
systemd-run --quiet --wait --pipe --collect --unit=ots-rebuild \
  --uid=ots-web --gid=ots-state \
  --property=WorkingDirectory=/srv/ots/repo/service --property=UMask=0007 \
  --property=EnvironmentFile=/etc/ots/public.env \
  --property=EnvironmentFile=/etc/ots/secrets.env \
  --setenv=OTS_ENV=production --setenv=OTS_ROLE=web --setenv=OTS_REPO_ROOT=/srv/ots/repo \
  /srv/ots/repo/service/.venv/bin/python -m app.rebuild --sources
```

Inspect the JSON counts and errors; a partial failure exits nonzero. Once metadata recovery and
host checks pass, run `systemctl start ots-web ots-worker`. Missing optional source caches stay
unavailable and can be retried separately.

A failed or interrupted metadata restore leaves `OTS_DATA_DIR/recovery.incomplete`. While it exists,
new verification and result publication remain paused, including after a restart. Resolve the API
or receipt error and rerun `app.rebuild` or `app.resync`; only successful metadata recovery clears
this marker. Never delete it to bypass incomplete record history. Optional notes/source-descriptor
warnings and missing source caches do not make otherwise complete metadata incomplete.

For metadata only, omit `--sources`. `--sources --limit N` bounds attempts to recover missing caches;
existing valid caches do not consume that limit. `--queue-open-heads` additionally admits current
open PR heads that have no durable receipt. Default rebuild already restores durable pending
receipts even if their PR was closed or force-pushed. It initializes a missing database and does
not wipe an existing one. Records are reconstructed in verification-finish order within the
current contract; frozen attribution takes precedence over subsequently edited PR text.

Ordinary startup runs metadata resync; `OTS_RESYNC_ON_START=0` disables it. Startup and page requests
do not fetch source ZIPs. Missing caches are fetched only by the explicit `--sources` command.
An interrupted check, or a result lost before its terminal comment became durable, can resume from
its pending receipt and require verification again. This is unfinished work, not reconstruction of
an old log. GitHub API pagination is bounded; a reported listing limit or API error must be resolved
before calling a rebuild complete.

Monitor local cache growth and free space. The archive writer reserves 64 MiB to leave room for
failure reporting. Cache or log loss does not require restoring a server image: reconstruct source
caches from GitHub and leave lost transcripts unavailable.

### Updating the live deployment

The maintainer workflow is **commit, push, then update `h2`**. No localhost preview or refresh is
required. Stop the worker before changing `/srv/ots/repo`, fetch the published core commit, check
out that exact commit, synchronize the locked dependencies, install changed units and run
`systemctl daemon-reload` when needed. Keep `/etc/ots/public.env` at `OTS_PHONY=0`; the installer
preserves existing environment files. Restart web and worker after the update, confirm `/healthz`
respond successfully, check `/rules` for the deployed commit, inspect all five boards and the service journal, and repeat
actual-host isolation/reference checks whenever the verifier or sandbox changes.

### Upgrading from the single-user setup

When upgrading from the earlier single-user setup, stop both services, create `ots-web` and
`ots-state`, update both units, and make existing database, WAL/SHM, log and lock files group-writable
by `ots-state`. Provision the bounded work mount and add `OTS_WORK_DIR`/`TMPDIR` to `public.env`;
existing environment files are not overwritten by the installer. Never grant the group access to
`secrets.env`. Set `OTS_PHONY=0` for both services. Run `app.rebuild --sources` to reconcile
historical records in verification-finish order and report which exact sources remain available;
it does not require moving or deleting the existing database. Legacy comments remain supported,
but unpinned historical commits may already be unavailable. Existing demo IDs and dates remain
stored and hidden.

### Webhook delivery

Webhook delivery is at least once, not guaranteed: use GitHub's delivery history to redeliver a lost
push event, or restart the website, whose resync queues open heads without a verdict. Records are
decided when verification finishes, never by webhook events, and the service never updates the
trusted checkout.
