"""Calibration harness — makes a FALLIBLE verifier trustworthy.

A real verification agent (e.g. Claude) has false alarms and misses, so its silver labels
are biased. We spend a small GOLD budget (human review, or the oracle in the dogfood) to
correct that bias with a two-phase, screen-and-confirm design:

  Phase 1 — confirm EVERY flag. Verifier-positives are rare, so gold-label all of them.
            This yields exact precision and the true-error weight among flags.
  Phase 2 — spot-check a fraction q of the (many) verifier-negatives to estimate the
            miss rate, and reweight the misses back up by 1/q.

Corrected error total = (confirmed true flags) + (estimated missed errors), each
Horvitz-Thompson-weighted by the original 1/pi. Losses are taken from GOLD (not the
verifier's estimate), so dollars are corrected too. A bootstrap gives CIs that fold in
both the PPS sampling and the calibration uncertainty.
"""
from .core import STORE


def _pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def _resample_sum(contribs, rng):
    n = len(contribs)
    if n == 0:
        return 0.0
    return sum(contribs[rng.randrange(n)] for _ in range(n))


def calibrate(gold_action, gold_loss, cfg, rng, B=400):
    approved = [d for d in STORE.decisions.values() if d.action == "approve"]
    N = len(approved)
    q = cfg.cal_negative_sample_rate

    # Sampled approved decisions split by label source:
    #   * gold (audit-caught) — already truth, count directly (no new gold spent)
    #   * silver (verifier)   — run the two-phase confirm/spot-check
    gold_err_c, gold_loss_c = [], []
    silver = []
    for d in approved:
        o = STORE.outcomes.get(d.business_key)
        if not o or not o.sampled:
            continue
        if o.source == "verification_agent":
            silver.append((d, o))
        else:                                   # gold (recovery_audit): audit only labels errors
            err = o.ground_truth != "approve"
            gold_err_c.append((1.0 / o.pi) if err else 0.0)
            gold_loss_c.append(((o.realized_loss_usd or 0.0) / o.pi) if err else 0.0)

    positives = [(d, o) for d, o in silver if o.ground_truth != "approve"]
    negatives = [(d, o) for d, o in silver if o.ground_truth == "approve"]

    # Phase 1 — gold-confirm every flag
    tp = fp = 0
    pos_err_c, pos_loss_c = [], []
    for d, o in positives:
        if gold_action(d.business_key) != "approve":
            tp += 1
            pos_err_c.append(1.0 / o.pi)
            pos_loss_c.append(gold_loss(d.business_key) / o.pi)
        else:
            fp += 1
            pos_err_c.append(0.0)
            pos_loss_c.append(0.0)

    # Phase 2 — spot-check q of the approvals to catch misses
    checked = miss = 0
    neg_err_c, neg_loss_c = [], []
    for d, o in negatives:
        if rng.random() >= q:
            continue
        checked += 1
        if gold_action(d.business_key) != "approve":
            miss += 1
            neg_err_c.append(1.0 / (o.pi * q))
            neg_loss_c.append(gold_loss(d.business_key) / (o.pi * q))
        else:
            neg_err_c.append(0.0)
            neg_loss_c.append(0.0)

    corrected_rate = (sum(gold_err_c) + sum(pos_err_c) + sum(neg_err_c)) / N if N else 0.0
    corrected_loss = sum(gold_loss_c) + sum(pos_loss_c) + sum(neg_loss_c)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")   # verifier's own precision
    w_pos, w_miss = sum(pos_err_c), sum(neg_err_c)
    recall = w_pos / (w_pos + w_miss) if (w_pos + w_miss) else float("nan")  # verifier's own recall

    rates, losses = [], []
    for _ in range(B):
        e = _resample_sum(gold_err_c, rng) + _resample_sum(pos_err_c, rng) + _resample_sum(neg_err_c, rng)
        l = _resample_sum(gold_loss_c, rng) + _resample_sum(pos_loss_c, rng) + _resample_sum(neg_loss_c, rng)
        rates.append(e / N if N else 0.0)
        losses.append(l)

    return {
        "corrected_rate": corrected_rate,
        "rate_lo": _pct(rates, 0.025), "rate_hi": _pct(rates, 0.975),
        "corrected_loss": corrected_loss,
        "loss_lo": _pct(losses, 0.025), "loss_hi": _pct(losses, 0.975),
        "precision": precision, "recall": recall,
        "tp": tp, "fp": fp, "missed_in_sample": miss, "neg_checked": checked,
        "gold_budget": len(positives) + checked,
    }
