#!/usr/bin/env python3
"""Assemble probe corpus items from staged (defective module + defect spec) pairs.

For each `corpus_probe/staging/<mod>__defective.py` + `<mod>__defects.json`, build a
corpus item under `corpus_probe/code/probe-NNNN/`:
  artifact.diff  — the defective module as a new-file unified diff (unit src/<mod>.py)
  meta.json      — synthetic provenance + gray zones + defect_count
  defects.json   — each seeded defect with a resolved post-image line + anchor + paraphrases

Defects start `confirmed: false` (the freeze gate refuses until the USER R/F/U-audits).
Anchors are resolved to their unique post-image line; a missing/ambiguous anchor is
reported and that item is skipped.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "corpus_probe"
STAGING = PROBE / "staging"
CODE = PROBE / "code"


def new_file_diff(code: str, unit: str) -> str:
    lines = code.splitlines()
    hdr = [f"diff --git a/{unit} b/{unit}", "new file mode 100644",
           "index 0000000..1111111", "--- /dev/null", f"+++ b/{unit}",
           f"@@ -0,0 +1,{len(lines)} @@"]
    return "\n".join(hdr + ["+" + ln for ln in lines]) + "\n"


def find_line(code_lines, anchor):
    hits = [i + 1 for i, ln in enumerate(code_lines) if anchor in ln]
    return hits[0] if len(hits) == 1 else (None if not hits else -len(hits))


def main():
    mods = sorted(p.name[: -len("__defective.py")] for p in STAGING.glob("*__defective.py"))
    if not mods:
        print("no staged modules found", file=sys.stderr); return 2
    CODE.mkdir(parents=True, exist_ok=True)
    problems = []
    for idx, mod in enumerate(mods, 1):
        pid = f"probe-{idx:04d}"
        code = (STAGING / f"{mod}__defective.py").read_text(encoding="utf-8")
        spec = json.loads((STAGING / f"{mod}__defects.json").read_text(encoding="utf-8"))
        code_lines = code.splitlines()
        unit = f"src/{mod}.py"

        defects = []
        for k, d in enumerate(spec.get("defects", []), 1):
            anchor = d["anchor"]
            ln = find_line(code_lines, anchor)
            if ln is None:
                problems.append(f"{pid} d{k}: anchor NOT FOUND: {anchor!r}"); continue
            if ln < 0:
                problems.append(f"{pid} d{k}: anchor AMBIGUOUS ({-ln} hits): {anchor!r}"); continue
            defects.append({
                "id": f"{pid}-d{k}", "category": d.get("category", "logic"),
                "severity": d.get("severity", "major"), "description": d["description"],
                "location": {"unit": unit, "start": ln, "end": ln},
                "anchor": anchor, "paraphrases": d.get("paraphrases", []),
                "confirmed": False,
                "rationale": f"Correct form: {d.get('correct_form','')!r}. LLM-seeded; PENDING human R/F/U audit.",
            })

        gz = []
        for z in spec.get("gray_zones", []):
            aln = z.get("approx_line") or 1
            aln = max(1, min(aln, len(code_lines)))
            gz.append({"location": {"unit": unit, "start": aln, "end": aln},
                       "note": z.get("note", "pre-existing debatable smell (not a seeded defect)")})

        item = CODE / pid
        item.mkdir(parents=True, exist_ok=True)
        (item / "artifact.diff").write_text(new_file_diff(code, unit), encoding="utf-8")
        (item / "defects.json").write_text(json.dumps({"defects": defects}, indent=1) + "\n", encoding="utf-8")
        meta = {
            "id": pid, "type": "code", "artifact_file": "artifact.diff",
            "title": f"{mod.replace('_', ' ')} (realistic-scale probe)",
            "recipe_version": "0.1.0",
            "source": {"origin": "synthetic", "license": "CC-BY-4.0", "url": None,
                       "notes": "Freshly authored for the realistic-scale probe (uncontaminated); "
                                "defects seeded then human-audited. Not derived from any repo."},
            "construction": {"proposer": "freshly authored (LLM) + LLM-seeded defects - PENDING human R/F/U audit",
                             "transformations": sorted({d["category"] for d in defects})},
            "clean_regions": [{"unit": unit, "start": 1, "end": 1, "note": "module header"}],
            "known_gray_zone": gz,
            "defect_count": len(defects),
        }
        (item / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
        print(f"{pid}: {mod} — {len(defects)} defects, {len(gz)} gray zones, {len(code_lines)} lines")

    if problems:
        print("\nPROBLEMS (fix before validate):", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"\nassembled {len(mods)} probe items under {CODE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
