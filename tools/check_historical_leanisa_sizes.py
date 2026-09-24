#!/usr/bin/env python3
"""Reproduce the manually audited bytecode counts of six pre-feature leanISA submissions.

This checks frozen, reviewed source identities and literal log-size fields, not arbitrary Lean
programs. It does not rerun certificates or revise verdicts. Future measurements use the trusted
kernel-replay driver. Pass a submissions Git checkout containing the retained source commits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check(repo: Path):
    entries = json.loads((ROOT / "service/leanisa-program-sizes.json").read_text())["measurements"]
    for sid, entry in entries.items():
        sources = {}
        for name, digest in entry["source_audit"]["files_sha256"].items():
            raw = subprocess.check_output(["git", "-C", str(repo), "show",
                f'{entry["commit"]}:formal/Submissions/UpperLeanIsa/{name}'])
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError(f"{sid}: reviewed source identity changed: {name}")
            sources[name] = raw.decode()
        n = entry["source_audit"]["log_size"]
        assert 0 <= n <= 18 and entry["instructions"] == 2 ** n
        assert f"def program : Program where\n  logSize := {n}\n" in sources["MachineProgram.lean"]
        assert "  program := program\n" in sources["MachineFaithful.lean"]
        alias = "HLFlat" if "namespace OptimalOTS.HLFlat\n" in sources["MachineProgram.lean"] else "Honest"
        assert f"def submission : LeanIsa.Submission := {alias}.machineSubmission\n" in sources["Solution.lean"]
        print(f"{sid}: {2 ** n:,} slots; reviewed source bindings unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submissions", type=Path)
    check(parser.parse_args().submissions.resolve())
