"""Eval that PROVES the calibration: a deliberately-biased reasoner, corrected to the truth.

The reasoning detector is fallible, so its raw (naive) numbers are biased. This is a Monte-Carlo
proof that two-phase calibration (`agentloss.calibration.calibrate`) removes that bias — recovering
the true error RATE and dollar LOSS — while the naive estimate stays wrong. Simulated data, so the
oracle plays the "gold audit" a human would do in production.

The reasoner here is biased on purpose, in both directions:
  * it MISSES 35% of real errors  -> naive rate is biased LOW
  * it OVERSTATES loss (flags the full exposure, not the partial true loss) -> naive loss biased HIGH

    python examples/calibration_eval.py     # runs many trials; exits nonzero if calibration fails to fix the bias
"""
import random
import sys

import agentloss
from agentloss import calibration, metrics, sampler
from agentloss.report import Params

TRIALS = 80
N = 1500
TRUE_RATE = 0.12
FN = 0.35          # miss rate on real errors
FP = 0.08          # false-alarm rate on good decisions


def one_trial(rng):
    agentloss.STORE.decisions.clear(); agentloss.STORE.outcomes.clear()
    oracle = {}
    for i in range(N):
        val = rng.uniform(50, 5000)
        is_err = rng.random() < TRUE_RATE
        true_loss = val * rng.uniform(0.25, 0.9) if is_err else 0.0    # partial -> exposure overstates
        key = f"D{i}"
        oracle[key] = ("reject" if is_err else "approve", true_loss)
        agentloss.STORE.record(agentloss.Decision(
            action="approve", value_at_risk_usd=val, business_key=key, use_case="sim"))

    def reasoner(d):
        true_action, true_loss = oracle[d.business_key]
        truly_err = true_action != "approve"
        flags = (rng.random() > FN) if truly_err else (rng.random() < FP)
        if flags:
            return {"should_have_been": "reject", "confidence": 0.8,
                    "estimated_loss": d.value_at_risk_usd}          # overstated: full exposure
        return {"should_have_been": "approve", "confidence": 0.8, "estimated_loss": 0.0}

    cfg = Params(target_n=500, floor=0.02, cal_q=0.3)
    sampler.run_store(reasoner, cfg, rng)

    naive = metrics.false_approve(cfg)
    cal = calibration.calibrate(lambda k: oracle[k][0], lambda k: oracle[k][1], cfg, rng, B=200)

    true_rate = sum(1 for a, _ in oracle.values() if a != "approve") / N
    true_loss = sum(l for _, l in oracle.values())
    return {
        "true_rate": true_rate, "naive_rate": naive["rate_ht"], "cal_rate": cal["corrected_rate"],
        "true_loss": true_loss, "naive_loss": naive["expected_loss_usd"], "cal_loss": cal["corrected_loss"],
        "rate_cover": cal["rate_lo"] <= true_rate <= cal["rate_hi"],
        "loss_cover": cal["loss_lo"] <= true_loss <= cal["loss_hi"],
    }


def main():
    rng = random.Random(20260701)
    rows = [one_trial(rng) for _ in range(TRIALS)]

    def mean(k):
        return sum(r[k] for r in rows) / len(rows)

    tr, tl = mean("true_rate"), mean("true_loss")
    naive_rate_bias = (mean("naive_rate") - tr) / tr
    cal_rate_bias = (mean("cal_rate") - tr) / tr
    naive_loss_bias = (mean("naive_loss") - tl) / tl
    cal_loss_bias = (mean("cal_loss") - tl) / tl
    rate_cov = mean("rate_cover")
    loss_cov = mean("loss_cover")

    print(f"trials={TRIALS}  N={N}  true_rate≈{tr:.3f}  reasoner: miss {FN:.0%}, false-alarm {FP:.0%}, loss overstated")
    print("-" * 70)
    print(f"                     rate bias      loss bias")
    print(f"naive (raw silver) : {naive_rate_bias:+7.1%}       {naive_loss_bias:+7.1%}")
    print(f"calibrated         : {cal_rate_bias:+7.1%}       {cal_loss_bias:+7.1%}")
    print(f"calibrated CI coverage — rate {rate_cov:.0%}, loss {loss_cov:.0%}  (target ~95%)")
    print("-" * 70)

    checks = {
        "calibrated rate ~unbiased (|bias|<6%)": abs(cal_rate_bias) < 0.06,
        "calibrated loss ~unbiased (|bias|<6%)": abs(cal_loss_bias) < 0.06,
        "naive rate materially biased (|bias|>10%)": abs(naive_rate_bias) > 0.10,
        "naive loss materially biased (|bias|>15%)": abs(naive_loss_bias) > 0.15,
        "calibration cuts rate bias >=3x": abs(cal_rate_bias) * 3 <= abs(naive_rate_bias) + 1e-9,
        "calibrated rate CI coverage >=85%": rate_cov >= 0.85,
        "calibrated loss CI coverage >=85%": loss_cov >= 0.85,
    }
    ok = True
    for name, passed in checks.items():
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"\n{'ALL PASS — calibration recovers the truth from a biased reasoner.' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
