"""The readout: turn captured decisions + outcomes into the number — error rate + dollar loss.

Two ground-truth paths (same as the SDK):
  * report_outcome(...)          — you push resolved outcomes (correction, dispute, audit, queue)
  * sample_and_verify(verify_fn) — active sampling + a verification agent produce ground truth
                                   when you have no external labels (Tier A), so day-one value
                                   isn't blocked on wiring a system of record.
"""
import random

from . import metrics, sampler
from .core import STORE


class Params:
    """Lightweight config for the generic (non-dogfood) path."""
    def __init__(self, target_n=600, floor=0.02, cal_q=0.15):
        self.sample_target_n = target_n
        self.sample_floor = floor
        self.cal_negative_sample_rate = cal_q


def sample_and_verify(verify_fn=None, target_n=600, seed=0):
    """Active-sample the captured decisions and label them with a verification agent.

    verify_fn(decision) -> {should_have_been, confidence?, estimated_loss?}
    If verify_fn is None, uses the default LLM verifier (Claude; needs agentloss[claude]).
    Returns the number of decisions verified."""
    if verify_fn is None:
        from .llm_verifier import llm_verifier
        verify_fn = llm_verifier()
    return sampler.run_store(verify_fn, Params(target_n=target_n), random.Random(seed))


def report():
    """Compute the error rate + dollar loss from the captured store."""
    m = metrics.false_approve(Params())
    rl = metrics.realized_loss()
    return {
        "decisions": len(STORE.decisions),
        "auto_approved": m["N_approved"],
        "sampled": m["n_sampled"],
        "error_rate": m["rate_sampled"],
        "error_rate_ci": [m["ci_lo"], m["ci_hi"]],
        "error_rate_reweighted": m["rate_ht"],
        "expected_loss_usd": m["expected_loss_usd"],
        "expected_loss_se": m["expected_loss_se"],
        "realized_loss_usd": rl["realized_loss_usd"],
        "gt_resolvable_rate": metrics.gt_resolvable_rate(),
    }


def print_report():
    r = report()
    lo, hi = r["error_rate_ci"]
    print("=" * 60)
    print("agentloss report")
    print("=" * 60)
    print(f"decisions captured   : {r['decisions']}")
    print(f"auto-approved        : {r['auto_approved']}")
    print(f"ground-truth coverage: {r['gt_resolvable_rate']:.1%}")
    print("-" * 60)
    print(f"error rate           : {r['error_rate']:.3%}  [{lo:.3%}, {hi:.3%}]  (n={r['sampled']})")
    print(f"expected loss        : ${r['expected_loss_usd']:,.0f}  "
          f"(±${1.96 * r['expected_loss_se']:,.0f})")
    print(f"realized loss (gold) : ${r['realized_loss_usd']:,.0f}")
    print("=" * 60)
    return r
