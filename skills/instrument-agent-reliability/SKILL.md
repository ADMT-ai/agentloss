---
name: instrument-agent-reliability
description: Instrument an AI agent with agentloss to measure the real-world error rate and dollar cost of its decisions. Use when the user wants to know how much an agent's mistakes cost, quantify the financial impact of AI agent errors, measure how often an agent is wrong in production, compare an agent's decisions to actual outcomes / ground truth, decide whether it's safe to give an agent more autonomy, run production/online evals on real outcomes, prove an agent is reliable/auditable/insurable, onboard a system of record for outcome measurement, or measure an agent when there is NO explicit outcome data (infer outcomes, estimate losses). Keywords: cost of agent errors, agent error rate, dollar loss, production evals, ground truth outcomes, agent reliability, autonomy, LLM agent monitoring, MCP gateway, system of record, outcome inference, loss estimation.
---

# Instrument agent reliability & cost (agentloss)

Wire `agentloss` into an agent that takes consequential actions so its production error rate and
**dollar impact** become measurable.

## Steps

1. **Find the consequential action(s).** The tool calls that move money or commit the business
   (send payment, approve, place order, write to a system of record). Instrument only these,
   not every LLM call.

2. **Install:** `pip install agentloss`.

3. **Wrap the action** with `@agentloss.decision`, returning a `Decision`:
   ```python
   from agentloss import decision, Decision

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

4. **Report outcomes** when truth resolves — from a downstream correction, dispute, chargeback,
   audit, or the human-review queue. If you ALREADY HAVE the ground truth (the common case),
   this is the default: each outcome counts toward the number with no extra flags.
   ```python
   from agentloss import report_outcome, record_outcomes

   # one outcome
   report_outcome(business_key=<id>, ground_truth=<correct action/value>,
                  source="recovery_audit",   # recovery_audit|dispute|chargeback|refund|human_queue|verification_agent
                  realized_loss_usd=<loss or 0.0>)

   # or a whole disputes/chargebacks-table join, in one line
   record_outcomes([
       {"business_key": <id>, "ground_truth": "reject", "source": "chargeback",
        "realized_loss_usd": 80.0},
       {"business_key": <id2>, "ground_truth": "approve", "source": "dispute"},  # a CORRECT one
   ])
   ```
   Report the outcomes that AGREED with the agent too, not only the disputes — the rate's
   denominator is reported approvals, so reporting only errors makes it read ~100%.

5. **Confirm the wiring:** call `agentloss.doctor()` (in-process) or run `agentloss doctor
   --json`. It catches the silent failures in plain language — outcomes reported but none
   counted (0% rate), only-errors reported (~100% rate), a loss source that will not be summed.

6. **What you get:** error rate by segment (with CIs), **realized + expected dollar loss**, and
   incremental risk vs. baseline. Raw data stays local; only derived metrics leave.

## Notes
- **MCP gateway** (skip code changes entirely): if the agent reaches its system of record over
  MCP (a Stripe/ERP MCP server), replace steps 1–5 with the three-command loop —
  `agentloss gateway init --out m.json -- <server command>` (onboard: drafts the manifest from
  the server itself — money-movers, outcome reads, pagination, cross-tool joins, revision
  dedupe, and a reviewable `business_context` block; resolve any `_todo` markers it leaves),
  `agentloss gateway --manifest m.json -- <server command>` (execute), then
  `agentloss doctor --json --store .agentloss/store.jsonl` (verify) and
  `agentloss report --store <path>` (deliver). The gateway records decisions, syncs outcomes,
  and injects `agentloss_report`/`agentloss_doctor` into the agent's own tool list. Works for
  any agent runtime (not only Python). Hosted servers: `--url https://... --header
  "Authorization: ..."`. Ready-made manifests in `manifests/`; see `docs/GATEWAY.md`.
- **No outcome data to look up?** If the SoR writes resolutions as free text (case notes,
  tickets) or the status vocabulary is unknown, `init` drafts it automatically: `"mode":
  "infer"` reads the rows and **infers the outcome + estimates the loss** (explicit column →
  amount next to the resolution language → the decision's value-at-risk); an unknown status
  enum is **learned** from the rows' own text (marked `"fidelity": "silver"` until reviewed);
  prose beyond the vocabulary gets `"reasoner": "llm"` + `AGENTLOSS_REASONER=path.py:fn`.
  All inferred verdicts are silver — estimated dollars flow through expected loss, never
  realized — and calibrate against a small gold budget via `agentloss.calibrate`.
- **Packs** (skip hand-instrumentation): if the action goes through a known distribution system
  (a payment SDK, an ERP client, an agent tool), apply a pack instead of steps 3–4.
  `agentloss.packs.capture(fn, amount_of=..., key_of=...)` wraps the money-mover so every call
  auto-records a decision, and `outcomes_from_reversals(reversed_keys, amount_by_key,
  source="chargeback")` turns disputes/chargebacks/refunds into gold ground truth (a census, so
  the rate is right too). See `examples/payment_pack.py`.
- `sampled` / `pi` are load-bearing but you rarely set them: they default to a full census, so
  ground truth you already have counts by default. Pass `sampled=False` only for a biased
  partial catch (an audit that surfaces errors but never confirms correct decisions).
- Ground truth you cannot report directly is produced by `sample_and_verify(verify_fn)` — active
  sampling + a verification agent (see `docs/SDK-SPEC.md`) — you are not blocked on having
  labels, and it is real outcomes, not an offline dataset.
- Keep it OpenTelemetry-aligned; do not build a bespoke telemetry format.
