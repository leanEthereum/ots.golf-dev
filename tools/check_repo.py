#!/usr/bin/env python3
"""Run local regression checks without network access or changing the running site.

    python3 tools/check_repo.py --numerics-python .venv-tools/bin/python --formal
    python3 tools/check_repo.py --official --submissions ../ots.golf-submissions

Requires the service environment and NumPy for the research-tool tests. --official builds Lean and
runs the official pipeline for every track whose root exists in the --submissions checkout; --formal
also builds the internal lower-bound witnesses (formal/Witnesses). Linux sandbox acceptance and the browser check are separate
commands: verifier/check_linux_sandbox.py and service/browser_check.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--service-python', default=str(ROOT / 'service/.venv/bin/python'))
    parser.add_argument('--numerics-python', default=sys.executable)
    parser.add_argument('--node', help='Node.js executable for JavaScript syntax checks (otherwise found on PATH)')
    parser.add_argument('--formal', action='store_true', help='build Lean and audit all protected model declarations')
    parser.add_argument('--official', action='store_true',
                        help='also verify every submission root present in the --submissions checkout')
    parser.add_argument('--submissions', type=Path, help='submissions checkout verified by --official')
    args = parser.parse_args()
    if args.official and not args.submissions:
        parser.error('--official needs --submissions PATH, a checkout of the submissions repository')
    service_python = shutil.which(args.service_python)
    numerics_python = shutil.which(args.numerics_python)
    node = shutil.which(args.node or 'node')
    if not service_python or not numerics_python:
        parser.error('Python environment missing; see service/README.md and tools/README.md')
    if subprocess.run([numerics_python, '-c', 'import numpy'], capture_output=True).returncode:
        parser.error('NumPy is missing from --numerics-python; see tools/README.md')
    if not node:
        parser.error('Node.js is required for syntax checks; install it or pass --node /path/to/node')

    def check(label: str, command: list[str], cwd: Path = ROOT) -> None:
        print(f'\nChecking {label}', flush=True)
        subprocess.run(command, cwd=cwd, check=True)

    try:
        check('contract pin', [sys.executable, 'verifier/pin_contract.py', 'check'])
        check('verifier regression tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'verifier/tests', '-v'])
        check('service regression tests', [service_python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], ROOT / 'service')
        check('numerical regressions', [numerics_python, '-m', 'unittest', 'discover', '-s', 'tools/tests', '-v'])
        for script in sorted((ROOT / 'service/app/static').glob('*.js')):
            check(script.name, [node, '--check', str(script)])
        for parent in ('service', 'service/deploy', 'verifier'):
            for script in sorted((ROOT / parent).glob('*.sh')):
                check(str(script.relative_to(ROOT)), ['bash', '-n', str(script)])
        if args.formal or args.official:
            check('Lean library', ['lake', 'build', 'OptimalOTS'], ROOT / 'formal')
            check('protected model axioms', ['lake', 'env', 'lean', 'scripts/check-axioms.lean'], ROOT / 'formal')
            check('RISC-V machine boundaries', ['lake', 'env', 'lean', 'scripts/check-riscv.lean'], ROOT / 'formal')
            check('lower-bound witnesses', ['lake', 'build', 'Witnesses'], ROOT / 'formal')
        if args.official:
            import json
            cfg = json.loads((ROOT / 'challenges.json').read_text())
            source = args.submissions.resolve()
            present = [t for t in cfg['tracks'] if (source / t['submission_root'] / 'Solution.lean').is_file()]
            if not present:
                print(f'No submission roots found in {source}', file=sys.stderr)
                return 1
            for track in present:
                check(f"official pipeline {track['slug']}",
                      [sys.executable, 'verifier/verify.py', track['slug'], '--source', str(source)])
    except (subprocess.CalledProcessError, OSError) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        return 1
    print('\nRequested local checks passed. Browser and Linux deployment acceptance are separate checks.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
