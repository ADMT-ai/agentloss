"""Active sampling + verification, with a target-n PPS budget.

Inclusion probability is proportional to value-at-risk (the variance-minimizing choice for
a loss total), scaled so the EXPECTED sample size equals `sample_target_n`, plus a floor so
small-value items still get sampled for the rate. Big-ticket items saturate to pi=1 (a
certainty stratum falls out naturally). Each decision's pi is recorded for Horvitz-Thompson
reweighting in metrics.

Decisions that already carry a GOLD label (audit/human) are kept, not skipped — skipping
them would bias the rate down.
"""
from .core import STORE, report_outcome


def inclusion_probs(decisions, cfg):
    """pi_i = min(1, floor + beta * value_i), with beta chosen so sum(pi) == target_n."""
    sizes = {d.business_key: max(d.value_at_risk_usd, 1.0) for d in decisions}
    keys = list(sizes)
    N = len(keys)
    if N == 0:
        return {}
    target = min(cfg.sample_target_n, N)
    # reserve at most half the budget for the floor so PPS has room to work
    floor = min(cfg.sample_floor, 0.5 * target / N)

    def total(beta):
        return sum(min(1.0, floor + beta * sizes[k]) for k in keys)

    lo, hi = 0.0, 1.0
    while total(hi) < target and hi < 1e15:
        hi *= 10.0
    for _ in range(80):                       # bisection: total() is increasing in beta
        mid = (lo + hi) / 2.0
        if total(mid) < target:
            lo = mid
        else:
            hi = mid
    beta = (lo + hi) / 2.0
    return {k: min(1.0, floor + beta * sizes[k]) for k in keys}


def run(invoices_by_no, erp, cfg, rng, verify_fn):
    """verify_fn(invoice, erp, cfg) -> {should_have_been, confidence, failed_check, estimated_loss}"""
    probs = inclusion_probs(list(STORE.decisions.values()), cfg)
    n_sampled = n_verified = 0
    for key, d in list(STORE.decisions.items()):
        pi = probs[key]
        if rng.random() >= pi:
            continue
        n_sampled += 1
        existing = STORE.outcomes.get(key)
        if existing is not None:                 # keep the gold label; just mark it sampled
            existing.sampled = True
            existing.pi = pi
            continue
        v = verify_fn(invoices_by_no[key], erp, cfg)
        n_verified += 1
        if n_verified % 25 == 0:
            print(f"[verify] {n_verified} verified", flush=True)
        report_outcome(
            key,
            ground_truth=v["should_have_been"],
            source="verification_agent",
            fidelity="silver",
            confidence=v["confidence"],
            estimated_loss_usd=v["estimated_loss"],
            sampled=True,
            pi=pi,
        )
    return n_sampled
