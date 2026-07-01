# Getting ground truth in — the outcome channels

agentloss is a join: decisions captured where the agent acts, outcomes detected where the
world rules, matched on `business_key`. The decision side has three capture paths (SDK,
OTel spans, the [MCP gateway](GATEWAY.md)). This page is the other half: **every way a
resolved outcome can reach the store**, so ground truth flows in whatever shape the business
already has it.

All channels share one contract — the same status semantics everywhere:

- a status in `error_statuses` → the decision was wrong; `ground_truth="reject"`, dollar loss
  attached (gold fidelity);
- a status in `correct_statuses` → the decision was right; ground truth = the decision's own
  action, loss 0;
- anything else → **non-final**: skipped now, *and excluded from any census* (an open dispute
  is unknown, not correct);
- `census` → decisions that appear in no reversal at all are marked correct, so the error
  rate's denominator is honest. Enable it only when the channel is the complete catch of
  errors.

## The channels

| channel | shape | when |
|---|---|---|
| **pull** — `agentloss_sync_outcomes` (gateway) / `detectors.*` (SDK) | call the SoR's reversal read (disputes, credit-memos), map rows | the SoR has an API/MCP server you can query |
| **push** — `agentloss listen` | a webhook endpoint; the SoR POSTs events as they resolve | the rail can push (Stripe webhooks, ERP event subscriptions) — the number stays live |
| **batch** — `agentloss import` | map a CSV export's columns | the reversals live in the warehouse or a finance export; no API at all |
| **code** — `report_outcome` / `record_outcomes` | one line per outcome | you already hold the rows in a job/notebook |
| **generated** — `sample_and_verify` + `calibrate` | active sampling + a verification agent, bias-corrected | no external labels wired yet; day-one numbers |

Each shipped channel is proven by an oracle eval in CI: `examples/import_eval.py`,
`examples/webhook_eval.py`, `examples/gateway_eval.py`, and the detector evals
(docs/DETECTORS.md).

## push — `agentloss listen`

```bash
agentloss listen --map events.json --store .agentloss/store.jsonl --port 8787 --secret $S
```

`events.json` is the manifest idea applied to pushed events — dotted paths rooted at `event`
(the POSTed JSON body):

```json
{"type": "event.type",
 "events": {"charge.dispute.closed": {
     "business_key": "event.data.object.payment_intent",
     "status": "event.data.object.status",
     "loss": "event.data.object.amount", "amount_divisor": 100,
     "error_statuses": ["lost"], "correct_statuses": ["won"],
     "source": "chargeback"}}}
```

Responses are always JSON; skips (unknown type, non-final status) return 200 so the
provider's retry machinery settles — only auth (401) and malformed bodies (400) refuse.
`--secret` gates on `X-Agentloss-Secret`; provider signature schemes (Stripe-Signature etc.)
are provider-specific, so verify those upstream or in front of the listener.

## batch — `agentloss import`

```bash
agentloss import --csv disputes.csv --store .agentloss/store.jsonl \
    --map "business_key=invoice_no,status=resolution,loss=amount" \
    --error-statuses lost --correct-statuses won --source chargeback --census
```

- Omit `--map` → it drafts one from the file's own header + observed statuses (the
  `gateway init` move, for a file).
- `--all-errors` → a pure-reversals export (no status column); every row is an error.
- Money parsing strips thousands separators (`"$1,400.00"`) but **refuses a decimal comma**
  (`"90,5"`) rather than silently misreading it 10×.
- Duplicate keys: the last row wins (an appeal overturning an earlier ruling).
- Warehouse tables (Snowflake/BigQuery/Postgres): export the query to CSV and import — the
  join happens here, so no warehouse credentials ever touch agentloss.

## Choosing

Prefer **push** when the rail offers it (the number stays current by itself), **pull** when
you control the schedule, **batch** when finance owns the data, **code** when it's already in
hand, **generated** only for the gap ground truth hasn't covered yet. They compose: e.g. the
gateway captures decisions, webhooks push disputes as they close, and a quarterly recovery
audit arrives as a CSV — all three write the same rows into the same store.
