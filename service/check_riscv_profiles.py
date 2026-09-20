#!/usr/bin/env python3
"""Check owner-maintained profile data offline; this does not certify an execution.

python3 service/check_riscv_profiles.py ../ots.golf-submissions/riscv-profiles.json
"""
import argparse
from pathlib import Path

from app.riscv_profile_format import MAX_BYTES, parse_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    args = parser.parse_args()
    try:
        with args.registry.open("rb") as source:
            profiles, errors = parse_registry(source.read(MAX_BYTES + 1))
        for sid, profile in profiles.items():
            print(f"{sid}: {profile['executions']} instructions, {profile['cycles']} cycles")
        for sid, error in errors.items():
            print(f"INVALID {sid}: {error}")
        if errors:
            return 1
        print(f"Valid registry: {len(profiles)} profile(s).")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Invalid registry: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
