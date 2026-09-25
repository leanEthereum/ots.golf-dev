#!/usr/bin/env python3
"""Verify one submission end to end, the way the hosted verifier does.

    verify.py TRACK --source PATH_OR_URL [--commit SHA] [--trusted DIR] [--lake DIR]
                    [--work DIR] [--keep] [--json]

Pipeline
  1. Take the submission root (and nothing else) from `--source` at `--commit`, or from the
     working tree of `--source` when no commit is given.
  2. Lay it over a copy of the TRUSTED tree (`--trusted`, default: this repo), so every protected
     file comes from the contract by construction.
  3. Policy checks: protected pin, flat root of regular files, imports, sizes, canonical claim.
  4. Attach a fresh clone of the warm `.lake` (`--lake`, default: <trusted>/formal/.lake) with any
     previous build products of this track removed. The submission is compiled for the first
     time inside comparator's sandbox, which is one of comparator's stated assumptions.
  5. Render the challenge stub with the claim and run comparator. On Linux it runs as a transient
     systemd user service: the contract's memory and wall-clock limits on the whole process tree,
     no AF_UNIX sockets (comparator's documented requirement, since Landlock cannot block them),
     no new privileges, and an environment holding nothing but PATH, HOME and the tool paths.
  6. Report: verified | rejected | policy_rejected | timeout | failed.

Tools come from verifier/setup_tools.sh (verifier/.tools/env.sh). On non-Linux hosts comparator
runs with its fake landrun shim: fine for development, NOT a sandbox.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from contract import LEAN_FILE_RE, ContractError, load_challenges, repo_root, track  # noqa: E402
from linux_storage import linux_work_preflight  # noqa: E402
from source_archive import ArchiveError, read_metadata, restore_source, save_source  # noqa: E402


LOG_CAP = 4 * 1024 * 1024        # bytes of comparator output kept; the rest is read and dropped
_BOUNDED_PROCESSES: set[subprocess.Popen] = set()


class PolicyReject(Exception):
    """The submission is refused before anything of it is copied or compiled."""


def run(cmd, timeout: int = 600):
    # Fetch progress and remote error messages are untrusted too. Bound their capture
    # and register the whole process group for cancellation, just like blob reads.
    output = bounded_output(cmd, LOG_CAP, timeout=timeout).decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")


def tools_env(root: Path) -> dict:
    env_file = root / "verifier" / ".tools" / "env.sh"
    if not env_file.is_file():
        raise ContractError("verification tools missing; run verifier/setup_tools.sh")
    env = {}
    for line in env_file.read_text().splitlines():
        if line.startswith("export ") and "=" in line:
            k, v = line[len("export "):].split("=", 1)
            env[k] = v.strip().strip('"')
    for key in ("COMPARATOR_BIN", "COMPARATOR_LEAN4EXPORT", "COMPARATOR_LANDRUN"):
        value = Path(env.get(key, ""))
        if not value.is_absolute() or not value.is_file() or not os.access(value, os.X_OK):
            raise ContractError(f"{key} must name an existing absolute executable; rerun verifier/setup_tools.sh")
    return env


def bounded_output(cmd: list[str], limit: int, timeout: float = 60, *, cwd=None, env=None) -> bytes:
    """Bound output bytes and the time until both the command and its output pipe finish."""
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, bufsize=0, cwd=cwd, env=env)
    _BOUNDED_PROCESSES.add(proc)
    chunks: list[bytes] = []
    size = 0

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return left

    try:
        # A descendant can retain stdout after the leader exits. Read without a buffered
        # reader thread, whose close() could otherwise wait forever on that thread's lock.
        os.set_blocking(proc.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                if not selector.select(remaining()):
                    continue
                try:
                    chunk = os.read(proc.stdout.fileno(), min(65536, limit - size + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise PolicyReject("submission metadata or file exceeds its size limit")
                chunks.append(chunk)
        # EOF alone is not completion either: the command may close stdout and keep running.
        proc.wait(timeout=remaining())
        data = b"".join(chunks)
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=data.decode(errors="replace"))
        return data
    finally:
        try:
            # The group may still exist after its leader exits, even after a successful command.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)  # bounded grace for reaping after SIGKILL
            except subprocess.TimeoutExpired:
                pass
        finally:
            proc.stdout.close()  # unbuffered and never shared with a reader thread
            _BOUNDED_PROCESSES.discard(proc)


def valid_name(name: str) -> bool:
    return bool(LEAN_FILE_RE.fullmatch(name)) or name in {"claim.txt", "NOTES.md", "README.md"}


NOTES_MAX_BYTES = 64 * 1024


def read_notes(root: Path) -> str | None:
    """The submitter's notes (`NOTES.md`), published with the result whatever the verdict."""
    path = root / "NOTES.md"
    if path.is_symlink() or not path.is_file():
        return None
    text = path.read_bytes()[:NOTES_MAX_BYTES].decode("utf-8", errors="replace").strip()
    return text or None


def export_submission(source: str, commit: str | None, rel_root: str, dest: Path,
                      max_files: int = 200, max_file_bytes: int = 8 * 1024 * 1024,
                      max_total_bytes: int = 16 * 1024 * 1024) -> str:
    """Copy only flat, bounded regular files; never apply archive attributes or follow links."""
    dest.mkdir(parents=True)
    out = dest / rel_root
    out.mkdir(parents=True)

    def check_sizes(entries):
        if len(entries) > max_files:
            raise PolicyReject(f"more than {max_files} files in {rel_root}")
        if any(size > max_file_bytes for _, size in entries):
            raise PolicyReject(f"a file in {rel_root} exceeds {max_file_bytes} bytes")
        if sum(size for _, size in entries) > max_total_bytes:
            raise PolicyReject(f"{rel_root} exceeds {max_total_bytes} bytes in total")
        for name, _ in entries:
            if not valid_name(name):
                raise PolicyReject(f"{name!r}: only flat .lean files, claim.txt, NOTES.md and README.md are allowed")

    if commit is None:
        src = Path(source) / rel_root
        if not src.is_dir():
            raise ContractError(f"{source} has no {rel_root}")
        if src.is_symlink():
            raise PolicyReject("submission root must not be a symlink")
        entries = []
        for path in src.iterdir():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise PolicyReject(f"{path.name!r}: only regular files are allowed")
            entries.append((path.name, info.st_size))
            if len(entries) > max_files:
                raise PolicyReject(f"more than {max_files} files in {rel_root}")
        check_sizes(entries)
        copied = 0
        for name, _ in entries:
            # O_NOFOLLOW + fstat closes the check/open race for final-component symlinks,
            # FIFOs and devices. Bound the read again in case a local file grew.
            fd = os.open(src / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise PolicyReject(f"{name!r}: only regular files are allowed")
                data = stream.read(max_file_bytes + 1)
            copied += len(data)
            if len(data) > max_file_bytes or copied > max_total_bytes:
                raise PolicyReject("submission grew beyond its size limit while being copied")
            (out / name).write_bytes(data)
        return "worktree"
    if not commit or commit.startswith("-") or "\x00" in commit:
        raise PolicyReject("invalid commit revision")
    with tempfile.TemporaryDirectory(prefix="ots-src-", dir=dest.parent) as tmp:
        repo = Path(tmp) / "repo"
        remote_source = not Path(source).is_dir()
        if not remote_source:
            repo = Path(source)
        else:
            run(["git", "init", "--quiet", str(repo)])
            run(["git", "-C", str(repo), "remote", "add", "origin", source])
            run(["git", "-C", str(repo), "fetch", "--filter=blob:none", "--depth=1", "--", "origin", commit])
        full = run(["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}"]).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", full):
            raise ContractError("git did not resolve a canonical commit hash")
        # Listing only this tree (not recursively) rejects a nested directory immediately.
        # Reading blobs directly ignores attacker-controlled export-ignore/export-subst.
        if remote_source:
            # ls-tree -l needs blob contents to determine their sizes. In a blobless fetch
            # that would lazily fetch one blob per network connection. Inspect names and
            # modes without sizes first, then fetch only the admitted root's blobs in one
            # request. Size checks still precede exporting any bytes to the proof tree.
            names = bounded_output(["git", "-C", str(repo), "ls-tree", "-z", f"{full}:{rel_root}"],
                                   max_files * 4096)
            selected = []
            for entry in filter(None, names.split(b"\0")):
                meta, raw_name = entry.split(b"\t", 1)
                mode, kind, oid = meta.split()
                name = raw_name.decode("utf-8", errors="replace")
                if kind != b"blob" or mode not in (b"100644", b"100755"):
                    raise PolicyReject(f"{name!r}: only regular files are allowed")
                selected.append((name, oid.decode("ascii")))
            if not selected:
                raise PolicyReject(f"the commit has no {rel_root}")
            check_sizes([(name, 0) for name, _ in selected])
            # Match Git's own promisor prefetch: no ref updates, tags, submodules or
            # negotiation over unrelated history. Explicitly wanted blobs survive the filter.
            oids = list(dict.fromkeys(oid for _, oid in selected))
            run(["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "fetch",
                 "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none",
                 "--", "origin", *oids])
        tree = bounded_output(["git", "-C", str(repo), "ls-tree", "-l", "-z", f"{full}:{rel_root}"],
                              max_files * 4096)
        blobs = []
        for entry in filter(None, tree.split(b"\0")):
            meta, raw_name = entry.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            name = raw_name.decode("utf-8", errors="replace")
            if kind != b"blob" or mode not in (b"100644", b"100755"):
                raise PolicyReject(f"{name!r}: only regular files are allowed")
            blobs.append((name, int(size), oid.decode("ascii")))
        if not blobs:
            raise PolicyReject(f"the commit has no {rel_root}")
        check_sizes([(name, size) for name, size, _ in blobs])
        for name, size, oid in blobs:
            data = bounded_output(["git", "-C", str(repo), "cat-file", "blob", oid], size)
            if len(data) != size:
                raise ContractError("git blob size changed unexpectedly")
            (out / name).write_bytes(data)
        return full


def linux_preflight(env: dict) -> None:
    """Production verification must never fall back to the development shim."""
    if os.geteuid() == 0:
        raise ContractError("refusing to compile submissions as root")
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        raise ContractError("Linux verification requires systemd-run and systemctl; refusing unsandboxed execution")
    lsm = Path("/sys/kernel/security/lsm")
    if not lsm.is_file() or "landlock" not in lsm.read_text().strip().split(","):
        raise ContractError("Landlock is not enabled on this kernel: refusing to build untrusted code")
    with Path(env["COMPARATOR_LANDRUN"]).open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ContractError("Linux verification requires the compiled landrun binary, not a development shim")
    if landlock_abi() < 3:
        raise ContractError("Landlock ABI 3 or newer is required to protect read-only files from truncate()")


def landlock_abi() -> int:
    # Linux assigns landlock_create_ruleset syscall 444 on these supported ABIs.
    # Querying VERSION with a null ruleset makes no changes to the calling process.
    if platform.machine() not in {"x86_64", "aarch64", "riscv64"}:
        raise ContractError("unsupported Linux architecture for the Landlock ABI preflight")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return int(libc.syscall(ctypes.c_long(444), ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1)))


def linux_command(cmd: list[str], cwd: Path, sandbox_env: dict, limits: dict, unit: str,
                  hidden: list[Path] = (), writable_files: tuple[Path, ...] = ()) -> list[str]:
    """Mandatory service isolation, shared with the on-host launch smoke test. `hidden` paths (the
    service's database, logs and configuration) become inaccessible, so a proof cannot print them
    into its public log."""
    props = [f"MemoryMax={limits['memory_bytes']}", "MemorySwapMax=0",
             f"RuntimeMaxSec={limits['wall_clock_seconds']}", "KillMode=control-group",
             # PID-namespace init or a candidate may ignore SIGTERM. Bound the shutdown
             # grace too, then force-kill the whole cgroup instead of waiting 90 seconds.
             "TimeoutStopSec=5", "SendSIGKILL=yes",
             "TasksMax=512", "RestrictAddressFamilies=~AF_UNIX", "NoNewPrivileges=yes",
             # Comparator builds only beneath .lake (nanoda is disabled in every pinned
             # config). A read-only mount also blocks chmod/xattr/utime metadata changes
             # that Landlock's file-content permissions do not comprehensively cover.
             "ProtectSystem=strict", f"ReadWritePaths={cwd / '.lake'}",
             # A private PID namespace: /proc shows only the job's own processes, never another
             # same-UID process's environment or descriptors. (Hiding /proc entirely breaks the
             # dynamic loader's $ORIGIN lookup, which Lean's binaries need.)
             "PrivatePIDs=yes", "ProcSubset=pid", "InaccessiblePaths=/sys",
             # Repeated assignments accumulate; "-" ignores paths that do not exist.
             "InaccessiblePaths=" + " ".join(f"-{p}" for p in ["/etc/ots", *hidden]),
             # PrivateDevices keeps the host's /dev/shm; give the job its own.
             "PrivateDevices=yes", "TemporaryFileSystem=/dev/shm", "PrivateIPC=yes", "SystemCallErrorNumber=EPERM",
             "SystemCallFilter=~@network-io @debug ptrace process_vm_readv process_vm_writev "
             "pidfd_getfd kill tkill tgkill pidfd_send_signal"]
    props.extend(f"ReadWritePaths={p}" for p in writable_files)
    launch = [sys.executable, str(HERE / "linux_exec.py")] + cmd
    launch_env = {"OTS_VERIFIER_HOST_DEV": str(Path("/dev").stat().st_dev),
                  "OTS_VERIFIER_HOST_PIDNS": (str(Path("/proc/self/ns/pid").stat().st_ino)
                                              if Path("/proc/self/ns/pid").exists() else ""),
                  "OTS_VERIFIER_HOST_SHM_DEV": (str(Path("/dev/shm").stat().st_dev)
                                                if Path("/dev/shm").exists() else ""), **sandbox_env}
    clean_cmd = ["/usr/bin/env", "-i"] + [f"{k}={v}" for k, v in launch_env.items()] + launch
    return (["systemd-run", "--user", "--wait", "--collect", "--pipe", "--quiet", f"--unit={unit}",
             f"--working-directory={cwd}"]
            + [x for p in props for x in ("-p", p)] + ["--"] + clean_cmd)


def measure_program(project: Path, lean_root: str, config: str, env: dict,
                  sandbox_env: dict, limits: dict, hidden=(), *, leanisa=False) -> dict | None:
    """Best-effort metadata from kernel-checked exports, under a separate bounded sandbox.

    The output file is writable only by the trusted driver. Comparator's Landlock
    export subprocesses have no writable paths. Never parse candidate stdout as metadata.
    A failure here leaves an already verified certificate and its score unchanged.
    """
    output = project / ("leanisa-size.json" if leanisa else "riscv-size.json")
    tool_paths = [Path(env[k]).parent.parent / "lib" / "lean"
                  for k in ("COMPARATOR_BIN", "COMPARATOR_LEAN4EXPORT")]
    size_env = {**sandbox_env, "LEAN_PATH": os.pathsep.join(map(str, tool_paths)),
                "OTS_SIZE_CONFIG": str(project / config), "OTS_SIZE_OUTPUT": str(output)}
    cmd = [shutil.which("lean", path=size_env["PATH"]) or "lean", str(HERE / ("MeasureLeanIsa.lean" if leanisa else "MeasureRiscv.lean"))]
    cenv, unit = size_env, None
    try:
        output.write_text("")
        if platform.system() == "Linux":
            unit = f"ots-size-{uuid.uuid4().hex[:12]}"
            cmd = linux_command(cmd, project / lean_root, size_env,
                                {**limits, "wall_clock_seconds": 300}, unit, hidden, (output,))
            runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            cenv = {"PATH": size_env["PATH"], "HOME": size_env["HOME"], "XDG_RUNTIME_DIR": runtime,
                    "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")}
        bounded_output(cmd, LOG_CAP, timeout=310, cwd=project / lean_root, env=cenv)
        with output.open("rb") as stream:
            raw = stream.read(1025)
        if len(raw) > 1024:
            return None
        value = json.loads(raw)
        if leanisa:
            if isinstance(value, dict) and set(value) == {"instructions"}:
                n = value["instructions"]
                if type(n) is int and 1 <= n <= 262144 and n & (n - 1) == 0:
                    return value
            return None
        if (isinstance(value, dict) and set(value) == {"instructions", "data_bytes"}
                and type(value["instructions"]) is int and 0 <= value["instructions"] <= 262144
                and type(value["data_bytes"]) is int and 0 <= value["data_bytes"] <= 1048576):
            return value
    except (OSError, ValueError, PolicyReject, subprocess.SubprocessError):
        pass
    finally:
        if unit:
            try:
                subprocess.run(["systemctl", "--user", "kill", "--signal=KILL", unit], env=cenv,
                               capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
    return None


def measure_riscv(project, lean_root, config, env, sandbox_env, limits, hidden=()):
    return measure_program(project, lean_root, config, env, sandbox_env, limits, hidden)


def measure_leanisa(project, lean_root, config, env, sandbox_env, limits, hidden=()):
    return measure_program(project, lean_root, config, env, sandbox_env, limits, hidden, leanisa=True)


def clone_tree(src: Path, dst: Path, ignore=None) -> None:
    """Copy a directory using filesystem clones where available (APFS, btrfs, xfs)."""
    if platform.system() == "Darwin":
        cmd = ["cp", "-c", "-R", str(src), str(dst)]
    else:
        cmd = ["cp", "-a", "--reflink=auto", str(src), str(dst)]
    if ignore is None:
        run(cmd)
    else:
        shutil.copytree(src, dst, ignore=ignore, symlinks=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--source", required=True, help="git URL, or a local directory (git repo or plain tree)")
    ap.add_argument("--commit", help="commit to verify; omit to take the working tree of a local --source")
    ap.add_argument("--trusted", type=Path, help="the contract checkout (default: this repo)")
    ap.add_argument("--lake", type=Path, help="warm .lake to clone (default: <trusted>/formal/.lake)")
    ap.add_argument("--work", type=Path, help="work directory (default: a temp dir)")
    ap.add_argument("--hide", type=Path, action="append", default=[],
                    help="Linux: make every entry of this directory inaccessible to the proof, "
                         "except the one containing the work directory")
    ap.add_argument("--archive-dir", type=Path, help="durable source store, outside disposable work")
    ap.add_argument("--archive-id", help="32-digit submission id; required with --archive-dir")
    ap.add_argument("--keep", action="store_true", help="keep the work directory")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if bool(a.archive_dir) != bool(a.archive_id) or (a.archive_dir and not a.commit):
        ap.error("--archive-dir and --archive-id require each other and an exact --commit")

    trusted = (a.trusted or repo_root()).resolve()
    cfg = load_challenges(trusted)
    t = track(cfg, a.track)
    lim = cfg["limits"]
    lean_root = cfg.get("lean_root", ".")
    warm_lake = (a.lake or trusted / lean_root / ".lake").resolve()
    work = (a.work or Path(tempfile.mkdtemp(prefix="ots-verify-"))).absolute()
    if a.archive_dir:
        a.archive_dir = a.archive_dir.resolve()
        if a.archive_dir.is_relative_to(work.resolve()) or work.resolve().is_relative_to(a.archive_dir):
            ap.error("source archive storage must be separate from disposable work")
    if a.work:
        # This directory is removed after successful runs; never adopt an existing path.
        try:
            work.mkdir(mode=0o700, parents=True, exist_ok=False)
        except OSError as exc:
            ap.error(f"--work must be a new directory: {exc}")
    project = work / "project"
    log_path = work / "verify.log"
    result = {"track": a.track, "source": a.source, "status": "failed", "work": str(work)}
    t0 = time.monotonic()
    proc, unit, cenv = None, None, None

    def stop_processes():
        if unit:
            try:
                subprocess.run(["systemctl", "--user", "kill", "--signal=KILL", unit], env=cenv,
                               capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for child in tuple(_BOUNDED_PROCESSES):
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def interrupted(signum, _frame):
        stop_processes()
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)

    def finish(status, **extra):
        result.update(status=status, duration_s=round(time.monotonic() - t0, 1), log=str(log_path), **extra)
        if a.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{status}: track={a.track} claim={result.get('claim')} commit={result.get('commit')} "
                  f"in {result['duration_s']}s (log: {log_path})")
        if not a.keep and status in {"verified", "rejected", "policy_rejected", "timeout"}:
            shutil.rmtree(work, ignore_errors=True)
        return 0 if status == "verified" else 1

    try:
        env = tools_env(trusted)
        if platform.system() == "Linux":
            linux_preflight(env)
            linux_work_preflight(work, trusted, warm_lake)
        # 1. submission root only
        staged = work / "staged"
        archive_contract = hashlib.sha256((trusted / cfg["contract"]["pin_file"]).read_bytes()).hexdigest() if a.archive_dir else None
        retained = read_metadata(a.archive_dir, a.archive_id) if a.archive_dir else None
        if retained is not None:
            result["commit"] = restore_source(a.archive_dir, retained, staged, commit=a.commit,
                                               track=a.track, contract=archive_contract,
                                               submission_root=t["submission_root"])
            result["source_archive"] = retained
        else:
            result["commit"] = export_submission(a.source, a.commit, t["submission_root"], staged,
                                                  max_files=lim["max_files"], max_file_bytes=lim["max_file_bytes"],
                                                  max_total_bytes=lim["max_total_bytes"])
            if a.archive_dir:
                if result["commit"] != a.commit:
                    raise ArchiveError("archive retention requires the exact resolved commit")
                # The trusted parent publishes durable bytes before any candidate code executes.
                result["source_archive"] = save_source(a.archive_dir, a.archive_id,
                    staged / t["submission_root"], source_repo=a.source, commit=result["commit"],
                    track=a.track, submission_root=t["submission_root"], contract=archive_contract)
        notes = read_notes(staged / t["submission_root"])
        if notes:
            result["notes"] = notes
        # 2. the trusted tree, allowlisted: only what a verification needs, so the copy can never
        #    recurse into work directories, tool checkouts or unrelated files
        def skip(names_to_skip):
            return lambda dirpath, names: {n for n in names if n in names_to_skip or n == "__pycache__"}
        project.mkdir(parents=True)
        shutil.copyfile(trusted / "challenges.json", project / "challenges.json")
        shutil.copytree(trusted / "verifier", project / "verifier", ignore=skip({".tools", ".work"}))
        root_rel = Path(t["submission_root"]).relative_to(lean_root)
        chal_rel = Path(t["challenge_file"]).relative_to(lean_root)
        def skip_lean(dirpath, names):
            rel = Path(dirpath).resolve().relative_to((trusted / lean_root).resolve())
            return {n for n in names if n == ".lake" or (rel / n) in {root_rel, chal_rel}}
        shutil.copytree(trusted / lean_root, project / lean_root, ignore=skip_lean, symlinks=True)
        shutil.copytree(staged / t["submission_root"], project / t["submission_root"], symlinks=True)
        # 3. policy (before the expensive clone)
        pin = subprocess.run([sys.executable, str(HERE / "pin_contract.py"), "check", "--root", str(project)],
                             text=True, capture_output=True)
        if pin.returncode != 0:
            log_path.write_text(pin.stdout + pin.stderr)
            return finish("failed", reason="protected files differ from the pin: " + pin.stderr.strip())
        chk = subprocess.run([sys.executable, str(HERE / "check_submission.py"), a.track, "--root", str(project), "--json"],
                             text=True, capture_output=True)
        try:
            policy = json.loads(chk.stdout)
        except ValueError:
            log_path.write_text(chk.stdout + chk.stderr)
            return finish("failed", reason="check_submission crashed: " + chk.stderr.strip())
        result["claim"] = policy.get("claim")
        if not policy["ok"]:
            log_path.write_text("\n".join(policy["errors"]) + "\n")
            return finish("policy_rejected", errors=policy["errors"])
        # 4b. warm .lake (after the cheap checks), minus this track's build products
        if not warm_lake.is_dir():
            raise ContractError(f"warm .lake missing: {warm_lake} (build the trusted tree first)")
        lake_dir = project / lean_root / ".lake"
        clone_tree(warm_lake, lake_dir)
        modpath = t["module_prefix"].replace(".", "/")
        for sub in ("build/lib/lean", "build/ir"):
            shutil.rmtree(lake_dir / sub / modpath, ignore_errors=True)
        shutil.rmtree(lake_dir / "build/lib/lean/OptimalOTS/Challenge", ignore_errors=True)
        # 5. render + comparator
        run([sys.executable, str(HERE / "render_challenge.py"), a.track, "--root", str(project)])
        home = str(Path.home())
        path = f"{home}/.elan/bin:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"
        # Nothing of the caller's environment reaches comparator or the code it builds: the worker's
        # carries the GitHub token and the webhook secret.
        sandbox_env = {"PATH": path, "HOME": home, "LANG": "C.UTF-8",
                       "COMPARATOR_LANDRUN": env["COMPARATOR_LANDRUN"],
                       "COMPARATOR_LEAN4EXPORT": env["COMPARATOR_LEAN4EXPORT"]}
        lake = shutil.which("lake", path=path) or "lake"
        cmd = [lake, "env", env["COMPARATOR_BIN"], str(project / t["comparator_config"])]
        cenv, unit = dict(sandbox_env), None
        hidden = []
        if platform.system() == "Linux":
            # A transient user SERVICE, not a scope: only a service can carry RestrictAddressFamilies,
            # which comparator requires because Landlock cannot block unix sockets, and only a service
            # is killed as a whole cgroup when the time is up. Under a system service there is no
            # session environment; the user's manager (kept alive by `loginctl enable-linger`)
            # listens under /run/user/<uid>.
            unit = f"ots-verify-{uuid.uuid4().hex[:12]}"
            hidden = [entry for d in a.hide if d.is_dir() for entry in sorted(d.resolve().iterdir())
                      if entry not in work.resolve().parents and entry != work.resolve()]
            if a.archive_dir:
                hidden.append(a.archive_dir)
            cmd = linux_command(cmd, project / lean_root, sandbox_env, lim, unit, hidden)
            runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            cenv = {"PATH": path, "HOME": home, "XDG_RUNTIME_DIR": runtime,
                    "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")}
        elif "TMPDIR" in os.environ:
            cenv["TMPDIR"] = os.environ["TMPDIR"]

        started = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=project / lean_root, env=cenv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)

        def pump():                                   # keep the head of the output, drain the rest
            kept = 0
            with log_path.open("wb") as log:
                for chunk in iter(lambda: proc.stdout.read(65536), b""):
                    if kept < LOG_CAP:
                        log.write(chunk[:LOG_CAP - kept])
                        kept += len(chunk)
                        if kept >= LOG_CAP:
                            log.write(b"\n[output truncated]\n")

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=lim["wall_clock_seconds"] + 60)
        except subprocess.TimeoutExpired:
            stop_processes()
            proc.wait()
            reader.join(10)
            return finish("timeout", limit_s=lim["wall_clock_seconds"])
        reader.join(30)
        if proc.returncode != 0 and time.monotonic() - started >= lim["wall_clock_seconds"] - 1:
            stop_processes()                           # RuntimeMaxSec already killed the tree
            return finish("timeout", limit_s=lim["wall_clock_seconds"])
        text = log_path.read_text(errors="replace")
        if proc.returncode == 0 and "Your solution is okay!" in text:
            if a.track in ("upper-riscv", "upper-riscv-hint"):
                size = measure_riscv(project, lean_root, t["comparator_config"], env,
                                     sandbox_env, lim, hidden)
                if size is not None:
                    result["riscv_program_size"] = size
            elif a.track == "upper-leanisa":
                size = measure_leanisa(project, lean_root, t["comparator_config"], env,
                                       sandbox_env, lim, hidden)
                if size is not None:
                    result["leanisa_program_size"] = size
            return finish("verified", comparator_exit=0)
        return finish("rejected", comparator_exit=proc.returncode, tail=text[-2000:])
    except PolicyReject as exc:
        log_path.write_text(str(exc) + "\n")
        return finish("policy_rejected", errors=[str(exc)])
    except (ArchiveError, ContractError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        log_path.write_text(str(detail))
        return finish("failed", reason=str(detail)[-2000:])
    finally:
        # Includes exceptions while reading logs and interruption by the worker's timeout.
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
