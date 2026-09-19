"""The production smoke probe reaches the user bus and cleans up failed/interrupted runs."""
import contextlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

VERIFIER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VERIFIER))
import check_linux_sandbox as probe


def process(pid, *, stdout=None, stderr=None):
    return SimpleNamespace(pid=pid, stdout=stdout, stderr=stderr, returncode=0,
                           wait=Mock(return_value=0), communicate=Mock(return_value=("passed", "")))


class LinuxProbeTests(unittest.TestCase):
    def test_bus_defaults_work_without_a_login_session(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True), patch.object(os, "getuid", return_value=123):
            env = probe.bus_environment()
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/123")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/123/bus")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_existing_bus_configuration_is_preserved(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/runtime", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/bus"}):
            env = probe.bus_environment()
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/runtime")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/bus")

    def test_success_stops_unit_and_client_group(self):
        client, kill, stop = process(101, stdout=io.StringIO(), stderr=io.StringIO()), process(102), process(103)
        env = {"XDG_RUNTIME_DIR": "/run/user/123", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/123/bus"}
        with patch.object(probe.subprocess, "Popen", side_effect=[client, kill, stop]) as popen, \
                patch.object(probe.os, "killpg") as killpg:
            result = probe.run_probe(["systemd-run"], env, "ots-smoke-fixture")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "passed", ""))
        self.assertEqual(popen.call_args_list[1].args[0],
                         ["systemctl", "--user", "kill", "--signal=KILL", "--kill-whom=all", "ots-smoke-fixture"])
        self.assertEqual(popen.call_args_list[2].args[0],
                         ["systemctl", "--user", "stop", "--no-block", "ots-smoke-fixture"])
        self.assertTrue(all(call.kwargs["env"] is env for call in popen.call_args_list))
        self.assertTrue(all(call.kwargs["start_new_session"] for call in popen.call_args_list))
        killpg.assert_any_call(client.pid, signal.SIGKILL)
        client.wait.assert_called_with(timeout=1)
        self.assertTrue(client.stdout.closed and client.stderr.closed)

    def test_timeout_survives_unavailable_or_hung_cleanup(self):
        client, control = process(201, stdout=io.StringIO(), stderr=io.StringIO()), process(202)
        original = subprocess.TimeoutExpired(["systemd-run"], 90)
        client.communicate.side_effect = original
        control.wait.side_effect = subprocess.TimeoutExpired(["systemctl"], 2)
        with patch.object(probe.subprocess, "Popen", side_effect=[client, control, OSError("bus unavailable")]), \
                patch.object(probe.os, "killpg") as killpg, \
                self.assertRaises(subprocess.TimeoutExpired) as caught:
            probe.run_probe(["systemd-run"], {}, "ots-smoke-fixture")
        self.assertIs(caught.exception, original)
        self.assertEqual([call.kwargs["timeout"] for call in control.wait.call_args_list], [2, 1])
        killpg.assert_any_call(client.pid, signal.SIGKILL)
        self.assertTrue(client.stdout.closed and client.stderr.closed)

    def test_interrupt_still_cleans_client_when_unit_cleanup_fails(self):
        client = process(301, stdout=io.StringIO(), stderr=io.StringIO())
        interruption = probe.ProbeInterrupted(signal.SIGTERM)
        client.communicate.side_effect = interruption
        with patch.object(probe.subprocess, "Popen",
                          side_effect=[client, OSError("bus unavailable"), OSError("bus unavailable")]), \
                patch.object(probe.os, "killpg") as killpg, self.assertRaises(probe.ProbeInterrupted) as caught:
            probe.run_probe(["systemd-run"], {}, "ots-smoke-fixture")
        self.assertIs(caught.exception, interruption)
        killpg.assert_called_once_with(client.pid, signal.SIGKILL)
        self.assertTrue(client.stdout.closed and client.stderr.closed)

    def test_canary_is_cleaned_after_interruption(self):
        holder = process(401)
        with patch.object(probe, "tools_env", return_value={"COMPARATOR_LANDRUN": "/bin/true"}), \
                patch.object(probe, "linux_preflight"), patch.object(probe, "linux_work_preflight"), \
                patch.object(probe, "linux_command", return_value=["fixture"]), \
                patch.object(probe.subprocess, "Popen", return_value=holder) as popen, \
                patch.object(probe, "run_probe", side_effect=probe.ProbeInterrupted(signal.SIGTERM)), \
                patch.object(probe, "kill_process_group") as cleanup, \
                self.assertRaises(probe.ProbeInterrupted):
            probe.check()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("DBUS_SESSION_BUS_ADDRESS", popen.call_args.kwargs["env"])
        cleanup.assert_called_once_with(holder)

    def test_signal_handlers_are_restored_after_termination(self):
        previous = {signal.SIGINT: object(), signal.SIGTERM: object()}
        handlers = {}
        def install(sig, handler):
            handlers[sig] = handler
        def interrupted_check():
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        with patch.object(probe.platform, "system", return_value="Linux"), \
                patch.object(probe.signal, "getsignal", side_effect=previous.__getitem__), \
                patch.object(probe.signal, "signal", side_effect=install), \
                patch.object(probe, "check", side_effect=interrupted_check), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(probe.main(), 128 + signal.SIGTERM)
        self.assertEqual(handlers, previous)

    def test_real_canary_group_terminates_without_waiting_for_natural_exit(self):
        canary = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                  start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:
            started = time.monotonic()
            probe.kill_process_group(canary)
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNotNone(canary.returncode)
            self.assertTrue(canary.stdout.closed and canary.stderr.closed)
        finally:
            # Independent fallback if a future regression stops cleaning up the fixture.
            try:
                os.killpg(canary.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            canary.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
