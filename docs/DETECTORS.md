# Outcome detectors — the system-of-record side

agentloss is two halves that join on `business_key`:

- **Decision tracer** (agent side) — `@agentloss.decision` / `packs.capture`: record the decision +
  its exposure where it happens, stamped with a durable `business_key`.
- **Outcome detector** (SoR side) — `agentloss.detectors.*`: go INTO a system of record and turn its
  reversals into resolved Outcomes `{business_key, ground_truth, realized_loss}`.
- **Join** — match outcomes back to decisions by `business_key`, across time and systems.

Keeping these separate is the point: the decision is traced in one system, the outcome detected in
another, and the join is explicit.

## The detector contract

A detector maps a system of record's reversal records → outcome rows, **hardened for what a real SoR
throws**, not the happy path: won vs lost (is it actually a loss?), partial amounts, currency (incl.
zero-decimal), attribution (agent error vs normal business), pending/non-final records, and dedup.
Every detector ships with an **eval** (known records → expected Outcomes) so "hardened" is measured.

## Ladder (increasing complexity — one at a time, each with an eval)

1. **Stripe chargebacks** — `detectors.stripe` — first-class Dispute objects. ✅ **11-case eval**
   (`examples/stripe_detector_eval.py`); `packs.stripe.outcomes_from_disputes` routes through it.
2. **ERP AP credit-memos** — semi-structured records. *(next)*
3. **Support / refund tickets** — the outcome is free-text, reasoning-required. *(later)*

## Stripe chargeback detector

```python
from agentloss.detectors.stripe import chargeback_outcomes, detect, record

rows = detect(stripe, attributable_reasons={"fraudulent", "duplicate"})   # live fetch -> hardened rows
record(rows, census=False)                                                # write into agentloss
```

Behavior (all covered by the eval):
- `lost` / `charge_refunded` → error (`ground_truth="reject"`), loss = dispute amount (partial-safe).
- `won` → correct (`ground_truth="approve"`), loss 0. *(the old code wrongly counted these as losses.)*
- pending / non-final → skipped, unless `include_pending=True`.
- zero-decimal currencies (JPY, KRW, …) are not divided by 100.
- `attributable_reasons` → only those reasons count as an agent error; other real reversals (a
  legitimate return) are recorded as correct.
- multiple dispute records per charge → deduped to the most final.
