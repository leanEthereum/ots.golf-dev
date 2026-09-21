#!/usr/bin/env python3
"""Recheck the audited pre-limit images with Lean, preserving original result identities.

Run with a submissions Git checkout containing the retained source commits. This audits
the frozen catalog, not arbitrary submissions; new submissions use the official comparator.
Historical OTS certificates remain the original verdicts. Only image lengths are rechecked.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = "formal/Submissions/UpperRiscv/"


def check(submissions: Path) -> None:
    catalog = json.loads((ROOT / "service/riscv-program-sizes.json").read_text())["measurements"]
    for sid, value in catalog.items():
        def source(name):
            return subprocess.check_output(
                ["git", "-C", str(submissions), "show", f'{value["commit"]}:{SUBMISSION}{name}.lean'],
                text=True)

        program, candidate, solution = source("Program"), source("Candidate"), source("Solution")
        namespace = re.search(r"^namespace (OptimalOTS\.Riscv(?:Upper|2)Program)$", program, re.M)
        if not namespace:
            raise ValueError(f"{sid}: unaudited program layout")
        image = namespace[1] + ".image"
        short_image = image.removeprefix("OptimalOTS.")
        if (f"  image := {short_image}\n" not in candidate or
                "noncomputable def submission : Riscv.Submission where\n" not in candidate or
                "noncomputable def submission : Riscv.Submission := RiscvUpperForest.submission\n" not in solution):
            raise ValueError(f"{sid}: review the submitted image binding")
        prefix = "import OptimalOTS.RiscvMachine\n"
        if "import Submissions.UpperRiscv.Constants\n" in program:
            constants = source("Constants")
            # The audited images use only these unchanged numeric definitions.
            # Drop subsequent, unrelated historical proof lemmas, some of whose
            # tactic names no longer exist. No value definition is rewritten.
            if "\ntheorem levVal_lt " not in constants:
                raise ValueError(f"{sid}: unaudited constants layout")
            prefix += constants.split("\ntheorem levVal_lt ", 1)[0].replace("import Mathlib\n", "")
            prefix += "\nend OptimalOTS.Flat\n"
        imports = re.findall(r"^import (.+)$", program, re.M)
        if set(imports) - {"OptimalOTS.RiscvMachine", "Submissions.UpperRiscv.Constants"}:
            raise ValueError(f"{sid}: unaudited program imports")
        program = re.sub(r"^import .+\n", "", program, flags=re.M)
        proof = f"""
set_option maxRecDepth 100000
set_option maxHeartbeats 0
theorem historical_image_lengths :
    {image}.code.length = {value['instructions']} ∧
    {image}.data.length = {value['data_bytes']} := by decide +kernel
theorem historical_image_limit : {image}.byteSize < 1048576 := by
  unfold OptimalOTS.Riscv.Image.byteSize
  rw [historical_image_lengths.1, historical_image_lengths.2]
  decide
#print axioms historical_image_lengths
#print axioms historical_image_limit
"""
        with tempfile.TemporaryDirectory(prefix="ots-size-audit-") as temporary:
            path = Path(temporary) / "ImageAudit.lean"
            path.write_text(prefix + program + proof)
            subprocess.run(["lake", "env", "lean", str(path)], cwd=ROOT / "formal", check=True)
        total = 4 * value["instructions"] + value["data_bytes"]
        print(f"{sid}: {total:,} bytes < 1,048,576; kernel checked", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submissions", type=Path)
    check(parser.parse_args().submissions.resolve())
