"""Stripe chargeback outcome-detector (Stage 1 — the simplest SoR: first-class Dispute objects).

`chargeback_outcomes(disputes)` is a PURE function (Stripe Dispute objects -> outcome rows) — it is
the thing the eval pins down. `detect(stripe)` adds the live-API fetch. Hardened for the edge cases
a real payments SoR throws: won vs lost, partial amounts, zero-decimal currencies, reason-based
attribution, pending/non-final disputes, and dedup.
"""
from ..core import STORE, report_outcome

# Stripe reports amounts in the smallest currency unit EXCEPT for zero-decimal currencies, where the
# amount is already in the major unit. https://stripe.com/docs/currencies#zero-decimal
_ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd",
                 "vuv", "xaf", "xof", "xpf"}

_LOST = {"lost", "charge_refunded"}     # final, adverse -> a realized loss
_WON = {"won"}                          # final, favorable -> the decision was fine
# everything else (needs_response, under_review, warning_needs_response, warning_under_review,
# warning_closed) is non-final -> no realized outcome yet.


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _to_major(amount, currency):
    """Minor units -> major units, respecting zero-decimal currencies."""
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if (currency or "").lower() in _ZERO_DECIMAL else amount / 100.0


def _finality(status):
    return 2 if (status or "").lower() in (_LOST | _WON) else 1


def chargeback_outcomes(disputes, *, source="chargeback", attributable_reasons=None,
                        include_pending=False):
    """Pure: Stripe Dispute objects -> outcome rows for `record_outcomes` / `report_outcome`.

    - lost / charge_refunded -> error (`ground_truth="reject"`), `realized_loss_usd` = dispute
      amount (partial-safe, currency-correct).
    - won -> correct (`ground_truth="approve"`), loss 0.
    - pending / non-final -> skipped, unless `include_pending=True` (then treated as an
      as-yet-unresolved loss).
    - `attributable_reasons`: if given (e.g. {"fraudulent", "duplicate"}), only disputes with those
      reasons count as an agent error; other real reversals (a legitimate return) are recorded as
      correct — not the agent's fault.
    - dedup by charge, keeping the most final record.

    Each row also carries `currency`, `reason`, `status` for auditability.
    """
    attributable = set(attributable_reasons) if attributable_reasons is not None else None

    by_charge = {}
    for d in disputes:
        charge = str(_get(d, "charge", "") or _get(d, "payment_intent", "") or "")
        if not charge:
            continue                                    # unlinked -> can't join to a decision
        prev = by_charge.get(charge)
        if prev is None or _finality(_get(d, "status")) > _finality(_get(prev, "status")):
            by_charge[charge] = d

    rows = []
    for charge, d in by_charge.items():
        status = (_get(d, "status") or "").lower()
        final = status in (_LOST | _WON)
        if not final and not include_pending:
            continue                                    # unresolved -> no outcome yet
        lost = (status in _LOST) or (not final and include_pending)
        reason = _get(d, "reason")
        if lost and attributable is not None and reason not in attributable:
            lost = False                                # real reversal, but not the agent's fault
        amount = _to_major(_get(d, "amount", 0), _get(d, "currency"))
        rows.append({
            "business_key": charge,
            "ground_truth": "reject" if lost else "approve",
            "realized_loss_usd": amount if lost else 0.0,
            "source": source,
            "currency": (_get(d, "currency") or "usd").upper(),
            "reason": reason,
            "status": status,
        })
    return rows


def detect(stripe, *, limit=100, **kw):
    """Fetch disputes from the live Stripe API -> hardened outcome rows (same shape as the pure fn)."""
    listing = stripe.Dispute.list(limit=limit)
    disputes = (listing.auto_paging_iter() if hasattr(listing, "auto_paging_iter")
                else _get(listing, "data", listing))
    return chargeback_outcomes(list(disputes), **kw)


def record(rows, *, census=False, source="chargeback"):
    """Write detector rows into agentloss. census=True also marks every other captured decision
    correct (only valid when the reversal feed is the COMPLETE set of errors). Returns counts."""
    seen = set()
    n_err = n_ok = 0
    for r in rows:
        report_outcome(r["business_key"], ground_truth=r["ground_truth"], source=r.get("source", source),
                       fidelity="gold", realized_loss_usd=r["realized_loss_usd"],
                       estimated_loss_usd=r["realized_loss_usd"])
        seen.add(r["business_key"])
        n_err += r["ground_truth"] != "approve"
        n_ok += r["ground_truth"] == "approve"
    if census:
        for key in list(STORE.decisions):
            if key not in seen:
                report_outcome(key, ground_truth="approve", source=source, fidelity="gold",
                               realized_loss_usd=0.0, estimated_loss_usd=0.0)
                n_ok += 1
    return {"errors": n_err, "correct": n_ok}
