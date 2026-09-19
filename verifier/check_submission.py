#!/usr/bin/env python3
"""Check a submission root against the contract's policy, before anything is compiled.

    check_submission.py TRACK [--root DIR] [--json]

Checks: the root is flat and holds only `.lean` files, `claim.txt`, and optional `NOTES.md` and
`README.md`;
`Solution.lean` exists; the claim is canonical; each explicit source-header import names a
permitted library, contract module, or sibling file; the size limits hold. Exit 0 iff these
source-policy checks pass. This does not restrict transitive imports or runtime module loads by
metaprograms, nor certify proof provenance. Soundness is comparator's job.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import LEAN_FILE_RE, ContractError, load_challenges, read_claim, repo_root, track  # noqa: E402

OTHER_ALLOWED = {"claim.txt", "NOTES.md", "README.md"}
# Lean quoted identifiers can contain path separators and `..`. Never treat an arbitrary
# string starting with "Mathlib." or "VCVio." as a module inside that library.
MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")


def strip_comments(text: str) -> str:
    """Replace comments with whitespace for header scanning, preserving token boundaries.

    In particular, `module/- comment -/prelude` must not become `moduleprelude`.
    This is not a lexer for command bodies or quoted identifiers; the header checker stops at
    the first body command and admits only unquoted ASCII module identifiers.
    """
    out, i, depth, n = [], 0, 0, len(text)
    while i < n:
        if text.startswith("/-", i):
            out.append(" ")
            depth += 1
            i += 2
        elif depth and text.startswith("-/", i):
            depth -= 1
            i += 2
        elif depth:
            if text[i] == "\n":
                out.append("\n")
            i += 1
        elif text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def header_imports(text: str) -> tuple[list[str], str | None]:
    """Check ordinary, single-line header imports; return (imports, error).

    Commands after the header can execute arbitrary Lean metaprograms. This function does not
    attempt to inspect their behavior or constrain their runtime module loads.
    """
    imports = []
    for line in strip_comments(text.removeprefix("\ufeff")).splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^prelude\b", s):
            return imports, "`prelude` is not allowed"
        if re.match(r"^module\b|^(?:(?:public|private|meta)\s+)+import\b", s):
            return imports, "use ordinary `import` lines; alternate module headers are not allowed"
        m = re.match(r"^import\s+(\S+)\s*$", s)
        if m:
            if not MODULE_RE.fullmatch(m.group(1)):
                return imports, "module names must be dot-separated, unquoted ASCII identifiers"
            imports.append(m.group(1))
            continue
        if s.startswith("import"):
            return imports, f"malformed import line: {line!r}"
        break
    return imports, None


def check(root: Path, slug: str) -> dict:
    cfg = load_challenges(root)
    t = track(cfg, slug)
    lim = cfg["limits"]
    sub = root / t["submission_root"]
    errors: list[str] = []
    files: list[str] = []
    total = 0

    if sub.is_symlink() or not sub.is_dir():
        return {"ok": False, "track": slug, "errors": [f"missing submission root {t['submission_root']}"]}

    entries = sorted(sub.iterdir())
    if len(entries) > lim["max_files"]:
        return {"ok": False, "track": slug, "errors": [f"more than {lim['max_files']} entries in the submission root"]}
    for p in entries:
        rel = f"{t['submission_root']}/{p.name}"
        if p.is_dir():
            errors.append(f"{rel}: subdirectories are not allowed")
            continue
        if not p.is_file() or p.is_symlink():
            errors.append(f"{rel}: not a regular file")
            continue
        if not (LEAN_FILE_RE.fullmatch(p.name) or p.name in OTHER_ALLOWED):
            errors.append(f"{rel}: only `.lean` files (identifier names), claim.txt, NOTES.md and README.md are admitted")
            continue
        size = p.stat().st_size
        total += size
        if size > lim["max_file_bytes"]:
            errors.append(f"{rel}: {size} bytes exceeds max_file_bytes {lim['max_file_bytes']}")
            continue
        files.append(p.name)

    if len(files) > lim["max_files"]:
        errors.append(f"{len(files)} files exceeds max_files {lim['max_files']}")
    if total > lim["max_total_bytes"]:
        errors.append(f"{total} bytes in total exceeds max_total_bytes {lim['max_total_bytes']}")
    if "Solution.lean" not in files:
        errors.append("Solution.lean is required")

    claim = None
    if "claim.txt" in files:
        try:
            claim = read_claim(sub / "claim.txt", lim["max_claim"])
        except ContractError as exc:
            errors.append(str(exc))
    else:
        errors.append("claim.txt is required")

    siblings = {f[:-5] for f in files if f.endswith(".lean")}
    prefixes = t["allowed_import_prefixes"]
    for name in files:
        if not name.endswith(".lean"):
            continue
        try:
            text = (sub / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{name}: cannot read UTF-8 source: {exc}")
            continue
        imports, err = header_imports(text)
        if err:
            errors.append(f"{name}: {err}")
        for imp in imports:
            # Library namespaces admit submodules; protected contract modules are exact
            # imports, not a license to import arbitrary OptimalOTS descendants.
            if any(imp == pre or (pre in {"Mathlib", "VCVio"} and imp.startswith(pre + "."))
                   for pre in prefixes):
                continue
            if imp.startswith(t["module_prefix"] + "."):
                leaf = imp[len(t["module_prefix"]) + 1:]
                if leaf in siblings and "." not in leaf:
                    continue
                errors.append(f"{name}: import {imp} is not a sibling file of {t['submission_root']}")
                continue
            errors.append(f"{name}: import {imp} is not allowed (allowed: {prefixes} and siblings)")

    return {"ok": not errors, "track": slug, "claim": claim, "files": files, "total_bytes": total, "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("track")
    ap.add_argument("--root", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        res = check(a.root or repo_root(), a.track)
    except ContractError as exc:
        print(f"check_submission: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for e in res["errors"]:
            print(f"error: {e}", file=sys.stderr)
        if res["ok"]:
            print(f"ok: {res['track']} submission, claim {res['claim']}, {len(res['files'])} files, {res['total_bytes']} bytes")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
