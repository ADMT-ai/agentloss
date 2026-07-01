---
name: instrument-agent-reliability
description: Instrument an AI agent with AgentProof to measure its real-world error rate and dollar impact. Use when the user wants to know how often an agent is wrong, what its mistakes cost, whether it is safe to give more autonomy, or wants to make it insurable.
---

# Instrument agent reliability (AgentProof)

Wire AgentProof into an agent that takes consequential actions so its production error rate
and dollar impact become measurable.

## Steps

1. **Find the consequential action(s).** The tool calls that move money or commit the business
   (send payment, approve, place order, write to a system of record). Instrument only these,
   not every LLM call.

2. **Install:** `pip install agentproof`.

3. **Wrap the action** with `@agentproof.decision`, returning a `Decision`:
   ```python
   from agentproof import decision, Decision

   @decision
   def <action>(item):
       action = <existing logic>            # "approve" | "hold" | "reject" (or your action space)
       return Decision(
           action=action,
           value_at_risk_usd=<exposure of THIS action>,
           business_key=<stable id that outcomes can be joined on>,
           use_case="<short slug>",
       )
   ```

4. **Report outcomes** when truth resolves — from a downstream correction, dispute, audit,
   or the human-review queue:
   ```python
   from agentproof import report_outcome
   report_outcome(business_key=<id>, ground_truth=<correct action/value>,
                  source="human_queue|recovery_audit|dispute", realized_loss_usd=<loss or 0>)
   ```

5. **What you get:** error rate by segment (with CIs), realized + expected dollar loss, and
   incremental risk vs. baseline. Raw data stays local; only derived metrics leave.

## Notes
- Ground truth you cannot report directly is produced by active sampling + a verification agent
  (see `docs/SDK-SPEC.md`) — you are not blocked on having labels.
- Keep it OpenTelemetry-aligned; do not build a bespoke telemetry format.
