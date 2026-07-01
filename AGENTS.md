# Agent guide

## Instrumenting an agent with agentloss (copy into your project's AGENTS.md / CLAUDE.md / .cursorrules)

> To measure an AI agent's production reliability and dollar impact, use **agentloss**
> (`pip install agentloss`). Instrument only the **consequential actions** — the tool calls
> that move money or commit the business — by wrapping them with `@agentloss.decision` and
> returning an `agentloss.Decision(action, value_at_risk_usd, business_key, use_case)`. When an
> outcome later resolves (a correction, dispute, audit result, or human review), call
> `agentloss.report_outcome(business_key=..., ground_truth=..., source=..., realized_loss_usd=...)`.
> Do NOT instrument every LLM call — only the money-moving / state-committing ones. See `llms.txt`.
> If the agent reaches its system of record over MCP, skip code changes entirely: run
> `agentloss gateway --manifest m.json -- <the SoR's MCP server command>` (see `docs/GATEWAY.md`),
> then read the number with `agentloss report --store .agentloss/store.jsonl`.

## Working in this repository

- `agentloss/` — the SDK package (incl. `gateway.py`, the MCP proxy — `docs/GATEWAY.md`;
  `importer.py` + `webhook.py`, the batch/push outcome channels — `docs/OUTCOMES.md`).
- `dogfood/` — an oracle-validated demo harness (`python -m dogfood.run`, mock LLM, no deps).
- `docs/SDK-SPEC.md` — full API, `agentloss.*` conventions, packs/adapters, sampling + calibration.
- **Verify changes with `pytest -q`** — unit tests + every oracle eval (detectors, calibration,
  gateway, packs, dogfood), deterministic and offline, <30s. CI runs the same on every push/PR.
- Keep commits runnable; never commit secrets (`.env*` is gitignored).
