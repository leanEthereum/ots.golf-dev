# Deploying the verifier and website

The operational guide for a production host: installation, the Linux acceptance checks, the gates
before public launch, and day-to-day operations. For local development see the
[service README](../README.md).

## Requirements

- **Host.** One x86_64 Linux host running Ubuntu 24.04, with at least 8 cores and 32 GB RAM, and
  space for the trusted warm Lean build. The worker and all web processes share one data
  directory; workers on separate hosts are not supported. Use the locked Python dependencies.
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

2. Add a token for a dedicated bot account (not a person) to `/etc/ots/secrets.env`. It is a
   fine-grained token for `leanEthereum/ots.golf-submissions` only, with commit statuses read/write,
   pull requests read/write (verdict comments on pull requests) and contents read-only (reading each
   head's `NOTES.md`); metadata read-only is implied. The bot writes nothing else: it never merges,
   closes or pushes, so it needs no contents write. A classic token would need the `public_repo`
   scope, which grants far more; prefer the fine-grained token. Protect `main`, which holds only the
   template, with a repository ruleset: no force pushes, no deletion. No core-repository access
   beyond reading is needed. The file already contains a generated webhook secret.
   Keep it `root:root 0600`. Do not put credentials in `/etc/ots/public.env`, the checkout, Git
   configuration, the `ots` account's home, or the verifier environment.

   `ots-web` owns the website and GitHub reporting; only that service receives `secrets.env`.
   The verifier runs as the different Unix user `ots`, with public settings only. Both use the
   `ots-state` group for the SQLite database, logs and lock files. The data directory is setgid and
   the services use `UMask=0007`. This separates the web process's credentials from submission code,
   including reads of another process's environment. Production worker startup refuses GitHub
   credentials. Do not run both services as the same user.

3. Provision a dedicated ext4 or xfs volume at `/srv/ots-work`, at most 64 GiB, and persist its mount
   through `/etc/fstab`. The installer creates only the mountpoint; it does not repartition or mount
   disks. After mounting, give its root to `ots:ots-state` with mode `2770`. Loop-backed filesystems
   are refused: checking their capacity does not establish reserved physical space on the host.
   A bounded tmpfs is also supported, but its pages consume RAM; size it within the host memory
   budget. Do not put the database, logs, trusted checkout or warm cache on this volume.

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
   Existing environment files are preserved: update both repository settings explicitly when migrating.
   The trusted checkout and its Git remote must refer to the core repository.

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

3. Nothing needs to be seeded by hand. At every start the website prepares the board: with
   `OTS_PHONY=1` (the current setting, chosen for the pre-launch site) it replaces the invented
   rows with those of `service/demo/submissions.json`; with `OTS_PHONY=0` it adds nothing, and every
   board starts empty until the first verified submission of its track becomes the record.

4. In a staging repository, exercise a signed PR webhook, duplicate delivery, a rejected proof,
   a verified improvement, a second PR with the same claim (verified, not a record), and a GitHub
   API outage followed by recovery. Confirm that the bot never merges or closes a PR. Stop and restart
   the worker during a job; it must retry the interrupted job once and refuse a concurrent worker.
   Verify that result statuses/comments eventually arrive without rerunning the proof after a
   reporting outage. These GitHub mutations are staging tests, never part of local repository tests.

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
2. Web credentials unreadable to the verifier identity, the effective systemd restrictions,
   HTTPS/proxy configuration, private backups and a successful database restore.
3. The staging GitHub flow of acceptance check 4. The local tests mock GitHub and cannot replace it.
4. Before upgrading an existing deployment, the audit of historical `is_record` rows described
   under upgrades below.

The host bootstrap downloads system tooling and is not a reproducible operating-system image.
This is a single-host deployment; the process locks are not a distributed queue protocol.

## Operations, upgrades and recovery

### Monitoring

`/healthz` checks the web process and database connection; it is not a certificate or worker-health
signal. Monitor `journalctl -u ots-web -u ots-worker`, queue age, free disk space, verification failures
and the `github_reports` outbox. Failed reports remain in that table and retry with backoff, up to an
hour; subsequent updates edit the stored result comment. A crash after GitHub accepts a new comment
but before its ID is committed can produce one duplicate comment on retry. Proof verification is not
repeated for a reporting failure.

### Worker

The worker holds a process lock for the shared data directory. At startup it requeues interrupted
`verifying` jobs, then processes one job at a time. Outer pipeline timeouts retain their logs and
terminate the verifier process group; the verifier also cleans up its comparator group and Linux
service. Keep one trusted checkout per worker and update it only while that worker is stopped.

### Rebuilding the server from nothing

The database is a cache. Everything durable lives on GitHub: pull requests (author, description,
attribution, head commits), each checked head's code and `NOTES.md` under
`refs/pull/<N>/head` of the submissions repository, and every verdict in a hidden
`<!-- ots-result ... -->` block of the verifier's own comment on the pull request. Keep only
`/etc/ots/secrets.env` (token and webhook secret) outside the server; `public.env` is regenerated
by the installer, and the webhook needs its secret to stay the same.

To rebuild: run `setup-server.sh` on a fresh host, restore `secrets.env`, repeat the acceptance
checks, and start both services. At startup the website prepares the board (phony rows or nothing, see
step 3 above) and runs `app.resync`, which restores every checked head from GitHub,
replays the verified verdicts in the order their verifications finished (ties by PR number, then
commit) to decide records, which keep their original dates, and queues any open head without a
verdict. Submission IDs are derived from the pull request and commit, so every page link survives.
Only old verifier transcripts are lost; rerun the verifier on the checked head to regenerate one.
`OTS_RESYNC_ON_START=0` skips the startup resync, and `.venv/bin/python -m app.resync` runs it by
hand as the web user.

### Backups

A backup remains useful for a quick restore. Before an upgrade, stop both services and back up the database with SQLite's backup API and the logs:
copying `ots.db` alone while WAL writes are active is not a consistent backup. For example, after
creating a protected backup directory, run `sqlite3 /srv/ots/data/ots.db '.backup /backup/ots.db'` as
root and copy `data/logs/`. Keep the backup private. Restore into a staging data directory and run
`PRAGMA integrity_check` before relying on it. The additive `github_reports` table is created at
startup; existing submission IDs, dates and results are preserved.

### Upgrading from the single-user setup

When upgrading from the earlier single-user setup, stop both services, create `ots-web` and
`ots-state`, update both units, and make existing database, WAL/SHM, log and lock files group-writable
by `ots-state`. Provision the bounded work mount and add `OTS_WORK_DIR`/`TMPDIR` to `public.env`;
existing environment files are not overwritten by the installer. Never grant the group access to
`secrets.env`. Records are no longer tied to merges: to recompute historical real records in
verification-finish order, move the old database aside and let the website rebuild it from GitHub.
Demo rows retain their intentional status.

### Webhook delivery

Webhook delivery is at least once, not guaranteed: use GitHub's delivery history to redeliver a lost
push event, or restart the website, whose resync queues open heads without a verdict. Records are
decided when verification finishes, never by webhook events, and the service never updates the
trusted checkout.
