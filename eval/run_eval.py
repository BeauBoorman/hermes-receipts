#!/usr/bin/env python3
"""Labeled evaluation corpus runner for `receipts`.

Measures what the hardening spec (gate C4/D1) demands:
  - verdict-class accuracy vs. labeled ground truth (spec four-state model)
  - extraction recall: labeled claims the engine never surfaced (silence = failure, gate B1)
  - wall-time overhead per synthetic reply at 0/3/10/25 claims (gate C4)

Usage:  python3 eval/run_eval.py [--core path] [--json]
Writes eval/REPORT.md next to this file. Deterministic: no blackholed-URL cases
in the timing set (those are DA's latency measurements, not ours).
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# v0.1 has three states; the spec adds 📍 (reachable-not-content-verified).
# Ground truth uses spec states; the mapper below scores v0.1 honestly:
#   v0.1 "PASS on URL reachability" is labeled wrong when truth is LOCATABLE.
SPEC_STATES = {"VERIFIED", "LOCATABLE", "UNVERIFIED", "REFUTED", "SKIPPED"}


def load_core(path):
    """Load the receipts package (core.py uses relative imports since the sidecar landed)."""
    pkg_dir = Path(path).resolve().parent
    if str(pkg_dir.parent) not in sys.path:
        sys.path.insert(0, str(pkg_dir.parent))
    import importlib
    spec = importlib.util.find_spec("receipts.core")
    if spec is None:
        raise ImportError(f"receipts.core not importable from {pkg_dir.parent}")
    mod = importlib.import_module("receipts.core")
    return mod


def verdict_state(v):
    """Normalize a core.Verdict to a spec state string."""
    s = str(getattr(v, "state", getattr(v, "status", v))).upper()
    if "UNVERIF" in s or "WARN" in s:   # must precede VERIFIED: "UNVERIFIED" contains it
        return "UNVERIFIED"
    if "SKIP" in s:
        return "SKIPPED"
    if "MISS" in s or "REFUT" in s or "FAIL" in s:
        return "REFUTED"
    if "LOCAT" in s or "REACH" in s:    # must precede PASS: locatable ≠ verified
        return "LOCATABLE"
    if "PASS" in s or "VERIFIED" in s or "OK" in s:
        return "VERIFIED"
    return s or "UNKNOWN"


def run(corpus, core, verbose=False):
    rows = []
    for case in corpus:
        t0 = time.perf_counter()
        try:
            verdicts = core.adjudicate(case["text"])
        except Exception as e:  # engine crash on a case is itself a finding
            verdicts = []
            rows.append({"id": case["id"], "error": f"{type(e).__name__}: {e}",
                         "elapsed": time.perf_counter() - t0,
                         "expected": case["expected"], "got": []})
            continue
        elapsed = time.perf_counter() - t0
        def _claim_text(v):
            c = getattr(v, "claim", None)
            return getattr(c, "text", None) or getattr(c, "target", None) or str(c) or "?"
        got = [{"claim": _claim_text(v), "state": verdict_state(v)} for v in verdicts]
        rows.append({"id": case["id"], "elapsed": elapsed,
                     "expected": case["expected"], "got": got})
        if verbose:
            print(case["id"], [g["state"] for g in got])
    return rows


def score(rows):
    """Per-case: every labeled claim must be matched by exactly one verdict with the right state."""
    per_class = {s: {"correct": 0, "wrong": 0} for s in SPEC_STATES}
    matched_ids, missed = set(), []
    wrong_details = []
    for r in rows:
        if "error" in r:
            missed.append((r["id"], "ENGINE-ERROR " + r["error"]))
            continue
        got_by_claim = {}
        for g in r["got"]:
            key = str(g["claim"])  # Claim dataclass is unhashable — normalize to str
            got_by_claim.setdefault(key, []).append(g["state"])
        for exp in r["expected"]:
            claim, want = exp["claim"], exp["state"]
            got = got_by_claim.get(claim)
            if not got:
                missed.append((r["id"], claim))
                per_class[want]["wrong"] += 1
                continue
            # exact-claim match (fuzzy matching is a v2 problem; corpus uses verbatim spans)
            if want in got:
                per_class[want]["correct"] += 1
            else:
                per_class[want]["wrong"] += 1
                wrong_details.append((r["id"], claim, want, got))
    return per_class, missed, wrong_details


def timing_bench(core, tmpdir):
    """Gate C4: wall-time on synthetic replies with 0/3/10/25 checkable claims.
    Deterministic: local files only (create N temp files, cite them)."""
    results = {}
    for n in (0, 3, 10, 25):
        files = []
        for i in range(n):
            f = tmpdir / f"bench_{n}_{i}.txt"
            f.write_text(f"bench fixture {i}\n")
            files.append(str(f))
        text = ("Status update. " if n == 0 else
                "Verified items: " + " ".join(f"`{f}`" for f in files) +
                " plus prose that carries no claims.")
        t0 = time.perf_counter()
        core.adjudicate(text)
        results[n] = (time.perf_counter() - t0) * 1000
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default=str(REPO / "receipts" / "core.py"))
    ap.add_argument("--json", action="store_true", help="also dump rows to eval/results.json")
    args = ap.parse_args()

    corpus = [json.loads(l) for l in
              (HERE / "corpus.jsonl").read_text().splitlines() if l.strip()]
    core = load_core(args.core)
    rows = run(corpus, core)
    per_class, missed, wrong_details = score(rows)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        timing = timing_bench(core, Path(td))

    # Relative path in the report: it is a published artifact and must not
    # embed the build machine's home directory (Financial privacy sweep + DA
    # carry-forward nit; a re-run must not resurrect the absolute path).
    shown = os.path.relpath(Path(args.core), HERE.parent) \
        if os.path.isabs(args.core) else args.core
    lines = ["# `receipts` eval report", "",
             f"Core under test: `{shown}`",
             f"Corpus: {len(corpus)} cases, {sum(len(c['expected']) for c in corpus)} labeled claims",
             ""]
    lines += ["## Verdict-class accuracy (vs. spec four-state ground truth)", "",
              "| truth | correct | wrong | precision |", "|---|---|---|---|"]
    for s in ("VERIFIED", "LOCATABLE", "UNVERIFIED", "REFUTED", "SKIPPED"):
        c, w = per_class[s]["correct"], per_class[s]["wrong"]
        p = f"{c/(c+w):.2f}" if c + w else "—"
        lines.append(f"| {s} | {c} | {w} | {p} |")
    tot_c = sum(v["correct"] for v in per_class.values())
    tot_w = sum(v["wrong"] for v in per_class.values())
    lines += ["", f"**Overall: {tot_c}/{tot_c+tot_w} labeled claims judged correctly "
              f"({tot_c/(tot_c+tot_w):.1%})**",
              "", "## Extraction misses (labeled claim, no matching verdict — gate B1: silence is failure)", ""]
    lines += [f"- `{cid}`: {claim}" for cid, claim in missed] or ["- none"]
    lines += ["", "## Wrong-state details (id, claim, wanted, got)", ""]
    lines += [f"- `{cid}` `{claim}` want={want} got={got}" for cid, claim, want, got in wrong_details] or ["- none"]
    lines += ["", "## Wall-time overhead (local-path claims only; deterministic)", "",
              "| claims/reply | ms |", "|---|---|"]
    for n, ms in timing.items():
        lines.append(f"| {n} | {ms:.0f} |")
    lines += ["", f"_p95 engine time across corpus cases: {statistics.quantiles([r['elapsed'] for r in rows], n=20)[-1]*1000:.0f}ms_",
              "", "_Note: URL-reachability ✅ in v0.1 scores as wrong against LOCATABLE truth — that is the"
              " spec A4 four-state gap, quantified here on purpose._"]
    report = "\n".join(lines)
    (HERE / "REPORT.md").write_text(report)
    if args.json:
        (HERE / "results.json").write_text(json.dumps(rows, indent=1))
    print(report)


if __name__ == "__main__":
    main()
