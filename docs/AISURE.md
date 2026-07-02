# Munich Re aiSure (Agentic AI) — answering the questionnaire from the record

Munich Re's aiSure risk-assessment questionnaire for agentic AI asks an applicant to
describe the agent, its controls, and its ground-truth process — and to submit
**historical performance data: at least one year of records across all customers and
use cases**, in a fixed template. An agentloss record answers the substantive
questions directly, and `agentloss export` emits the data submission in their format.

## The data submission (questionnaire §6)

Template columns → record fields, one row per evidenced decision:

| aiSure template column | agentloss record |
|---|---|
| Timestamp | `Decision.ts` (historical time from the export on backfill; stamped live otherwise) |
| Customer ID | `Decision.customer` |
| Use Case ID | `Decision.use_case` |
| Agent Output / Action | `Decision.action` |
| Ground Truth / Expected Outcome | `Outcome.ground_truth` |
| Financial Loss (US$; expected loss) | realized dollars (gold) or the estimated figure (silver); `0.00` for correct decisions |

    agentloss backfill --csv history.csv --store s.jsonl      # the year of history, from the SoR itself
    agentloss export --format aisure --store s.jsonl --out submission.csv

The "at least 1 year of records" requirement is exactly what `backfill` produces from
the system of record's own historical export (docs/SUPPORT-CONCESSION.md#backfill) —
including the timestamps, carried from the export's own date column, and the customer
dimension. A submission built from silver (inferred) outcomes should be calibrated
against a QA gold budget first; the underwriting report says so when it isn't.

## The narrative questions, answered by the record

- **"Are audit logs kept for all agent actions?"** — Yes, structurally: the store is an
  append-only JSONL log of every consequential decision and every outcome, written by
  the gateway middleware without agent code changes (docs/GATEWAY.md).
- **"How is ground-truth determined during testing and in production?"** — The outcome
  channels (docs/OUTCOMES.md): pulled from the SoR's own reversal reads, pushed by
  webhooks, imported from finance exports, sampled + verified, or inferred from
  evidence — each provenance-typed gold/silver, with silver bias-corrected by two-phase
  calibration against a gold budget (docs/SDK-SPEC.md).
- **"Estimated annual volume of agent outputs or actions"** — `exposure.decisions` in
  the underwriting report, from the record rather than an estimate.
- **"Performance metrics tracked" / "real-time monitoring"** — error rate with CI,
  realized + expected dollar loss, loss-to-exposure, per-segment; `agentloss doctor`
  self-checks the wiring continuously; the gateway injects the readout into the agent's
  own tool list.
- **"Do you track model or agent behavior drift?"** — partially today: the envelope
  (`in_envelope`) records out-of-policy decisions and the report excludes them from
  covered exposure. Distribution-drift alerts against the priced envelope are roadmap.

The rest of the questionnaire (architecture, guardrails, deployment process) is about
the agent itself — the applicant answers those; the record corroborates them.

Proven by `examples/backfill_eval.py` (in CI): the zero-config backfill run also exports
the aiSure submission and asserts the template header, the row count, the carried
historical timestamps, and that the loss column totals the seeded truth.
