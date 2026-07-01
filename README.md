# AgentAudit

**Measure an AI agent's real-world error rate and dollar impact.** OpenTelemetry-native
instrumentation that captures an agent's *consequential* decisions in-process and joins them
to ground truth, so you can answer the question that gates every autonomous deployment:
*is this agent safe enough to trust with more autonomy, and what is it worth?*

Most observability tools score *quality* (LLM-judge, hallucination rate). AgentAudit closes the
loop to *outcomes and dollars*: did the action turn out right when the world resolved it, and
what did the misses cost?

## Install

```bash
pip install agentaudit
```

## Quickstart

Instrument only the **consequential action** — the tool call that moves money or commits the
business — not every LLM call.

```python
from agentaudit import decision, report_outcome, Decision

@decision
def approve_payment(invoice):
    action = run_matching(invoice)            # "approve" | "hold" | "reject"
    return Decision(action=action, value_at_risk_usd=invoice.total,
                    business_key=invoice.number, use_case="ap_3way_match")

# when the outcome resolves (correction, dispute, audit, human review):
report_outcome(business_key="INV-1", ground_truth="duplicate-should-block",
               source="recovery_audit", realized_loss_usd=14200)
```

It computes the error rate by segment (with confidence intervals), realized + expected dollar
loss, and the agent's incremental risk vs. a baseline. Raw prompts/records stay in your
boundary; only derived metrics leave.

## How it works

- **Instrument consequential actions, not the whole agent.** Insurable/measurable events are the
  handful of tool calls that move money or commit state.
- **Ground truth arrives late, from outside the agent.** Capture it via `report_outcome`, the
  human-review queue, and active sampling + a verification agent — you're never stuck at zero.
- **Honest statistics.** Monetary-unit sampling with a target verifier budget; two-phase
  calibration corrects a fallible verifier's bias back to truth (with confidence intervals).

See [`docs/SDK-SPEC.md`](docs/SDK-SPEC.md) for the full API, `ailoss.*` semantic conventions,
and the pack/adapter model.

## Try the demo

An oracle-validated harness that seeds an accounts-payable environment with *known* errors and
checks that AgentAudit recovers the true error rate and dollar loss:

```bash
python -m dogfood.run                                  # deterministic mock, no deps
AGENTAUDIT_VERIFIER_LLM=claude ANTHROPIC_API_KEY=... python -m dogfood.run
```

## For AI coding agents

AgentAudit is built to be discovered and wired by coding agents:
[`llms.txt`](llms.txt), the [`instrument-agent-reliability`](skills/instrument-agent-reliability/SKILL.md)
skill, the [`AGENTS.md`](AGENTS.md) rule, and an [MCP server](mcp/agentaudit_mcp.py)
(`how_to_instrument`, `explain_attribute`, `validate_integration`).

## License

Apache-2.0.
