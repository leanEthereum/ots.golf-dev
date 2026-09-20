#!/usr/bin/env python3
"""Validate the owner registry and its SVGs using only Python's standard library."""
import argparse
from pathlib import Path

from app.signature_diagram_format import (MAX_IMAGE_BYTES, MAX_REGISTRY_BYTES, MAX_TOTAL_BYTES,
                                          parse_registry, validate_svg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    args = parser.parse_args()
    try:
        with args.registry.open("rb") as file:
            entries, errors = parse_registry(file.read(MAX_REGISTRY_BYTES + 1))
        total, seen = 0, set()
        root = args.registry.resolve().parent
        for sid, entry in entries.items():
            try:
                path = (root / entry["image"]).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("image must remain in the submissions repository")
                with path.open("rb") as file:
                    raw = file.read(MAX_IMAGE_BYTES + 1)
                width, height = validate_svg(raw)
                if path not in seen:
                    seen.add(path)
                    total += len(raw)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("diagram images exceed 16 MiB together")
                print(f"{sid}: {entry['image']} ({width:g} × {height:g})")
            except (OSError, ValueError) as exc:
                errors[sid] = str(exc)
        for sid, error in errors.items():
            print(f"ERROR {sid}: {error}")
        return int(bool(errors))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
