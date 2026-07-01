"""Eval for the reasoning-based outcome detector — the deterministic *plumbing* eval.

The judgment itself is a fallible reasoner (measured live, e.g. `dogfood/erpnext/run_messy.py` with
Claude, and `close_caveat.py` with an ERP-grounded reasoner). This eval pins down the detector's
mapping: given a (mock) reasoner's verdict, does `reasoned_outcomes` produce the right Outcome —
including retrieval wiring, approve→loss-zeroing, defaults, and parse-safety.

    python examples/reasoning_detector_eval.py     # PASS/FAIL per case; exits nonzero on any fail
"""
import sys

from agentloss.detectors.reasoning import reasoned_outcomes


def const(v):
    return lambda ctx, candidates: v


def by_key(ctx, records):
    return [r for r in (records or []) if r["k"] == ctx]


def sum_candidates(ctx, candidates):
    if candidates:
        return {"should_have_been": "reject", "estimated_loss": sum(c["amt"] for c in candidates)}
    return {"should_have_been": "approve"}


# (name, items, reasoner, kwargs, expected {key: (ground_truth, loss)})
CASES = [
    ("reject + loss -> reject with loss",
     [("K1", None)], const({"should_have_been": "reject", "estimated_loss": 50}), {},
     {"K1": ("reject", 50.0)}),

    ("approve -> loss zeroed even if reasoner returns one",
     [("K2", None)], const({"should_have_been": "approve", "estimated_loss": 99}), {},
     {"K2": ("approve", 0.0)}),

    ("missing verdict -> default approve",
     [("K3", None)], const({}), {}, {"K3": ("approve", 0.0)}),

    ("unparseable loss -> 0 (no crash)",
     [("K4", None)], const({"should_have_been": "reject", "estimated_loss": "n/a"}), {},
     {"K4": ("reject", 0.0)}),

    ("retrieval wiring: only matching records reach the reasoner",
     [("g1", "g1")], sum_candidates,
     {"retrieve": by_key, "records": [{"k": "g1", "amt": 30}, {"k": "other", "amt": 5}]},
     {"g1": ("reject", 30.0)}),
]


def main():
    passed = failed = 0
    for name, items, reasoner, kw, expected in CASES:
        rows = reasoned_outcomes(items, reasoner, **kw)
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
