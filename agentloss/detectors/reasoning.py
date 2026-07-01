"""Reasoning-based outcome detector (Stage 3 — the hardest SoR: the outcome is FREE-TEXT).

When the system of record has no `was_wrong` field — support tickets, resolution notes, email
threads — the outcome must be **read and reasoned**, not looked up. This detector injects two things
and stays pure with respect to them, so the plumbing is deterministically eval'd (mock reasoner) and
the judgment is measured live (an LLM):

  - `retrieve(context, records)` — fuzzy-join the decision to its candidate free-text records.
  - `reasoner(context, candidates)` — judge `{should_have_been, estimated_loss, confidence?}`.

It also resolves the Stage-2 caveat: a reasoner can read *how much* was actually wrong (the excess vs
the whole invoice), where a structured full-invoice reversal could only report the clawback amount.

The reasoner is fallible, so its verdicts are silver — feed them through agentloss's sampling +
two-phase verifier-bias calibration for an unbiased rate/loss (see `sample_and_verify`). The live
proof of this path is the messy-ERPNext run (`dogfood/erpnext/run_messy.py`): real Claude recovers
the true error rate within its CI.
"""


def reasoned_outcomes(items, reasoner, *, retrieve=None, records=None, source="reasoned"):
    """Adjudicate free-text outcomes by reasoning. Returns outcome rows (same shape as the other
    detectors), plus `confidence`.

    items: iterable of `(business_key, context)` — context is whatever `retrieve`/`reasoner` need.
    reasoner(context, candidates) -> {"should_have_been": "approve"|"reject",
                                      "estimated_loss": float, "confidence"?: float}
    retrieve(context, records) -> candidate records (optional; without it, candidates = records).
    """
    rows = []
    for key, ctx in items:
        candidates = retrieve(ctx, records) if retrieve is not None else (records or [])
        verdict = reasoner(ctx, candidates) or {}
        reject = str(verdict.get("should_have_been", "approve")).lower() == "reject"
        try:
            loss = float(verdict.get("estimated_loss", 0) or 0)
        except (TypeError, ValueError):
            loss = 0.0
        rows.append({
            "business_key": str(key),
            "ground_truth": "reject" if reject else "approve",
            "realized_loss_usd": loss if reject else 0.0,
            "source": source,
            "confidence": float(verdict.get("confidence", 1.0) or 1.0),
        })
    return rows
