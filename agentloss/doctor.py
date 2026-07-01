"""Self-check: catch the silent failures a coding agent hits when wiring agentloss.

Agents fail confidently and silently, so the SDK ships a machine-readable self-check the
agent can run to confirm its own work. `doctor()` inspects the in-process STORE (decisions +
outcomes) and returns findings in plain language, each a dict:

    {"level": "ok" | "warn" | "fail", "id": str, "message": str, "fix": str}

`validate_integration()` returns the same checks wrapped with a pass/warn/fail summary.
The `agentloss doctor` CLI runs these plus static config checks and prints guidance.

The checks specifically catch the design-partner friction: outcomes present but none
sampled (error rate reads 0%), only error outcomes reported (denominator collapse), a loss
source that won't be summed, and no outcomes at all.
"""
from .core import STORE
from .metrics import REALIZED_LOSS_SOURCES

_ORDER = {"ok": 0, "warn": 1, "fail": 2}


def _f(level, id, message, fix=""):
    return {"level": level, "id": id, "message": message, "fix": fix}


def _worst(findings):
    return max((f["level"] for f in findings), key=lambda l: _ORDER[l], default="ok")


def run_checks():
    """Inspect the in-process STORE and return a list of findings (ok/warn/fail)."""
    findings = []
    decisions = STORE.decisions
    outcomes = STORE.outcomes

    # 1) Are any decisions captured at all?
    if not decisions:
        findings.append(_f(
            "fail", "decisions_present",
            "No decisions captured in this process.",
            "Wrap your consequential action with @agentloss.decision (returning a Decision), "
            "or load decisions via agentloss.ingest_spans(...). If you are running the CLI, "
            "the store is empty by design — call agentloss.doctor() inside your app instead.",
        ))
        return findings
    findings.append(_f("ok", "decisions_present",
                       f"{len(decisions)} decision(s) captured."))

    approved = [d for d in decisions.values() if d.action == "approve"]

    # 2) Are any outcomes reported at all?
    if not outcomes:
        findings.append(_f(
            "fail", "outcomes_present",
            "No outcomes reported, so the error rate and dollar loss are unmeasurable.",
            "Report ground truth via agentloss.report_outcome(...) / "
            "agentloss.record_outcomes(rows) when you already have it, or call "
            "agentloss.sample_and_verify(verify_fn) to generate it (Tier A).",
        ))
        return findings
    findings.append(_f("ok", "outcomes_present",
                       f"{len(outcomes)} outcome(s) reported."))

    # 3) THE silent failure: outcomes exist but none is marked sampled, so the false-approve
    #    rate estimator skips every one of them and reports 0% on a non-zero-error population.
    sampled_outcomes = [o for o in outcomes.values() if o.sampled]
    sampled_approvals = [d for d in approved
                         if (o := outcomes.get(d.business_key)) is not None and o.sampled]
    if not sampled_outcomes:
        findings.append(_f(
            "fail", "outcomes_sampled",
            "Outcomes are reported but NONE is marked sampled — the error rate will read 0% "
            "and expected loss $0, silently, even if there are real errors.",
            "In agentloss >= 0.0.4 report_outcome defaults to sampled=True. Upgrade, or pass "
            "sampled=True, pi=1.0 for outcomes you have as complete ground truth; or run "
            "agentloss.sample_and_verify(...) which marks its draws sampled.",
        ))
    elif approved and not sampled_approvals:
        findings.append(_f(
            "warn", "outcomes_sampled",
            "Some outcomes are sampled, but none of them is on an 'approve' decision — the "
            "false-approve rate (denominator = sampled approvals) will be 0/0 = 0%.",
            "Report outcomes for the approved decisions too, not only for held/rejected ones.",
        ))
    else:
        findings.append(_f("ok", "outcomes_sampled",
                           f"{len(sampled_approvals)} sampled approval(s) feed the rate."))

    # 4) Denominator collapse: only error/exception outcomes reported (no correct ones), so
    #    the rate reads ~100%. A correct outcome is one where ground_truth == the action taken.
    matched = [(d, outcomes[d.business_key]) for d in decisions.values()
               if d.business_key in outcomes]
    correct = [1 for d, o in matched if o.ground_truth == d.action]
    if matched and not correct:
        findings.append(_f(
            "warn", "correct_outcomes_present",
            f"All {len(matched)} reported outcomes are errors (none where the outcome matches "
            "the action taken) — the error rate will read ~100%.",
            "Also report the outcomes that agreed with the agent (the correct approvals), not "
            "only the disputes/chargebacks, or the denominator collapses to only-errors.",
        ))
    else:
        findings.append(_f("ok", "correct_outcomes_present",
                           f"{len(correct)} correct (non-error) outcome(s) present."))

    # 5) Loss that won't be counted: a realized dollar figure on a source outside the enum
    #    that realized_loss() sums.
    bad_loss = sorted({o.source for o in outcomes.values()
                       if o.realized_loss_usd is not None
                       and o.source not in REALIZED_LOSS_SOURCES})
    if bad_loss:
        findings.append(_f(
            "warn", "loss_source_counts",
            f"realized_loss_usd is set on source(s) {bad_loss} that do NOT count toward "
            "realized loss — those dollars are silently dropped.",
            f"Use one of {sorted(REALIZED_LOSS_SOURCES)} as the source for realized dollars "
            "(silver verifier estimates flow through expected loss instead).",
        ))
    else:
        findings.append(_f("ok", "loss_source_counts",
                           "Realized-loss outcomes use counted sources."))

    return findings


def doctor():
    """Inspect the in-process STORE and return {'ok', 'findings'} catching silent failures.

    Agent-facing: call this inside your app after decisions/outcomes are recorded."""
    findings = run_checks()
    level = _worst(findings)
    return {"ok": level != "fail", "level": level, "findings": findings}


def validate_integration():
    """Structured pass/warn/fail view of the same checks (wired to the MCP tool)."""
    findings = run_checks()
    level = _worst(findings)
    return {
        "ok": level != "fail",
        "level": level,
        "passed": sum(1 for f in findings if f["level"] == "ok"),
        "warnings": sum(1 for f in findings if f["level"] == "warn"),
        "failures": sum(1 for f in findings if f["level"] == "fail"),
        "checks": findings,
    }


def format_findings(result):
    """Render a doctor()/validate_integration() result as human-readable text."""
    findings = result.get("findings") or result.get("checks") or []
    icon = {"ok": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO"}
    lines = ["agentloss doctor", "=" * 60]
    for f in findings:
        lines.append(f"[{icon[f['level']]}] {f['id']}: {f['message']}")
        if f["fix"] and f["level"] != "ok":
            lines.append(f"        fix: {f['fix']}")
    lines.append("=" * 60)
    lines.append(f"overall: {'OK' if result['ok'] else 'PROBLEMS'} (level={result['level']})")
    return "\n".join(lines)
