#!/usr/bin/env python3
"""Run on the production Linux verifier account before admitting untrusted submissions.

This exercises the same mandatory systemd properties and Landrun restrictions as the
verifier. It is deliberately unavailable on macOS: local certificate checks do not test
Linux process, filesystem or network isolation. Run all configured certificate checks afterward.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import uuid

from contract import ContractError, repo_root
from verify import linux_command, linux_preflight, tools_env
from linux_storage import linux_work_preflight


PROBE = r'''
import ctypes, errno, json, os, pathlib, socket, sys
work, parent_pid = pathlib.Path(sys.argv[1]), sys.argv[2]
assert "OTS_SANDBOX_CANARY" not in os.environ, "inherited environment leaked"
for name in (f"/proc/{parent_pid}/environ", str(work / "readonly")):
    try:
        if name.startswith("/proc/"):
            pathlib.Path(name).read_bytes()
        else:
            pathlib.Path(name).write_text("unauthorized write")
    except OSError:
        pass
    else:
        raise AssertionError("sandbox unexpectedly allowed access: " + name)
try:
    os.truncate(work / "readonly", 0)
except OSError:
    pass
else:
    raise AssertionError("sandbox unexpectedly allowed truncating a read-only file")
try:
    os.chmod(work / "readonly", 0o777)
except OSError:
    pass
else:
    raise AssertionError("sandbox unexpectedly allowed changing read-only file permissions")
for family, kind in ((socket.AF_UNIX, socket.SOCK_STREAM),
                     (socket.AF_INET, socket.SOCK_STREAM),
                     (socket.AF_INET, socket.SOCK_DGRAM),
                     (socket.AF_INET6, socket.SOCK_STREAM)):
    try:
        sock = socket.socket(family, kind)
    except OSError:
        pass
    else:
        sock.close()
        raise AssertionError("sandbox unexpectedly allowed a network socket")
try:
    os.kill(int(parent_pid), 0)  # harmless probe of a same-UID process outside this job
except PermissionError:
    pass
else:
    raise AssertionError("sandbox unexpectedly allowed signalling the external canary")
libc = ctypes.CDLL(None, use_errno=True)
for name in ("process_vm_readv", "process_vm_writev"):
    probe = getattr(libc, name)
    probe.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                      ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    probe.restype = ctypes.c_ssize_t
    ctypes.set_errno(0)
    # Zero buffers and lengths: this never reads or changes the canary's memory,
    # even if isolation is broken. The seccomp rule must reject the syscall itself.
    result = probe(int(parent_pid), None, 0, None, 0, 0)
    if result != -1 or ctypes.get_errno() != errno.EPERM:
        raise AssertionError("sandbox unexpectedly allowed " + name)
shm = pathlib.Path("/dev/shm")
if shm.exists():
    # The mandatory launcher has already proved this is a different device from host shm.
    marker = shm / ("ots-smoke-" + str(os.getpid()))
    marker.write_text("private to this job")
    marker.unlink()
(work / ".lake" / "writable").write_text("allowed")
print(json.dumps({"sandbox": "passed", "checks": ["environment", "proc", "readonly files", "truncate", "chmod", "writable build", "unix sockets", "TCP", "UDP", "IPv6", "external process signals", "process memory syscalls"]}))
'''



class ProbeInterrupted(Exception):
    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(f"interrupted by signal {signum}")


def bus_environment() -> dict[str, str]:
    """Reach the verifier user's lingering manager even from sudo without a login session."""
    env = dict(os.environ)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = runtime
    env["DBUS_SESSION_BUS_ADDRESS"] = env.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime}/bus"
    return env


def kill_process_group(proc: subprocess.Popen) -> None:
    """Bound cleanup even when a process already exited or cannot immediately be reaped."""
    try:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    finally:
        # These are unbuffered pipes with no competing reader thread.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def stop_unit(unit: str, env: dict[str, str]) -> None:
    """The transient unit is independent of systemd-run's process group; stop both."""
    for action in (["kill", "--signal=KILL", "--kill-whom=all"], ["stop", "--no-block"]):
        control = None
        try:
            control = subprocess.Popen(["systemctl", "--user", *action, unit], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            control.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            # An already collected unit is normal; unavailable/hung managers must not hang cleanup.
            pass
        finally:
            if control is not None:
                kill_process_group(control)


def run_probe(cmd: list[str], env: dict[str, str], unit: str) -> subprocess.CompletedProcess:
    client = None
    try:
        client = subprocess.Popen(cmd, env=env, text=True, bufsize=0, start_new_session=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = client.communicate(timeout=90)
        return subprocess.CompletedProcess(cmd, client.returncode, stdout, stderr)
    finally:
        try:
            stop_unit(unit, env)
        finally:
            if client is not None:
                kill_process_group(client)

def check() -> int:
    holder = None
    try:
        env = tools_env(repo_root())
        linux_preflight(env)
        python = str(Path(sys.executable).resolve())
        with tempfile.TemporaryDirectory(prefix="ots-sandbox-smoke-") as tmp:
            work = Path(tmp)
            linux_work_preflight(work, repo_root(), repo_root() / "formal" / ".lake")
            (work / ".lake").mkdir()
            (work / "readonly").write_text("must stay unchanged")
            probe = work / "probe.py"
            probe.write_text(PROBE)
            parent_env = dict(bus_environment(), OTS_SANDBOX_CANARY="public-smoke-test-canary")
            holder = subprocess.Popen([python, "-c", "import time; time.sleep(180)"],
                                      env=parent_env, start_new_session=True)
            clean = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home())}
            landrun = [env["COMPARATOR_LANDRUN"], "--best-effort", "--ro", "/", "--rw", "/dev",
                       "-ldd", "-add-exec", "--env", "PATH", "--env", "HOME", "--rwx", str(work / ".lake"),
                       "--rox", str(Path(python).parent), "--", python, str(probe), str(work), str(holder.pid)]
            unit = f"ots-smoke-{uuid.uuid4().hex[:12]}"
            cmd = linux_command(landrun, work, clean, {"memory_bytes": 512 * 1024 * 1024,
                                                      "wall_clock_seconds": 60},
                                unit)
            result = run_probe(cmd, parent_env, unit)
            if result.returncode or '"sandbox": "passed"' not in result.stdout:
                print(result.stdout + result.stderr, file=sys.stderr)
                raise ContractError("Linux sandbox smoke test failed; do not admit untrusted submissions")
            if (work / "readonly").read_text() != "must stay unchanged":
                raise ContractError("Landrun allowed a write outside the build directory")
            print(result.stdout.strip())
        return 0
    except (ContractError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"sandbox check: {exc}", file=sys.stderr)
        return 1
    finally:
        if holder is not None:
            kill_process_group(holder)


def main() -> int:
    if platform.system() != "Linux":
        print("Linux sandbox smoke test requires Linux; no isolation claim is made on this host", file=sys.stderr)
        return 2
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def interrupted(signum, _frame):
        # A second signal must not interrupt the bounded cleanup triggered by the first.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        raise ProbeInterrupted(signum)

    try:
        for sig in previous:
            signal.signal(sig, interrupted)
        try:
            return check()
        except ProbeInterrupted as exc:
            print(f"sandbox check: {exc}", file=sys.stderr)
            return 128 + exc.signum
        except KeyboardInterrupt:
            return 130
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
