# ailoss

**Your eval tool tells you your AI agent's hallucination rate. `ailoss` tells you what it
costs.** An OpenTelemetry-native SDK that measures the real-world **error rate and dollar
loss** of an AI agent's decisions — by capturing its consequential actions in-process and
joining them to ground truth (real resolved outcomes, not an offline labeled set).

Every eval/observability tool scores *quality proxies* — LLM-judge, hallucination rate, task
completion. `ailoss` answers the question the market keeps asking and no tool measures:
*what are my agent's mistakes costing, and is it safe to trust with more autonomy?*

> Part of **ADMT** (Automated Decision-Making Technology) — [admt.ai](https://admt.ai).

## Install

```bash
pip install admt-ailoss     # distribution name; you still `import ailoss`
```

## Quickstart

Instrument only the **consequential action** — the tool call that moves money or commits the
business — not every LLM call.

```python
from ailoss import decision, report_outcome, Decision

@decision
def approve_payment(invoice):
    action = run_matching(invoice)            # "approve" | "hold" | "reject"
    return Decision(action=action, value_at_risk_usd=invoice.total,
                    business_key=invoice.number, use_case="ap_3way_match")

# when the outcome resolves (correction, dispute, audit, human review):
report_outcome(business_key="INV-1", ground_truth="duplicate-should-block",
               source="recovery_audit", realized_loss_usd=14200)
```

It computes the error rate by segment (with confidence intervals), **realized + expected dollar
loss**, and the agent's incremental risk vs. a baseline. Raw prompts/records stay in your
boundary; only derived metrics leave.

## How it works

- **Instrument consequential actions, not the whole agent.** The costly events are the handful
  of tool calls that move money or commit state.
- **Ground truth arrives late, from outside the agent** — a correction, dispute, audit result,
  or human review. Capture it via `report_outcome`, the human-review queue, and active sampling
  + a verification agent. This is *real resolved outcomes*, not an offline dataset.
- **Honest statistics.** Monetary-unit sampling with a target verifier budget; two-phase
  calibration corrects a fallible verifier's bias back to truth (with confidence intervals).

See [`docs/SDK-SPEC.md`](docs/SDK-SPEC.md) for the full API, `ailoss.*` semantic conventions,
and the pack/adapter model.

## Try the demo

An oracle-validated harness that seeds an accounts-payable environment with *known* errors and
checks that `ailoss` recovers the true error rate and dollar loss:

```bash
python -m dogfood.run                                  # deterministic mock, no deps
AILOSS_VERIFIER_LLM=claude ANTHROPIC_API_KEY=... python -m dogfood.run
```

## For AI coding agents

`ailoss` is built to be discovered and wired by coding agents:
[`llms.txt`](llms.txt), the [`instrument-agent-reliability`](skills/instrument-agent-reliability/SKILL.md)
skill, the [`AGENTS.md`](AGENTS.md) rule, and an [MCP server](mcp/ailoss_mcp.py)
(`how_to_instrument`, `explain_attribute`, `validate_integration`).

## License

Apache-2.0.
