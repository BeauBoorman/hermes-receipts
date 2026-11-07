"""Sidecar dataset bindings — lets bare stat claims graduate from ⚠️ to ✅/❌.

A `receipts.yaml` file (minimal flat subset, stdlib-parsed — no PyYAML dep)
names the dataset behind a stat claim so "47 handoffs" becomes checkable:

    # receipts.yaml
    - pattern: handoffs
      dataset: ~/org/vault/sessions/handoffs.org
      method: count_lines

    - pattern: subscriptions
      dataset: ~/projects/hermes-receipts/fixtures/subscriptions_fixture.csv
      method: count_rows

    - pattern: waste
      dataset: ~/projects/hermes-receipts/fixtures/subscriptions_fixture.csv
      method: sum_column
      column: Amount

Methods:
  count_lines   — non-empty lines in file (optionally matching `selector` regex)
  count_rows    — CSV data rows, skipping `_`-prefixed meta rows
                  (optional `column` + `value` equality filter)
  sum_column    — float sum of `column` over data rows (optional `value` filter)

If the dataset is missing or unreadable the verdict is UNVERIFIED, never MISS —
a binding that cannot run is not evidence of fabrication.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path

SIDECAR_NAME = "receipts.yaml"


@dataclass
class Binding:
    pattern: str          # word that must appear in the claim text
    dataset: str          # path (~/ and $VAR expanded at probe time)
    method: str           # count_lines | count_rows | sum_column
    column: str | None = None
    value: str | None = None
    selector: str | None = None  # regex for count_lines


def _parse(text: str) -> list[Binding]:
    """Parse the flat subset: '- key: v' starts an entry, '  key: v' continues."""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        m = re.match(r"^\s*-\s+(\w+):\s*(.*)$", line)
        if m:
            out.append({m.group(1): m.group(2).strip().strip("'\"")})
            continue
        m = re.match(r"^\s+(\w+):\s*(.*)$", line)
        if m and out:
            out[-1][m.group(1)] = m.group(2).strip().strip("'\"")
    return [Binding(**d) for d in out if "pattern" in d and "dataset" in d and "method" in d]


def load_sidecar(path: str | Path) -> list[Binding]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        return _parse(p.read_text())
    except OSError:
        return []


def discover(base_dir: str | Path | None = None) -> list[Binding]:
    """Auto-discover receipts.yaml: base_dir (or cwd), then ~/.hermes/."""
    cands = []
    if base_dir:
        cands.append(Path(base_dir) / SIDECAR_NAME)
    cands += [Path.cwd() / SIDECAR_NAME,
              Path.home() / ".hermes" / SIDECAR_NAME]
    for c in cands:
        if c.is_file():
            return load_sidecar(c)
    return []


def _data_rows(path: Path, column: str | None, value: str | None):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if column and column not in (reader.fieldnames or []):
            raise KeyError(column)
        for row in reader:
            first = next(iter(row.values()), "")
            if str(first).startswith("_"):     # _meta provenance rows
                continue
            if column and value and str(row.get(column, "")) != value:
                continue
            yield row


def evaluate(b: Binding) -> float | None:
    """Run the binding's method against its dataset. None = could not run."""
    path = Path(os.path.expandvars(os.path.expanduser(b.dataset)))
    if not path.is_file():
        return None
    try:
        if b.method == "count_lines":
            sel = re.compile(b.selector) if b.selector else None
            n = 0
            for line in path.read_text(errors="replace").splitlines():
                if line.strip() and (sel is None or sel.search(line)):
                    n += 1
            return float(n)
        if b.method == "count_rows":
            return float(sum(1 for _ in _data_rows(path, b.column, b.value)))
        if b.method == "sum_column":
            if not b.column:
                return None
            total = 0.0
            for row in _data_rows(path, b.column, b.value):
                cell = str(row.get(b.column, "")).replace(",", "").replace("$", "")
                m = re.match(r"^-?\d+(\.\d+)?$", cell)
                if m:
                    total += float(cell)
            return round(total, 2)
    except (OSError, KeyError, csv.Error, re.error):
        return None
    return None


def match(claim_text: str, bindings: list[Binding]) -> Binding | None:
    """First binding whose pattern word appears in the claim text."""
    low = claim_text.lower()
    for b in bindings:
        if re.search(rf"\b{re.escape(b.pattern.lower())}\b", low):
            return b
    return None
