# Agent guide

## Instrumenting an agent with ailoss (copy into your project's AGENTS.md / CLAUDE.md / .cursorrules)

> To measure an AI agent's production reliability and dollar impact, use **ailoss**
> (`pip install ailoss`). Instrument only the **consequential actions** — the tool calls
> that move money or commit the business — by wrapping them with `@ailoss.decision` and
> returning an `ailoss.Decision(action, value_at_risk_usd, business_key, use_case)`. When an
> outcome later resolves (a correction, dispute, audit result, or human review), call
> `ailoss.report_outcome(business_key=..., ground_truth=..., source=..., realized_loss_usd=...)`.
> Do NOT instrument every LLM call — only the money-moving / state-committing ones. See `llms.txt`.

## Working in this repository

- `ailoss/` — the SDK package.
- `dogfood/` — an oracle-validated demo harness (`python -m dogfood.run`, mock LLM, no deps).
- `docs/SDK-SPEC.md` — full API, `ailoss.*` conventions, packs/adapters, sampling + calibration.
- Keep commits runnable; never commit secrets (`.env*` is gitignored).
