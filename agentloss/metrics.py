"""Metrics: false-approve rate (Wilson CI + Horvitz-Thompson point estimate) and loss.

We estimate the *false-approve* rate on the auto-approved population using the sampler's
silver labels, reweighted by inclusion probability. Realized dollars come only from gold
recovery-audit outcomes; expected dollars come from the reweighted silver estimates.
"""
from math import sqrt
from .core import STORE


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def false_approve(cfg, approve_actions=("approve",)):
    """False-positive rate over the COMMITTING actions. `approve_actions` names the
    action vocabulary that commits the business (a support vertical grants/partials;
    an AP vertical approves) — the statistics are identical."""
    approved = [d for d in STORE.decisions.values() if d.action in approve_actions]
    N = len(approved)
    k, n = 0, 0
    ht_num = 0.0            # Horvitz-Thompson numerator: sum(err / pi)
    exp_loss = 0.0          # reweighted expected loss
    var_loss = 0.0         # HT variance of the loss total: sum (1-pi)/pi^2 * y^2
    for d in approved:
        o = STORE.outcomes.get(d.business_key)
        if o is None or not o.sampled:          # only the random rate sample (gold OR silver)
            continue
        err = 1 if o.ground_truth != d.action else 0   # the core error definition
        n += 1
        k += err
        ht_num += err / o.pi
        if err:
            loss = o.estimated_loss_usd if o.estimated_loss_usd is not None else o.realized_loss_usd
            if loss:
                exp_loss += loss / o.pi
                var_loss += (1 - o.pi) / (o.pi * o.pi) * loss * loss   # take-all (pi=1) → 0
    p_sample, lo, hi = wilson(k, n)
    return {
        "N_approved": N,
        "n_sampled": n,
        "k_errors": k,
        "rate_sampled": p_sample,       # unweighted sample proportion
        "rate_ht": ht_num / N if N else 0.0,   # importance-reweighted population estimate
        "ci_lo": lo,
        "ci_hi": hi,
        "expected_loss_usd": exp_loss,
        "expected_loss_se": sqrt(var_loss),
    }


# Gold, realized-dollar ground-truth sources — an outcome carrying realized_loss_usd from
# any of these counts toward realized loss. (verification_agent is silver/estimated, so its
# dollars flow through expected_loss, never realized_loss.)
REALIZED_LOSS_SOURCES = frozenset(
    {"recovery_audit", "dispute", "chargeback", "refund", "human_queue"}
)


def realized_loss():
    total, recovered = 0.0, 0.0
    for o in STORE.outcomes.values():
        # `is not None` (not truthiness): a resolved outcome with realized_loss_usd=0.0 is
        # a real "$0 loss" observation, not an unresolved one.
        if o.source in REALIZED_LOSS_SOURCES and o.realized_loss_usd is not None:
            total += o.realized_loss_usd
            recovered += o.recovery_usd or 0.0
    return {"realized_loss_usd": total, "recovered_usd": recovered,
            "net_realized_usd": total - recovered}


def gt_resolvable_rate():
    """Fraction of decisions with any reachable ground-truth source (the SDK's early-warning)."""
    if not STORE.decisions:
        return 0.0
    resolved = sum(1 for k in STORE.decisions if k in STORE.outcomes)
    return resolved / len(STORE.decisions)
