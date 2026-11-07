# receipts

**Every agent response ships with a RECEIPTS block: each filesystem path, URL, and stat the agent cites is probed live and stamped verified or refuted.**

```
hermes plugins install receipts
```

Agents cite evidence constantly — file paths, URLs, "N of M" counts — and users have no way to tell a checked claim from a fabricated one. `receipts` closes that gap mechanically: a `transform_llm_output` hook intercepts every outgoing reply on **every platform** (Discord, Telegram, CLI, cron, Desktop — zero adapter code), extracts checkable claims, probes them, and appends the receipt block. Warn-only: it annotates, never blocks a send. A model that hallucinates its own all-✅ RECEIPTS block gets it stripped and re-probed (the self-stamp bypass is tested end-to-end).

Scope: **fabricated paths, dead links, ghost stats.** It does not judge reasoning, tone, or truth of prose — only whether cited evidence exists where the agent says it does.

## Verdict states

| State | Meaning |
|---|---|
| ✅ VERIFIED | Content-checked locally (file exists / dataset row-count matches the claim) |
| 📍 LOCATABLE | Reachable but not content-checked (e.g. URL returns 200; honest about what was proven) |
| ⚠️ UNVERIFIABLE | Cannot-check-here: foreign-machine paths (`/var`, `/etc`, Windows-drive roots), unreachable URLs, stats with no named dataset. Never a pass, never a false ❌ |
| ❌ REFUTED | Probe ran on local evidence and the claim is false (path under an owned root doesn't exist; sidecar count contradicts the claim) |
| ⊘ SKIPPED | Visibly skipped: code fences, API route fragments, version/section fractions. Silence is a test failure — every skip renders |

## Benchmark card

Measured on Apple Silicon, commit `b0951a9` (`eval/REPORT.md`, deterministic score; timing cells vary per run — ranges given):

- **Verdict accuracy:** 11/11 labeled claims correct (100%) across the 10-case eval corpus; 0 extraction misses (gate B1: silence is failure)
- **Local-path claims:** ≤5 ms per reply at 25 claims (0–3 ms measured across fresh runs); no network involved
- **Remote URLs:** probed in parallel under a 3s-per-probe wall budget — 8 blackholed URLs complete in ~5s total wall (40–60s serial before the Gate-A thread pool)
- **p95 engine time:** 0.2–0.7s per corpus case across fresh runs (corpus includes live network probes)
- **Model calls:** zero — probes are `stat()`, HTTP HEAD/GET, and row counts

## vs. the neighbors (the verification lane is crowded — this is the mechanism diff)

| Plugin | Mechanism | Diff |
|---|---|---|
| `provenance-gate` | Flags memory/skill writes that claim a user decision without the user's verbatim words | Guards *what the agent remembers*, not the evidence it cites in replies |
| `hermes-verifier` | Independent advisor model reviews each turn delta, raises findings | Second LLM judging reasoning; `receipts` is deterministic probing of cited evidence — no model calls |
| `agent-ledger` | Write-ahead SQLite ledger of every state-changing tool call | Records side effects *after* tools run; doesn't probe the claims in the reply the user reads |
| `tracekit` | Pre-call signer gates every tool call, signs calls + outcomes into an offline-verifiable run | Sign-what-ran vs. probe-what's-claimed: a signed run can still contain an uncited fabricated path in prose |
| `epistemic-harness` | Prediction-before-check tracking with revision history | Discipline for forecasts, not existence-proof of cited evidence |
| `invinoveritas-receipts` | Signed receipts for approval-verdict decisions and iteration-exhaustion turns | Receipts about *the agent's own control flow*; name collision on "receipts" noted — different artifact entirely |

**The open seat:** all six are scoped or pull-based. None is an always-on, platform-agnostic, reply-time middleware that mechanically probes every checkable claim in ordinary outgoing text. Mechanism grounded in NabaOS (arXiv 2603.10060): HMAC tool receipts + claim classification detect 91% of hallucinated agent claims at <15ms.

## Layout

```
receipts/
├── plugin.yaml     # manifest (name, provides_tools/hooks/commands)
├── __init__.py     # register(ctx): hook + tool + CLI command
├── core.py         # claim extraction, probes, five-state verdicts, render
├── cli.py          # `hermes receipts` / /receipts entry
└── sidecar.py      # receipts.yaml: bind "N of M" stats to a dataset so counts check
```

**Sidecar stats.** Bare counts ("31 subscriptions") are ⚠️ until a `receipts.yaml` names their dataset — see the worked example at the repo root (`receipts.yaml`), which binds the demo fixture. Discovery: `$PWD/receipts.yaml`, then `~/.hermes/receipts.yaml`. With a binding the claim graduates to ✅ (count matches) or ❌ (refuted, true count named).

Config via env: `HERMES_RECEIPTS_MAX` (claim cap, default 25), `HERMES_RECEIPTS_TIMEOUT` (probe budget, default 5s).

## Disclosure

- URL probes issue live HTTP HEAD/GET requests to cited hosts (timeout-capped)
- Local probes `stat()` cited paths under the user's home/tmp roots; foreign-root paths are never probed, only marked ⚠️
- No telemetry, no model calls, no credentials read; state is per-session only

## Catalog submission checklist

- [ ] Public GitHub repo, installable tree at the pinned commit
- [ ] `plugin-catalog/receipts.yaml` PR with full 40-char SHA pin; owner-or-major-contributor submitter; **`subdir: receipts/`** — the manifest lives one level down and the loader won't find it without this field
- [ ] `capabilities:` matches exactly what registers — one hook (`transform_llm_output`), one tool (`receipts_check`), one command (`receipts`); no undeclared surfaces (rule 6 treats drift as security)
- [ ] Network-call disclosure line above mirrored into the PR description (rule 13)
- [ ] `hermes plugins validate /path/to/receipts --install-deps` green locally before the PR (same check CI runs)
- [ ] No self-updating code, no core overrides — plugin surface only (rules 3, 9)
