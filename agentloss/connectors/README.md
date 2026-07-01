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

Next connectors (same pattern): Langfuse (scores API), Braintrust (feedback API), raw OTLP.
