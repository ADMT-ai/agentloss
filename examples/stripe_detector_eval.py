"""Eval for the Stripe chargeback outcome-detector — known Dispute fixtures -> expected Outcomes.

This is how we make "hardened" measurable: one fixture per edge case, each with the correct outcome
written down, run through the PURE `chargeback_outcomes`. Deterministic, no network.

    python examples/stripe_detector_eval.py     # -> prints PASS/FAIL per case; exits nonzero on any fail
"""
import sys

from agentloss.detectors.stripe import chargeback_outcomes


def D(charge, status, amount, currency="usd", reason="fraudulent"):
    return {"id": f"dp_{charge}", "charge": charge, "status": status, "amount": amount,
            "currency": currency, "reason": reason}


# each case: (name, disputes, kwargs, expected {charge: (ground_truth, realized_loss)})
CASES = [
    ("lost -> error + full loss",
     [D("ch_lost", "lost", 2000)], {}, {"ch_lost": ("reject", 20.0)}),

    ("won -> correct, no loss",
     [D("ch_won", "won", 2000)], {}, {"ch_won": ("approve", 0.0)}),

    ("charge_refunded -> error",
     [D("ch_ref", "charge_refunded", 5000)], {}, {"ch_ref": ("reject", 50.0)}),

    ("pending (needs_response) -> skipped by default",
     [D("ch_pend", "needs_response", 9900)], {}, {}),

    ("pending counted when include_pending=True",
     [D("ch_pend2", "warning_under_review", 3300)], {"include_pending": True},
     {"ch_pend2": ("reject", 33.0)}),

    ("partial dispute -> loss = dispute amount",
     [D("ch_part", "lost", 750)], {}, {"ch_part": ("reject", 7.5)}),

    ("zero-decimal currency (JPY) -> not divided by 100",
     [D("ch_jpy", "lost", 4000, currency="jpy")], {}, {"ch_jpy": ("reject", 4000.0)}),

    ("attribution: non-attributable reason -> recorded correct",
     [D("ch_ret", "lost", 8000, reason="product_not_received")],
     {"attributable_reasons": {"fraudulent", "duplicate"}}, {"ch_ret": ("approve", 0.0)}),

    ("attribution: attributable reason -> error",
     [D("ch_fraud", "lost", 8000, reason="fraudulent")],
     {"attributable_reasons": {"fraudulent", "duplicate"}}, {"ch_fraud": ("reject", 80.0)}),

    ("dedup: pending + lost on same charge -> one final outcome",
     [D("ch_dup", "needs_response", 1000), D("ch_dup", "lost", 1000)], {},
     {"ch_dup": ("reject", 10.0)}),

    ("unlinked dispute (no charge) -> skipped",
     [{"id": "dp_x", "status": "lost", "amount": 100, "currency": "usd"}], {}, {}),
]


def main():
    passed = failed = 0
    for name, disputes, kw, expected in CASES:
        rows = chargeback_outcomes(disputes, **kw)
        got = {r["business_key"]: (r["ground_truth"], round(r["realized_loss_usd"], 4)) for r in rows}
        want = {k: (gt, round(loss, 4)) for k, (gt, loss) in expected.items()}
        ok = got == want
        passed += ok
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"        expected {want}")
            print(f"        got      {got}")
    print(f"\n{passed}/{passed + failed} cases pass")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
