# agentloss connectors

Ride the tracing you already run. agentloss reads the decision spans your tracer emits and
adds the loss/outcome layer on top — then writes the result back as annotations in the tool
you already use.

## Phoenix (`agentloss.connectors.phoenix`)

**Install:** `pip install "agentloss[phoenix]"`

**1. Run Phoenix and trace your agent** with OpenInference/OTel (as you already do). On the
**consequential** span (the tool call that moves money / commits the business), set:

```python
span.set_attribute("agentloss.action", "approve")          # or hold | reject
span.set_attribute("agentloss.business_key", invoice_no)    # stable id outcomes join on
span.set_attribute("agentloss.value_at_risk_usd", total)    # exposure of this action
```

**2. Read → verify → write back → report:**

```python
import agentloss
from agentloss.connectors import phoenix as ph

n, key_to_span = ph.read_decisions(project="my-agent")   # ingest agentloss.* spans
agentloss.sample_and_verify(my_verify_fn)                # Tier A — or push report_outcome(...)
ph.write_back(key_to_span)                               # per-decision loss/verdict -> Phoenix UI
agentloss.print_report()                                 # error rate by segment + dollar loss
```

`read_decisions` uses `phoenix.client.Client().spans.get_spans_dataframe(...)`; `write_back`
uses `...spans.log_span_annotations_dataframe(...)`. The pure DataFrame↔agentloss mapping is
unit-tested offline in `examples/phoenix_offline_test.py`.

## Try it end-to-end on a local Phoenix (no agent needed)

```bash
pip install arize-phoenix "agentloss[phoenix]"    # add [claude] for the default LLM verifier
phoenix serve                                      # http://localhost:6006
python examples/phoenix_emit_spans.py              # seed Phoenix with decision spans
python examples/phoenix_live.py                    # read -> verify -> write back -> report
```

Open http://localhost:6006 and look for `agentloss` annotations (loss/verdict) on the decision
spans, next to the printed error-rate + dollar-loss report. (No `ANTHROPIC_API_KEY` → a built-in
heuristic verifier runs so it works offline; set the key to use the default Claude verifier.)

## Langfuse (`agentloss.connectors.langfuse`) — built to docs, not yet live-verified

Put `agentloss.*` fields in your observation metadata. `read_decisions()` ingests them;
`write_back(key_to_ref)` posts loss + error as Langfuse **scores** (`create_score`).
`pip install "agentloss[langfuse]"`.

## Braintrust (`agentloss.connectors.braintrust`) — built to docs, not yet live-verified

`write_back(key_to_span, project=...)` posts loss/verdict as Braintrust **feedback**
(`log_feedback`). Supply the `business_key -> span_id` map from your logging (Braintrust is
log/BTQL-oriented, so reads are adapted per project). `pip install "agentloss[braintrust]"`.

> **Verification status:** Phoenix is verified end-to-end against a live server. Langfuse and
> Braintrust are built to their docs and need the same live-verification pass — expect small
> API fixes on first real run (that's exactly what Phoenix needed). The pure mapping logic for
> all three is offline-tested. Next: raw OTLP ingestion.
