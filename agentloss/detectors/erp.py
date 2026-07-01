"""ERP AP credit-memo / debit-note outcome-detector (Stage 2 — semi-structured records).

Given an accounts-payable system's reversal records (credit memos / debit notes), produce hardened
Outcomes for the invoices they reverse. Field-name-agnostic via accessors, so it works with ERPNext,
NetSuite, SAP, QuickBooks, … Hardened for what a real AP ledger throws: **partial** reversals,
**multiple memos per invoice** (aggregate), **linked vs unlinked** (`return_against` present or not),
**sign** (debit notes are negative), **reason-based attribution** (billing error vs legitimate
return), and **dedup**.

Pure `credit_memo_outcomes(...)` is the eval'd core; wire the accessors to your ERP's fields.

Note: `realized_loss_usd` is the SoR's **stated clawback** (memo) amount. That equals the true
economic loss when the whole invoice was the error (a duplicate / fraud). For a *partial* error
reversed by a full-invoice memo it can overstate the loss — recovering the true figure needs
reasoning about *why* the reversal happened (that's the next rung: reasoning-based detection).
"""


def credit_memo_outcomes(memos, *, target_of, amount_of, id_of=None, reason_of=None,
                         attributable_reasons=None, source="credit_memo"):
    """Reversal records -> outcome rows for `record_outcomes` / `report_outcome`.

    Accessors (called per memo record):
      target_of(m) -> the invoice `business_key` this memo reverses (falsy -> unlinked, skipped)
      amount_of(m) -> the memo's reversal amount (sign-agnostic; abs used)
      id_of(m)     -> a memo id for dedup (optional)
      reason_of(m) -> a reason/type string, for attribution (optional)

    Aggregates all memos per invoice. loss = sum of **attributable** memo amounts. An invoice with a
    positive attributable loss -> error (`ground_truth="reject"`); an invoice whose only memos are
    non-attributable (a legitimate return) -> correct (`ground_truth="approve"`, loss 0). Invoices
    with no memo are not emitted (their "correct" comes from the census/join over the decisions).
    """
    attributable = set(attributable_reasons) if attributable_reasons is not None else None
    seen_ids = set()
    per_invoice = {}
    for m in memos:
        inv = str(target_of(m) or "")
        if not inv:
            continue                                     # unlinked -> can't join to a decision
        if id_of is not None:
            mid = id_of(m)
            if mid in seen_ids:
                continue                                 # dedup
            seen_ids.add(mid)
        try:
            amt = abs(float(amount_of(m) or 0))
        except (TypeError, ValueError):
            amt = 0.0
        reason = reason_of(m) if reason_of is not None else None
        is_attributable = (attributable is None) or (reason in attributable)
        rec = per_invoice.setdefault(inv, 0.0)
        if is_attributable:
            per_invoice[inv] = rec + amt

    rows = []
    for inv, attr_loss in per_invoice.items():
        is_err = attr_loss > 0
        rows.append({
            "business_key": inv,
            "ground_truth": "reject" if is_err else "approve",
            "realized_loss_usd": attr_loss if is_err else 0.0,
            "source": source,
        })
    return rows
