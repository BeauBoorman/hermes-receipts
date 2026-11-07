# `receipts` eval report

Core under test: `receipts/core.py`
Corpus: 10 cases, 11 labeled claims

## Verdict-class accuracy (vs. spec four-state ground truth)

| truth | correct | wrong | precision |
|---|---|---|---|
| VERIFIED | 1 | 0 | 1.00 |
| LOCATABLE | 1 | 0 | 1.00 |
| UNVERIFIED | 3 | 0 | 1.00 |
| REFUTED | 2 | 0 | 1.00 |
| SKIPPED | 4 | 0 | 1.00 |

**Overall: 11/11 labeled claims judged correctly (100.0%)**

## Extraction misses (labeled claim, no matching verdict — gate B1: silence is failure)

- none

## Wrong-state details (id, claim, wanted, got)

- none

## Wall-time overhead (local-path claims only; deterministic)

| claims/reply | ms |
|---|---|
| 0 | 0 |
| 3 | 0 |
| 10 | 1 |
| 25 | 1 |

_p95 engine time across corpus cases: 271ms_

_Note: URL-reachability ✅ in v0.1 scores as wrong against LOCATABLE truth — that is the spec A4 four-state gap, quantified here on purpose._