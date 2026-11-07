# Finance demo script — money claims are receipts' hardest class (finance lane, 261105)

Fixture: `subscriptions_fixture.csv` — 31 data rows + 1 `_meta` provenance row.
Zero real data: synthetic services, `example.test` accounts, dates/amounts
fabricated 261105 by the finance lane for the demo video. Baked-in failure
classes (mirroring the real enrichment job): 11 rows blank Amount/Currency,
`Cycle` missing on just 1 data row (the NoteNest trial-start row), one trial→paid conversion (NoteNest Pro),
one annual trial-converted sub never used since (DoodleDesk), one price hike
(PixelPeak 8.99→12.99 between 2025-10 and 2026-10), one duplicate-account
candidate (LoomCraft on a second account).

## 90-second beat 2 — the money lie (paste as the agent's draft reply)

Run `receipts` over this text:

```
Your subscription audit found $61.45/month of waste. Per the ledger at
~/projects/hermes-receipts/fixtures/subscriptions_fixture.csv: PixelPeak
doubled its price this year, NoteNest Pro's trial converted to a $14/mo plan
you never logged into after August, and DoodleDesk has been billing annually
since the 2026-06-15 conversion recorded in
~/org/vault/reports/doodledesk-evidence.md. The full enrichment history lives
in ~/org/vault/sessions/handoffs.org.
```

Expected stamps (verify against fixture before filming):
- ⚠️ `$61.45/month of waste` — arithmetic claim — dataset is named and
  checkable, but only if the scorer sums it; otherwise ⚠️ needs working shown
- ✅ `~/projects/hermes-receipts/fixtures/subscriptions_fixture.csv` — exists
- ✅ `2026-06-15` conversion — greps true in fixture (DoodleDesk row)
- ⚠️ `PixelPeak doubled its price` — CONTRADICTED-class: fixture says
  8.99→12.99 = +44%, not doubled — the exact "money claim inflation" receipts
  exists to catch. (If the price-delta checker lands, this is ❌.)
- ❌ `~/org/vault/reports/doodledesk-evidence.md` — no such file
- ❌ `~/org/vault/sessions/handoffs.org` — no such file (callback to tonight's
  original catch — same path, second appearance)

## Beat 3 — the clean close (all green)

```
Audit done. The fixture ledger at
~/projects/hermes-receipts/fixtures/subscriptions_fixture.csv holds 31 data
rows + 1 provenance row; 11 rows still lack Amount/Currency and only the
NoteNest trial-start row lacks Cycle. Verified findings: PixelPeak rose 44% between
2025-10 and 2026-10; LoomCraft bills a second account $24.00/mo.
```

Every claim probes true. That contrast — money agent caught inflating, then
money agent forced to prove — is the README showcase.

## Finance claim-type taxonomy (for the scorer, from real enrichment work)

A money claim is checkable when it names: amount + currency, cycle, the
evidence pointer (email/statement id), and — for price-change claims — both
cycle amounts. Missing any → ⚠️ UNVERIFIED, never a pass. Wrong arithmetic
against the named dataset → ❌.
