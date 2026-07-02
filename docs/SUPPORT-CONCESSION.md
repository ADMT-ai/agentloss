# The support-concession audit record — insuring the money a support agent gives away

**The vertical.** LLM support agents resolve tickets autonomously, and the autonomy ceiling
is a money question: may the agent grant refunds, credits, replacements, and goodwill
gestures without a human? An insurer can lift that ceiling — but only against an **audit
record**: a verifiable history of every concession decision joined to what turned out to be
true, with honest statistics an underwriter can price. agentloss does not build the support
agent; it is the record the agent writes to (SDK, or the MCP gateway in front of the
ticketing/refund SoR — zero agent changes) so that its decisions **qualify**.

Why this vertical fits the machinery: support outcomes live in prose (ticket threads, QA
notes), losses are often implicit, and there is no census — QA reviews a few percent of
tickets. Soft outcomes (docs/GATEWAY.md), monetary-unit sampling, and two-phase calibration
(docs/SDK-SPEC.md) are exactly what turns that into an honest number.

## The funnel: assess, then bind

**1. Assess — prove you're coverable, before installing anything.** Read-only, day one:
`agentloss backfill --csv history.csv --store s.jsonl` (the mapping drafts itself from
the export's header) builds the record retroactively, and `agentloss underwrite --store
s.jsonl --agent <bot> --baseline <team> --html report.html` renders it into the
underwriting report + qualification, segmented agent-vs-human — including the
self-contained HTML one-pager you hand to an underwriter or a board. This is the
assessment an insurer prices from and a buyer uses to prove the agent qualifies.

**2. Bind — coverage goes in force when the middleware does.** A policy is kept in force
by a LIVE record, not a snapshot: binding requires the agentloss gateway installed in
front of the SoR's MCP server, capturing every decision as it happens and syncing
outcomes continuously (the telematics model — no box, no coverage). The report states
which grade of record it sees: `binding.capture` is `historical` (assessment-grade),
`mixed`, or `live`, and `binding.bound_ready` is true only for a qualifying record with
live middleware capture. Gateway-captured decisions are distinguishable by construction
(`Decision.model == "gateway"`), so bind status is read from the record, never
self-reported.

## The covered decision

One record per **concession decision** — the consequential action, not the conversation:

| Decision field | Support-concession meaning | Required |
|---|---|---|
| `action` | `grant` / `partial` / `deny` (the concession verdict) | yes |
| `value_at_risk_usd` | The concession amount granted (or requested, for `deny`) | yes |
| `business_key` | The refund/credit transaction id — or `ticket:<id>` when no money moved | yes |
| `use_case` | `support_concession` (segment further if useful: `support_concession/refund`) | yes |
| `in_envelope` | Was the decision inside the concession policy (amount cap, eligible order states, customer standing)? Out-of-envelope decisions are excluded from coverage | yes |
| `context` | Evidence the verifier/QA reviews: ticket summary, order id, policy basis | recommended |
| `model` | Agent/model version that decided (provenance) | recommended |

The **covered error** (v1) is a wrongful grant: a concession that policy, the facts, or
fraud/abuse review says should not have been made — including over-refunds (the excess is
the loss). Wrongful denials (churn cost) are real but not underwritable v1; record them,
don't insure them.

## Admissible evidence (the outcome side)

Same status contract as everywhere in agentloss; what changes per vertical is which sources
count as claims evidence:

- **Gold** — `human_queue` (the QA review verdict — see below), `recovery_audit`
  (accounting reconciliation of refunds vs orders), `chargeback`/`refund` reversals
  (e.g. a chargeback landing on an order the agent had already refunded — double loss).
- **Silver** — `inferred` (the ticket thread read by the marker vocabulary or a reasoning
  agent: `mode: "infer"` / `"reasoner": "llm"` at the gateway) and `verification_agent`.
  Silver dollars flow through **expected** loss, never realized, and must be calibrated.

**The QA process is the claims rail.** Support orgs already sample tickets for QA review.
Recorded properly — each reviewed decision reported via `report_outcome(...,
source="human_queue", sampled=True, pi=<inclusion probability>)` — that existing process
becomes the statistical anchor: monetary-unit sampling weights big concessions in,
Horvitz-Thompson reweighting keeps the estimates unbiased, and the two-phase calibration
(`agentloss.calibrate`) corrects the reasoner's silver verdicts against the QA gold budget.
No census is required for a qualifying record — a *known-probability sample* is enough.

## Qualification — does this record qualify?

A qualifying support-concession record satisfies, machine-checkably (`agentloss doctor`
plus the profile checks in the underwriting report):

1. Decisions carry exposure, a unique business key, and an envelope verdict.
2. Outcome evidence exists on a known-probability sample (or census) of grants — not only
   the errors (denominator honesty; the doctor's existing checks).
3. Every dollar is provenance-typed: realized loss only from gold sources; silver dollars
   estimated, confidence-carrying, and calibrated against a gold budget.
4. Out-of-envelope decisions are recorded (they prove the envelope is real) but excluded
   from covered exposure.

## The underwriting report

`agentloss underwrite --store s.jsonl --json` renders the record into what a pricing
actuary needs — all derived from the store, nothing self-reported:

- **exposure**: concessions written (count, total, max single, in-envelope fraction);
- **frequency**: wrongful-grant rate with confidence interval (sampled + HT-reweighted);
- **severity**: mean and max loss per wrongful grant;
- **loss**: realized (gold) and expected (calibrated silver) dollars, and
  loss-to-exposure — the raw loss ratio a premium is priced against;
- **evidence**: outcome coverage, gold/silver mix, source breakdown, sampling design
  (census vs QA-sample with pi);
- **accumulation**: wrongful decisions chained into LOSS EVENTS (a bad update or viral
  exploit is one incident, not N independent errors), worst event, max rolling 24h/7d
  aggregates — the correlated tail a per-event sublimit prices;
- **stability**: the monthly rate/loss series and a recent-vs-baseline drift verdict —
  whether the priced assumptions still hold (a drifting record warns in qualification);
- **qualification**: the pass/warn/fail findings from the checks above.

## Backfill — day-one actuarial history, and the human baseline

A newly deployed agent has no loss history; the system of record has years of it, in
prose. `agentloss backfill` builds the record retroactively from a historical export:

    agentloss backfill --csv history.csv --store s.jsonl \
        --map "business_key=ticket_id,amount=refund_amount,decider=agent_name,evidence=resolution_notes"
    agentloss underwrite --store s.jsonl --agent support_agent --baseline human_team

Each historical concession becomes a Decision (the `decider` column lands in
`Decision.model`, so human history and agent history are SEGMENTS of one record) and its
outcome is adjudicated from the row: a mapped `status` column with vocabularies is gold
(the export already ruled); otherwise the `evidence` prose is judged — the marker
vocabulary, or the `AGENTLOSS_REASONER` agent — into silver outcomes with estimated
losses. The report then carries per-decider segments and the **baseline comparison**:
the agent's wrongful-grant rate and loss-to-exposure against the human team it replaced
(`cheaper_to_insure` is the sentence that raises an autonomy ceiling). Silver-only
backfills are flagged uncalibrated — feed a QA gold budget in and calibrate before
anyone prices off them. The record also exports directly as an insurer's tabular data
submission — decisions joined to ground truth with the loss per row:
`agentloss export --store s.jsonl --out submission.csv [--template insurer.json]`
(a template file remaps the columns onto a specific application form's headers).

## Proven by

Oracle evals, in CI: `examples/underwriting_eval.py` — a seeded concession history
(QA sample at known pi, reconciliation gold, inferred silver) must yield the exact seeded
frequency, severity, and loss ratio, and a record missing the qualification bar must say
so; `examples/backfill_eval.py` — a prose-only historical export must backfill into the
exact seeded actuarial truth, segmented agent vs human, with the agent correctly priced
cheaper than the baseline.
