"""Scorecard: does AgentAudit recover the planted truth?

The eval is the judge and is allowed to peek the oracle. The agent/verifier/SDK are not.
"""
import agentaudit
from agentaudit import metrics


def scorecard(oracle, cfg, calib=None):
    dec = agentaudit.STORE.decisions
    approved = {k: d for k, d in dec.items() if d.action == "approve"}

    # --- ORACLE TRUTH over the auto-approved population ---
    true_escapes = [k for k in approved if oracle[k]["correct_action"] != "approve"]
    true_rate = len(true_escapes) / len(approved) if approved else 0.0
    true_escaped_loss = sum(oracle[k]["true_loss_usd"] for k in true_escapes)

    # --- MEASURED ---
    m = metrics.false_approve(cfg)
    rl = metrics.realized_loss()

    # --- verifier quality vs oracle, on the sampled+silver approved decisions ---
    tp = fp = fn = tn = 0
    for k, d in approved.items():
        o = agentaudit.STORE.outcomes.get(k)
        if o is None or o.source != "verification_agent":
            continue
        pred_err = o.ground_truth != "approve"
        true_err = oracle[k]["correct_action"] != "approve"
        tp += pred_err and true_err
        fp += pred_err and not true_err
        fn += (not pred_err) and true_err
        tn += (not pred_err) and (not true_err)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")

    ci_covers = m["ci_lo"] <= true_rate <= m["ci_hi"]

    lines = []
    p = lines.append
    p("=" * 66)
    p("AGENTAUDIT DOGFOOD SCORECARD")
    p("=" * 66)
    p(f"decisions total          : {len(dec)}")
    p(f"auto-approved            : {len(approved)}")
    p(f"gt_resolvable_rate       : {metrics.gt_resolvable_rate():.2%}")
    p("-" * 66)
    p("FALSE-APPROVE RATE (the insurable peril)")
    p(f"  ORACLE true rate       : {true_rate:.3%}  ({len(true_escapes)} escapes)")
    p(f"  measured (sampled)     : {m['rate_sampled']:.3%}   "
      f"[{m['ci_lo']:.3%}, {m['ci_hi']:.3%}]  n={m['n_sampled']}, k={m['k_errors']}")
    p(f"  measured (HT reweight) : {m['rate_ht']:.3%}")
    p(f"  CI covers truth        : {'PASS' if ci_covers else 'FAIL'}")
    p("-" * 66)
    p("VERIFIER QUALITY (silver vs oracle, on sampled approves)")
    p(f"  precision / recall     : {precision:.2f} / {recall:.2f}   (tp={tp} fp={fp} fn={fn})")
    if calib is not None:
        p("-" * 66)
        p("CALIBRATION (fallible verifier -> bias-corrected, two-phase gold)")
        p(f"  verifier prec/recall   : {calib['precision']:.2f} / {calib['recall']:.2f}   "
          f"(confirmed tp={calib['tp']} fp={calib['fp']}, "
          f"missed={calib['missed_in_sample']}/{calib['neg_checked']} spot-checked)")
        rc = calib["rate_lo"] <= true_rate <= calib["rate_hi"]
        p(f"  naive silver rate      : {m['rate_ht']:.3%}   (uncorrected)")
        p(f"  corrected rate         : {calib['corrected_rate']:.3%}  "
          f"[{calib['rate_lo']:.3%}, {calib['rate_hi']:.3%}]  ({'PASS' if rc else 'FAIL'})")
        lc = calib["loss_lo"] <= true_escaped_loss <= calib["loss_hi"]
        p(f"  corrected loss         : ${calib['corrected_loss']:,.0f}  "
          f"[${max(0, calib['loss_lo']):,.0f}, ${calib['loss_hi']:,.0f}]  ({'PASS' if lc else 'FAIL'})")
        p(f"  gold labels spent      : {calib['gold_budget']}")
    p("-" * 66)
    p("DOLLARS")
    loss_lo = m["expected_loss_usd"] - 1.96 * m["expected_loss_se"]
    loss_hi = m["expected_loss_usd"] + 1.96 * m["expected_loss_se"]
    dollars_cover = loss_lo <= true_escaped_loss <= loss_hi
    p(f"  ORACLE escaped loss    : ${true_escaped_loss:,.0f}")
    p(f"  measured expected loss : ${m['expected_loss_usd']:,.0f}  "
      f"[${max(0, loss_lo):,.0f}, ${loss_hi:,.0f}]  ({'PASS' if dollars_cover else 'FAIL'})")
    p(f"  realized (audit) loss  : ${rl['realized_loss_usd']:,.0f}  "
      f"(net ${rl['net_realized_usd']:,.0f} after recovery)")
    p("=" * 66)
    return "\n".join(lines), {"ci_covers": ci_covers, "true_rate": true_rate,
                              "measured": m, "precision": precision, "recall": recall}
