"""The underwriting report — render the audit record into what a pricing actuary needs.

The support-concession vertical (docs/SUPPORT-CONCESSION.md): an agent's concession
decisions joined to admissible evidence, summarized as exposure / frequency / severity /
loss ratio / evidence provenance, plus the QUALIFICATION findings — does this record
qualify for insurance at all? Everything is derived from the store; nothing is
self-reported. Doctor-style findings, same shapes as agentloss.doctor.
"""
from .core import STORE
from .doctor import _worst, run_checks
from .metrics import REALIZED_LOSS_SOURCES, false_approve
from .report import Params

__all__ = ["underwriting_report", "qualification_checks"]

# outcome sources admissible as GOLD claims evidence for a concession record
_GOLD_SOURCES = frozenset(REALIZED_LOSS_SOURCES)
# the committing actions: what "the agent gave money away" looks like in this vertical
_GRANTING = ("approve", "grant", "partial")


def _f(level, id, message, fix=""):
    return {"level": level, "id": id, "message": message, "fix": fix}


def qualification_checks():
    """Profile checks on top of the doctor's: does this record QUALIFY as an
    insurable concession history? (docs/SUPPORT-CONCESSION.md #qualification)"""
    findings = []
    decisions = list(STORE.decisions.values())
    outcomes = STORE.outcomes

    # 1) every decision carries exposure and an envelope verdict
    no_exposure = [d for d in decisions if not d.value_at_risk_usd]
    if no_exposure:
        findings.append(_f("fail", "exposure_present",
                           f"{len(no_exposure)} decision(s) carry no value_at_risk_usd — "
                           "unpriceable exposure.",
                           "Set value_at_risk_usd to the concession amount on every "
                           "decision (the amount requested, for denials)."))
    elif decisions:
        findings.append(_f("ok", "exposure_present",
                           f"All {len(decisions)} decision(s) carry exposure."))

    out_env = sum(1 for d in decisions if not d.in_envelope)
    findings.append(_f("ok", "envelope_recorded",
                       f"{out_env} decision(s) recorded out-of-envelope (excluded from "
                       "covered exposure)." if out_env else
                       "All decisions in-envelope. Fine if true — an envelope that never "
                       "excludes anything deserves a second look."))

    # 2) provenance-typed dollars: realized only from gold sources; silver estimated
    bad_gold = [k for k, o in outcomes.items()
                if o.fidelity == "gold" and o.source not in _GOLD_SOURCES]
    if bad_gold:
        findings.append(_f("fail", "gold_provenance",
                           f"{len(bad_gold)} outcome(s) claim gold fidelity from a "
                           "non-admissible source — realized dollars need a claims rail "
                           "(QA review, reconciliation, chargeback), not inference.",
                           "Record inferred/reasoned outcomes with fidelity='silver'."))
    elif outcomes:
        findings.append(_f("ok", "gold_provenance",
                           "Every gold outcome cites an admissible claims source."))

    # 3) silver dollars must be calibratable: confidence present, gold budget exists
    silver = [o for o in outcomes.values() if o.fidelity == "silver"]
    gold = [o for o in outcomes.values() if o.fidelity == "gold"]
    if silver and not gold:
        findings.append(_f("warn", "silver_uncalibrated",
                           f"All {len(silver)} evidenced outcome(s) are silver "
                           "(inferred/estimated) with NO gold budget to calibrate "
                           "against — the loss estimate is uncorrected.",
                           "Feed a QA-review sample in as gold (source='human_queue', "
                           "sampled=True, pi=<inclusion probability>) and run "
                           "agentloss.calibrate."))
    elif silver:
        findings.append(_f("ok", "silver_uncalibrated",
                           f"{len(silver)} silver outcome(s) alongside {len(gold)} gold "
                           "— calibratable."))

    return findings


def underwriting_report(cfg=None):
    """The actuary's view of the record. Returns a dict; see docs/SUPPORT-CONCESSION.md."""
    decisions = list(STORE.decisions.values())
    outcomes = STORE.outcomes
    granting = [d for d in decisions if d.action in _GRANTING]
    covered = [d for d in granting if d.in_envelope]   # out-of-envelope: not insurable
    exposures = [d.value_at_risk_usd or 0.0 for d in covered]

    m = false_approve(cfg or Params(), approve_actions=_GRANTING)
    # severity: dollars among evidenced wrongful grants (gold realized, silver estimated)
    losses = []
    realized = expected = 0.0
    for d in covered:
        o = outcomes.get(d.business_key)
        if o is None or o.ground_truth == d.action:
            continue
        loss = (o.realized_loss_usd if o.realized_loss_usd is not None
                else o.estimated_loss_usd) or 0.0
        losses.append(loss)
        if o.realized_loss_usd is not None and o.source in _GOLD_SOURCES:
            realized += o.realized_loss_usd
    expected = m["expected_loss_usd"]

    evidenced = [k for k in STORE.decisions if k in outcomes]
    sampled = [o for o in outcomes.values() if o.sampled]
    qa_sampled = [o for o in sampled if (o.pi or 1.0) < 1.0]
    sources = {}
    for o in outcomes.values():
        sources[o.source] = sources.get(o.source, 0) + 1

    qual = qualification_checks() + run_checks()
    level = _worst(qual)
    total_exposure = sum(exposures)
    return {
        "profile": "support_concession",
        "qualifies": level != "fail",
        "level": level,
        "exposure": {
            "decisions": len(decisions),
            "granting": len(granting),
            "covered_in_envelope": len(covered),
            "total_usd": total_exposure,
            "max_single_usd": max(exposures, default=0.0),
        },
        "frequency": {
            "wrongful_grant_rate": m["rate_sampled"],
            "rate_ci": [m["ci_lo"], m["ci_hi"]],
            "rate_reweighted": m["rate_ht"],     # HT estimate under QA sampling
            "n_evidenced": m["n_sampled"],
        },
        "severity": {
            "errors": len(losses),
            "mean_loss_usd": (sum(losses) / len(losses)) if losses else 0.0,
            "max_loss_usd": max(losses, default=0.0),
        },
        "loss": {
            "realized_usd": realized,
            "expected_usd": expected,
            "loss_to_exposure": (expected / total_exposure) if total_exposure else 0.0,
        },
        "evidence": {
            "outcome_coverage": (len(evidenced) / len(decisions)) if decisions else 0.0,
            "gold": sum(1 for o in outcomes.values() if o.fidelity == "gold"),
            "silver": sum(1 for o in outcomes.values() if o.fidelity == "silver"),
            "sampling": ("qa_sample" if qa_sampled else
                         "census" if sampled else "none"),
            "sources": sources,
        },
        "qualification": qual,
    }
