"""`hermes receipts <file>` — probe the claims in a text file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hermes receipts",
        description="Probe every checkable claim in a text file or stdin.")
    ap.add_argument("path", help="file to check ('-' reads stdin)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--max", type=int, default=25, help="max claims to probe")
    a = ap.parse_args(argv)
    text = Path(a.path).read_text() if a.path != "-" else sys.stdin.read()
    vs = core.adjudicate(text, a.timeout, a.max)
    if a.json:
        print(json.dumps([v.to_dict() for v in vs], indent=2))
    else:
        print(core.render_block(vs).lstrip("\n"))
    return 1 if any(v.status == core.MISS for v in vs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
