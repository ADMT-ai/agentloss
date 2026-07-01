"""Outcome detectors — the system-of-record side of agentloss.

A detector goes INTO a system of record and turns its reversals into resolved **Outcomes**:
`{business_key, ground_truth, realized_loss}`. This is one half of the loop; the other is decision
capture (`agentloss.decision` / `packs.capture`). They are deliberately separate and join on
`business_key` — a decision traced in one system, its outcome detected in another.

**Hardening a detector = handling what a real SoR throws at you**, not the happy path:

- **won vs lost** — a reversal that was *contested and won* is NOT a loss; only a final adverse
  reversal is.
- **partial** — the reversal amount can be less than the original exposure.
- **currency** — amounts may be in minor units (cents) or major units (zero-decimal currencies).
- **attribution** — a reversal can be an *agent error* (duplicate, fraud) or *normal business* (a
  legitimate return); only the former is a wrong decision.
- **pending / non-final** — records that haven't resolved yet have no outcome to report.
- **dedup** — one decision can accrue several reversal records; collapse to one outcome.

Every detector ships with an **eval** (known SoR records → expected Outcomes) so "hardened" is
measured, not asserted. See `examples/stripe_detector_eval.py`.

Ladder (increasing complexity): Stripe chargebacks (here) → ERP AP credit-memos → support/refund
tickets (reasoning-required).
"""
from . import erp, stripe  # noqa: F401

__all__ = ["stripe", "erp"]
