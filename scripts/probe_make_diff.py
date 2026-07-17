#!/usr/bin/env python3
"""Turn a (defect-injected) Python module into a new-file unified diff = artifact.diff.

Post-image line numbers (what defect `location`/`anchor` reference) are 1..N over the
`+` lines, matching corpus._diff_postimage_lines. Also prints numbered post-image lines
so seeded-defect locations are easy to read off.

Usage:
  python scripts/probe_make_diff.py <module.py> <unit-path> [--out artifact.diff] [--show]
  e.g. python scripts/probe_make_diff.py /tmp/token_bucket.py src/token_bucket.py --out .../artifact.diff
"""
import argparse
import sys
from pathlib import Path


def make_diff(code: str, unit: str) -> str:
    lines = code.splitlines()
    n = len(lines)
    body = [f"diff --git a/{unit} b/{unit}",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            f"+++ b/{unit}",
            f"@@ -0,0 +1,{n} @@"]
    body += ["+" + ln for ln in lines]
    return "\n".join(body) + "\n"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("module")
    ap.add_argument("unit")
    ap.add_argument("--out", default=None)
    ap.add_argument("--show", action="store_true", help="print numbered post-image lines")
    args = ap.parse_args(argv[1:])
    code = Path(args.module).read_text(encoding="utf-8")
    diff = make_diff(code, args.unit)
    if args.out:
        Path(args.out).write_text(diff, encoding="utf-8")
        print(f"wrote {args.out} ({len(code.splitlines())} post-image lines)")
    else:
        sys.stdout.write(diff)
    if args.show:
        for i, ln in enumerate(code.splitlines(), 1):
            print(f"{i:4} | {ln}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
