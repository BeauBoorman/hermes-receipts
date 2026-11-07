# `receipts` hardening spec — v0.1 → submission cut

Owner: Dev Design (build) · Support: Coder (sidecar datasets), research-oracle (extraction suite),
Research-Desk (catalog diff README + submission mechanics), Financial (finance fixtures, shipped),
Devils Advocate (gate verification), Barnaby (post-merge regression).
Beau's ruling 261105: "best methods, most elegant solutions, tuned and optimized for speed and cost,
all t's crossed and i's dotted."

## A. Ship-blocker fixes (before any catalog PR)

A1. **Parallel probes + wall budget.** Replace serial probing: thread-pool, global ~3s wall budget,
negative-cache for failed probes (TTL ~10 min, capped entries). DA measured 4 blackholed URLs = 12s,
20 = 60s. Target: p95 overhead <300ms on a typical reply (≤5 claims).
A2. **Remote-machine path guard.** ❌ only for paths under a known local root ($HOME, workspace,
/tmp scratch); everything else → ⚠️ UNVERIFIED (reachable-not-provable). Delete or implement the
"remote paths degrade to ⚠️" README claim — announced design must equal shipped code.
A3. **Self-stamp bypass fix.** Strip any pre-existing `**RECEIPTS**` block from input before probing;
re-probe; flag "self-stamped block replaced" with ⚠️. A hallucinated all-✅ block must never survive.
A4. **Four-state verdicts.** ✅ verified (content-checked: quoted line re-grepped from fetched page /
path content matched) · 📍 reachable (URL resolves, content unchecked) · ⚠️ uncheckable ·
❌ refuted (probe ran, claim contradicted). ✅ NEVER for bare reachability — Eng Design's "the ✅ lies"
attack, verified real (Barnaby's 54%-users-vs-organizations counterexample).

## B. Extraction robustness (research-oracle's lane)

B1. `/var/...`, `/Volumes/...` blanket-skip bug: narrow the version-fragment guard to `/v\d+/`
fragments; every plausible path/URL in input yields a Verdict or an explicit SKIPPED marker —
silence is a test failure. Add invariant test.
B2. Windows path support (`C:\logs\x.log`) — Hermes runs on Windows; add regex + tests.
B3. API-route false-❌ (Research's own repro): `/channels/<id>`, `GET/POST`-prefixed tokens,
unanchored fragments → ⚠️ never ❌. Test #8.
B4. Fraction/nag regex: "v2.3.4/5", "section 3/4" must not flag. Test.

## C. Cost & speed tuning (Beau's explicit ask)

C1. Zero model calls — probes are stdlib HTTP HEAD/GET + filesystem only. Keep it that way; verify
no aux-model path sneaks in.
C2. URL probe budget: cap concurrent connections (4), per-probe timeout 3s (down from 5s), only
first N URLs per reply (default 5, configurable). Content-check (A4) only on demand via the
`receipts_check` tool, not on every reply.
C3. Startup cost: no network at plugin load; lazy-init the cache.
C4. Benchmark table in README: measured overhead on 0/3/10/25-claim replies. Numbers, not adjectives.

## D. Correctness gates (t's crossed)

D1. Test suite ≥ 25 tests covering: all four verdict states, extraction exhaustiveness (B1),
self-stamp strip (A3), fraction regex (B4), API-route deny-list (B3), Windows paths (B2),
remote-path guard (A2), probe budget (C2).
D2. Truncated-turn guard: `transform_llm_output` fires on error/interrupt/limit-cut text — skip
stamping on non-normal turn ends (Barnaby's hooks-doc finding).
D3. `hermes plugins validate --install-deps` green.
D4. plugin.yaml capabilities: exactly what registers (hook + tool + command — all three declared,
rule 6 capability-match).
D5. Disclosure lines: HTTP HEAD/GET probes, cache location, no telemetry — catalog rule 13.
D6. README "vs. neighbors" table: provenance-gate, hermes-verifier, agent-ledger, tracekit,
epistemic-harness, invinoveritas-receipts — one mechanism line each. Rename if the
invinoveritas name collision bothers maintainers.
D7. README fixes: plugin.yaml path (`receipts/plugin.yaml`, not repo root), demo scope wording
("fabricated paths, dead links, ghost stats" — not "catches an agent lying").

## E. Demo (90s, uncut)

E1. Beats: cold open on the retracted pitch → ❌s fire with probe output → ⚠️ unreachable/
foreign-machine case (degrades honestly — never false-positives) → four-state verdicts shown →
clean post all green → finance fixture beat (arithmetic-against-named-dataset ❌ on inflated
"doubled its price" vs +44%) → final frame `hermes plugins install receipts`.
E2. Show the benchmark numbers (C4) in the end card.

## F. Ship sequence

1. Dev Design lands A1–A4 in one PR (the 90-minute cut).
2. research-oracle lands B1–B4 with tests.
3. Coder sidecar `receipts.yaml` dataset-naming (⚠️→✅/❌ upgrade for stats).
4. DA runs the gate: re-executes every claim in the README against the code.
5. Research-Desk: catalog PR checklist + diff README.
6. Film demo → submit by Nov 11, 5PM EST.
