# agentloss

[![ci](https://github.com/ADMT-ai/agentloss/actions/workflows/ci.yml/badge.svg)](https://github.com/ADMT-ai/agentloss/actions/workflows/ci.yml)

**Your eval tool tells you your AI agent's hallucination rate. `agentloss` tells you what it
costs.** An OpenTelemetry-native SDK that measures the real-world **error rate and dollar
loss** of an AI agent's decisions — by capturing its consequential actions in-process and
joining them to ground truth (real resolved outcomes, not an offline labeled set).

Every eval/observability tool scores *quality proxies* — LLM-judge, hallucination rate, task
completion. `agentloss` answers the question the market keeps asking and no tool measures:
*what are my agent's mistakes costing, and is it safe to trust with more autonomy?*

> Part of **ADMT** (Automated Decision-Making Technology) — [admt.ai](https://admt.ai).

## Assess, then bind — the path to an insured agent

`agentloss` is the audit record an agentic system writes to in order to **qualify for
coverage** ([docs/SUPPORT-CONCESSION.md](docs/SUPPORT-CONCESSION.md)):

1. **Assess** (read-only, day one — nothing installed): build the record retroactively
   from the system of record's own history and render the underwriting report —
   `agentloss backfill --csv history.csv --map ... --store s.jsonl`, then
   `agentloss underwrite --store s.jsonl --agent <bot> --baseline <human team>` —
   exposure, wrongful-decision frequency, severity, loss-to-exposure, and the
   agent-vs-human comparison. This is how you *prove* the agent is coverable.
2. **Bind**: coverage goes in force when the **middleware** does — the agentloss gateway
   installed in front of the SoR's MCP server, capturing every live decision and syncing
   outcomes continuously. The report reads bind status from the record itself
   (`binding.capture`: historical → assessment-grade; live → bound-ready). No box, no
   coverage.

## Install

```bash
pip install agentloss
```

## Quickstart

Instrument only the **consequential action** — the tool call that moves money or commits the
business — not every LLM call.

```python
from agentloss import decision, report_outcome, Decision

@decision                                     # bare decorator; the returned Decision is recorded
def approve_payment(invoice):
    action = run_matching(invoice)            # "approve" | "hold" | "reject"
    return Decision(action=action, value_at_risk_usd=invoice.total,
                    business_key=invoice.number, use_case="ap_3way_match")

# when the outcome resolves (correction, dispute, chargeback, audit, human review):
report_outcome(business_key="INV-1", ground_truth="duplicate-should-block",
               source="recovery_audit", realized_loss_usd=14200)
```

**You already have the ground truth?** (the common case — a disputes / chargebacks table).
That's the default: each reported outcome is a census observation that counts toward the
number, no flags needed. Join the whole table in one line:

```python
from agentloss import record_outcomes

record_outcomes([
    {"business_key": "INV-1", "ground_truth": "reject", "source": "chargeback",
     "realized_loss_usd": 80.0},
    {"business_key": "INV-2", "ground_truth": "approve", "source": "dispute"},  # a CORRECT one
])
```

Report the outcomes that **agreed** with the agent too, not only the disputes — the rate's
denominator is *reported approvals*, so reporting only errors makes it read ~100%. `source`
is one of `recovery_audit | dispute | chargeback | refund | human_queue | verification_agent |
inferred` (the last two are silver: their dollars flow through *expected* loss, never realized).

It computes the error rate by segment (with confidence intervals), **realized + expected dollar
loss**, and the agent's incremental risk vs. a baseline. Raw prompts/records stay in your
boundary; only derived metrics leave.

**Confirm the wiring** — `agentloss.doctor()` inspects the store and catches the silent
failures in plain language (outcomes reported but none counted, only-errors reported, a loss
source that won't be summed). Or from a shell: `agentloss doctor --json`.

## No code changes at all? The MCP gateway

If your agent already reaches its system of record over **MCP** (a Stripe MCP server, an ERP
MCP server), don't instrument code — put the agentloss gateway in front of that server. One
config change, any agent runtime (not only Python):

```bash
agentloss gateway --manifest stripe.manifest.json -- stripe-mcp --api-key ...          # local
agentloss gateway --manifest stripe.manifest.json \
    --url https://mcp.stripe.com --header "Authorization: Bearer $KEY"                 # hosted
```

A JSON **manifest** (a pack, as data) declares which tools are consequential and where the
reversal (dispute / credit-memo) lives; every consequential `tools/call` records a decision, and
`agentloss_sync_outcomes` turns the rail's reversals into gold ground truth. The gateway also
injects `agentloss_report` / `agentloss_doctor` into the server's tool list, so the agent reads
its own error rate and dollar loss **through the same connection it acts through**. Readout
out-of-process: `agentloss report --store .agentloss/store.jsonl`.

Don't write the manifest — **draft it from the server itself**:

```bash
agentloss gateway init --out my.manifest.json -- <your server command>
```

`init` classifies the money-movers from the server's own `tools/list`, probes the reversal
reads to derive the row paths from real data, emits a `business_context` block (the domain it
understood, each outcome channel's mode) so the onboarding judgment is reviewable, and marks
anything it can't establish with an explicit `_todo`. Ready-made manifests for known servers
live in [`manifests/`](manifests/).

**No outcome data to look up?** Some SoRs write the resolution as free text and no dollar
figure. Declare the outcome tool with `"mode": "infer"` (`init` drafts this itself when it
probes text-only rows) and the gateway **infers the outcome and estimates the loss** —
parsed from the evidence, else bounded by the decision's value-at-risk — recorded as silver
so estimated dollars flow through *expected* loss, never passed off as realized.

See [`docs/GATEWAY.md`](docs/GATEWAY.md); proven end-to-end by
[`examples/gateway_eval.py`](examples/gateway_eval.py),
[`examples/gateway_init_eval.py`](examples/gateway_init_eval.py), and — up eight rungs of
SoR mess with zero hand-written config — the synthetic SoR ladder
([`examples/sor_ladder_eval.py`](examples/sor_ladder_eval.py)) (oracle evals, in CI).

## Ground truth, in whatever shape you have it

Outcomes reach the store through five channels — pick by where the reversals live
(see [`docs/OUTCOMES.md`](docs/OUTCOMES.md)):

```bash
# batch: the finance/warehouse export (no API needed; omit --map to draft one from the header)
agentloss import --csv disputes.csv --store .agentloss/store.jsonl \
    --map "business_key=invoice_no,status=resolution,loss=amount" \
    --error-statuses lost --correct-statuses won --source chargeback --census

# push: the rail's webhooks, mapped in real time
agentloss listen --map events.json --store .agentloss/store.jsonl --port 8787
```

Plus **pull** (the gateway's `agentloss_sync_outcomes` / SDK detectors), **code**
(`record_outcomes`), and **generated** (`sample_and_verify` + calibration) — all writing the
same rows, all sharing one status contract (non-final rows stay out of the census). Each
channel is proven by an oracle eval in CI ([`import_eval`](examples/import_eval.py),
[`webhook_eval`](examples/webhook_eval.py)).

## Works with your existing traces (Phoenix / Langfuse / Braintrust / OTel)

Already tracing your agent with OpenInference/OpenTelemetry? Don't re-instrument. Add a few
`agentloss.*` attributes to the consequential span, point agentloss at your spans, and it adds
the loss/outcome layer on top of what your tracer already emits:

```python
from agentloss import ingest_spans, sample_and_verify, print_report

ingest_spans(your_spans)       # OTel/OpenInference spans carrying agentloss.* attributes
sample_and_verify(verify_fn)   # Tier A: get a number with no external labels wired
print_report()                 # error rate by segment + dollar loss
```

See [`examples/from_spans.py`](examples/from_spans.py).

## How it works

- **Instrument consequential actions, not the whole agent.** The costly events are the handful
  of tool calls that move money or commit state.
- **Ground truth arrives late, from outside the agent** — a correction, dispute, audit result,
  or human review. Capture it via `report_outcome`, the human-review queue, and active sampling
  + a verification agent. This is *real resolved outcomes*, not an offline dataset.
- **Honest statistics.** Monetary-unit sampling with a target verifier budget; two-phase
  calibration corrects a fallible verifier's bias back to truth (with confidence intervals).

See [`docs/SDK-SPEC.md`](docs/SDK-SPEC.md) for the full API, `agentloss.*` semantic conventions,
and the pack/adapter model.

## Try the demo

An oracle-validated harness that seeds an accounts-payable environment with *known* errors and
checks that `agentloss` recovers the true error rate and dollar loss:

```bash
python -m dogfood.run                                  # deterministic mock, no deps
AGENTLOSS_VERIFIER_LLM=claude ANTHROPIC_API_KEY=... python -m dogfood.run
```

## For AI coding agents

`agentloss` is built to be discovered and wired by coding agents:
[`llms.txt`](llms.txt) (also served at [agentloss.com/llms.txt](https://agentloss.com/llms.txt) —
starts with a which-path decision tree), the
[`instrument-agent-reliability`](skills/instrument-agent-reliability/SKILL.md) skill, the
[`AGENTS.md`](AGENTS.md) rule, and an [MCP server](mcp/agentloss_mcp.py)
(`how_to_instrument`, `how_to_gateway`, `how_to_onboard_sor` — the full onboarding runbook,
including the no-outcome-data path — `explain_attribute`, `explain_manifest_field`, and
`validate_integration`, which inspects a persisted `--store` file so an agent can *prove* its
wiring). The gateway loop itself is agent-shaped: `init` drafts the config from the server,
`doctor` says what's mis-wired in plain language, and the measurement tools ride the same MCP
connection the agent acts through. Every claim in the docs is backed by an oracle eval run in
CI: `pytest -q`.

## License

Apache-2.0.
