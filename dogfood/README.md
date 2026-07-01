# AgentProof dogfood harness

Dogfooding a **measurement instrument** requires a **known-truth oracle**: an
environment where *we* planted the errors, so we can check that AgentProof recovers
the true error rate and dollars. This harness is that environment.

```
seeder ─▶ ERP (sim) ─▶ AP agent (imperfect) ─▶ AgentProof (sample+verify+measure)
                                                        │
                                              eval scorecard vs oracle
```

- **`config.py`** — knobs: error-injection rates (calibrated to the real prior),
  agent limitations, sampling, outcome simulation.
- **`seeder.py`** — generates vendors/POs/receipts/invoices and **injects known errors**
  (duplicates, overpayments, qty mismatches, bank-change fraud, false-block traps,
  ambiguous cases) → returns the ERP + an `oracle` of the true correct action per invoice.
- **`erp.py`** — the system of record with a **REST-shaped surface**: a *limited* surface
  the agent uses (exact-match dup within 90d, PO price) and a *thorough* surface the
  verifier uses (fuzzy dup over all history, contract price, vendor risk).
- **`agent.py`** — the AP agent under test. Deliberately imperfect so it makes realistic
  residual errors. Instrumented with `@agentproof.decision`.
- **`agentproof/`** — the SDK being dogfooded: `core` (decision capture + outcomes),
  `sampler` (stratified + importance sampling with Horvitz–Thompson reweighting),
  `verifier` (re-adjudicates with the thorough ERP surface), `metrics` (Wilson CI,
  false-approve rate, expected/realized loss).
- **`outcomes.py`** — simulates the human-review queue (gold labels for holds/rejects)
  and a delayed recovery audit (gold + realized dollars for a caught subset of escapes).
- **`eval.py`** — the **scorecard**: does the measured false-approve rate CI cover the
  oracle truth? verifier precision/recall? dollars within tolerance?
- **`llm.py`** — `MockLLM` (deterministic, offline) and `ClaudeLLM` (real). Same evidence
  in, so real Claude drops in without changing the loop.

## Run

```bash
# from repo root
python -m dogfood.run                 # mock LLM, deterministic, no deps
AGENTPROOF_LLM=claude ANTHROPIC_API_KEY=sk-... python -m dogfood.run   # real Claude
```

## Realism ladder

1. **now** — in-process ERP sim (REST-shaped), mock LLM. Prove the oracle-validated loop.
2. **next** — wrap `erp.py` in FastAPI so the agent talks real HTTP; flip to Claude.
3. **then** — swap the adapter to **ERPNext** in Docker (real ERP), pack unchanged.
4. **real** — a design partner's NetSuite adapter. Pack unchanged throughout.

The `ap` pack never moves; only the adapter changes. That swap is the whole point.
