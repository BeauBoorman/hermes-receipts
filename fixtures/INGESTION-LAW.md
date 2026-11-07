# Ingestion-law filing for `finance-demo-script.md`

**Exemption:** the demo script cites two local-file sources — `subscriptions_fixture.csv` and the sidecar schema (`receipts.yaml`) — so the law exempts it from linkding. Exemption stated in the report's Method section per TASK-036.

**Workspace:** `~/projects/hermes-receipts/fixtures/`
- `subscriptions_fixture.csv` — 31 data rows, 11 blank Amount/Currency, Cycle missing on 1 row (NoteNest trial-start).
- `receipts.yaml` — three bindings: `31 subscriptions` → ✅, `40 subscriptions` → ❌, `29 subscriptions` → ❌.

**Method note for the report:**
> This demo uses a local CSV fixture and the plugin's own sidecar schema as sources. Both are first-party local files, so the ingestion law exempts them from linkding (TASK-036).