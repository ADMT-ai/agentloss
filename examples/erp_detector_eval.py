"""Eval for the ERP credit-memo outcome-detector — known memo fixtures -> expected Outcomes.

One fixture per edge case with the correct outcome written down, run through the PURE
`credit_memo_outcomes`. Deterministic, no ERP needed.

    python examples/erp_detector_eval.py     # PASS/FAIL per case; exits nonzero on any fail
"""
import sys

from agentloss.detectors.erp import credit_memo_outcomes


def M(target, amount, reason="overbill", id="DN"):
    """A credit-memo / debit-note record (ERPNext-shaped: return_against + negative grand_total)."""
    return {"name": id, "return_against": target, "grand_total": amount, "reason": reason}


BASE = dict(target_of=lambda m: m.get("return_against"),
            amount_of=lambda m: m.get("grand_total"),
            id_of=lambda m: m.get("name"),
            reason_of=lambda m: m.get("reason"))


def run(memos, **kw):
    return credit_memo_outcomes(memos, **{**BASE, **kw})


# (name, memos, kwargs, expected {invoice: (ground_truth, loss)})
CASES = [
    ("single memo -> reject + loss (sign-agnostic)",
     [M("INV1", -500)], {}, {"INV1": ("reject", 500.0)}),

    ("partial memo -> loss = memo amount",
     [M("INV2", -120)], {}, {"INV2": ("reject", 120.0)}),

    ("multiple memos per invoice -> summed",
     [M("INV3", -100, id="DN1"), M("INV3", -50, id="DN2")], {}, {"INV3": ("reject", 150.0)}),

    ("dedup: same memo id twice -> counted once",
     [M("INV4", -70, id="DN9"), M("INV4", -70, id="DN9")], {}, {"INV4": ("reject", 70.0)}),

    ("attribution: legitimate return -> recorded correct",
     [M("INV5", -800, reason="return")], {"attributable_reasons": {"duplicate", "overbill"}},
     {"INV5": ("approve", 0.0)}),

    ("attribution: mixed -> loss = attributable memos only",
     [M("INV6", -300, reason="overbill", id="A"), M("INV6", -200, reason="return", id="B")],
     {"attributable_reasons": {"duplicate", "overbill"}}, {"INV6": ("reject", 300.0)}),

    ("unlinked memo (no return_against) -> skipped",
     [M(None, -100)], {}, {}),

    ("positive-sign amount also handled",
     [M("INV8", 450)], {}, {"INV8": ("reject", 450.0)}),
]


def main():
    passed = failed = 0
    for name, memos, kw, expected in CASES:
        rows = run(memos, **kw)
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
