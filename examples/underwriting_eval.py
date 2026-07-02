"""Oracle eval for the underwriting report (docs/SUPPORT-CONCESSION.md) — the audit record
of a support agent's concession decisions must render into EXACTLY the seeded exposure,
frequency, severity, and loss ratio, including under a QA sample at known inclusion
probability (the Horvitz-Thompson path), and a record below the qualification bar must
say so. Deterministic, no network, no deps.

    python examples/underwriting_eval.py   # -> PASS/FAIL per check; exits nonzero on fail
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentloss import Decision, report_outcome  # noqa: E402
from agentloss.core import STORE  # noqa: E402
from agentloss.persist import append_decision, append_outcome  # noqa: E402
from agentloss.underwriting import underwriting_report  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def _reset():
    STORE.decisions.clear()
    STORE.outcomes.clear()


def _grant(key, amount, in_envelope=True, action="grant"):
    return STORE.record(Decision(action=action, value_at_risk_usd=amount,
                                 business_key=key, use_case="support_concession",
                                 in_envelope=in_envelope))


def seed_qualifying():
    """The oracle history. 10 covered grants ($100..$1000, total $5,500); 2 grants outside
    the concession envelope; 2 denials. Evidence: a QA sample of G1-G4 at pi=0.5 (G1
    wrongful, $80), a reconciliation gold on G5 (wrongful, $200), an inferred silver on G6
    (wrongful, est. $150). Hand-derived truths:
      N granting = 12; n evidenced = 6; k = 3 -> rate 1/2
      HT rate = (1/.5 + 1 + 1)/12 = 1/3
      expected loss = 80/.5 + 200 + 150 = 510 ; realized (gold rails) = 280
      severity: 3 errors, mean 430/3, max 200 ; exposure = 5,500 ; LTX = 510/5500
    """
    for i in range(1, 11):
        _grant(f"G{i}", 100.0 * i)
    _grant("OOE1", 500.0, in_envelope=False)
    _grant("OOE2", 500.0, in_envelope=False)
    _grant("D1", 50.0, action="deny")
    _grant("D2", 50.0, action="deny")

    # the QA sample IS the claims rail: known inclusion probability, gold verdicts
    report_outcome("G1", ground_truth="deny", source="human_queue",
                   realized_loss_usd=80.0, sampled=True, pi=0.5)
    for k in ("G2", "G3", "G4"):
        report_outcome(k, ground_truth="grant", source="human_queue",
                       realized_loss_usd=0.0, sampled=True, pi=0.5)
    report_outcome("G5", ground_truth="deny", source="recovery_audit",
                   realized_loss_usd=200.0)
    report_outcome("G6", ground_truth="deny", source="inferred", fidelity="silver",
                   confidence=0.8, estimated_loss_usd=150.0)


def main():
    _reset()
    seed_qualifying()
    r = underwriting_report()

    e = r["exposure"]
    check("exposure: granting decisions", e["granting"] == 12, str(e))
    check("exposure: out-of-envelope excluded from cover",
          e["covered_in_envelope"] == 10, str(e))
    check("exposure: total written", abs(e["total_usd"] - 5500.0) < 1e-9, str(e))
    check("exposure: max single", abs(e["max_single_usd"] - 1000.0) < 1e-9, str(e))

    fq = r["frequency"]
    check("frequency: sampled rate", abs(fq["wrongful_grant_rate"] - 0.5) < 1e-9, str(fq))
    check("frequency: HT-reweighted rate (QA pi=0.5 weighted up)",
          abs(fq["rate_reweighted"] - 1 / 3) < 1e-9, str(fq))
    check("frequency: CI brackets the rate",
          fq["rate_ci"][0] < 0.5 < fq["rate_ci"][1], str(fq))

    sv = r["severity"]
    check("severity: errors", sv["errors"] == 3, str(sv))
    check("severity: mean loss", abs(sv["mean_loss_usd"] - 430.0 / 3) < 1e-9, str(sv))
    check("severity: max loss", abs(sv["max_loss_usd"] - 200.0) < 1e-9, str(sv))

    ls = r["loss"]
    check("loss: realized only from gold rails", abs(ls["realized_usd"] - 280.0) < 1e-9,
          str(ls))
    check("loss: expected (HT, silver included)", abs(ls["expected_usd"] - 510.0) < 1e-9,
          str(ls))
    check("loss: loss-to-exposure", abs(ls["loss_to_exposure"] - 510.0 / 5500.0) < 1e-12,
          str(ls))

    ev = r["evidence"]
    check("evidence: QA sampling design detected", ev["sampling"] == "qa_sample", str(ev))
    check("evidence: gold/silver mix", ev["gold"] == 5 and ev["silver"] == 1, str(ev))
    check("record QUALIFIES", r["qualifies"] and r["level"] == "ok",
          str([f for f in r["qualification"] if f["level"] != "ok"]))

    # silver-only evidence: still a report, but flagged uncalibrated
    _reset()
    for i in range(1, 5):
        _grant(f"S{i}", 100.0)
    report_outcome("S1", ground_truth="deny", source="inferred", fidelity="silver",
                   confidence=0.7, estimated_loss_usd=60.0)
    report_outcome("S2", ground_truth="grant", source="inferred", fidelity="silver",
                   confidence=0.9)
    r2 = underwriting_report()
    check("silver-only: still qualifies, but warns", r2["qualifies"] and r2["level"] == "warn",
          str(r2["level"]))
    check("silver-only: names the missing gold budget",
          any(f["id"] == "silver_uncalibrated" and f["level"] == "warn"
              for f in r2["qualification"]), str(r2["qualification"]))

    # unpriceable exposure: does NOT qualify
    _reset()
    _grant("Z1", 0.0)
    report_outcome("Z1", ground_truth="grant", source="human_queue")
    r3 = underwriting_report()
    check("zero-exposure record does NOT qualify",
          not r3["qualifies"] and any(f["id"] == "exposure_present"
                                      and f["level"] == "fail"
                                      for f in r3["qualification"]), str(r3["level"]))

    # the CLI round-trip: persist the qualifying record, read it out-of-process
    _reset()
    seed_qualifying()
    store = os.path.join(tempfile.mkdtemp(prefix="agentloss_uw_"), "store.jsonl")
    for key, d in STORE.decisions.items():
        append_decision(d, store)
    for key, o in STORE.outcomes.items():
        append_outcome(key, o, store)
    proc = subprocess.run([sys.executable, "-m", "agentloss.cli", "underwrite",
                           "--store", store, "--json"],
                          capture_output=True, text=True, timeout=60)
    check("CLI: exits 0 for a qualifying record", proc.returncode == 0, proc.stderr)
    import json
    out = json.loads(proc.stdout)
    check("CLI: same expected loss out-of-process",
          abs(out["loss"]["expected_usd"] - 510.0) < 1e-9, proc.stdout[:200])
    check("CLI: same HT rate out-of-process",
          abs(out["frequency"]["rate_reweighted"] - 1 / 3) < 1e-9, proc.stdout[:200])

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the audit record renders into the exact seeded underwriting truth.")


if __name__ == "__main__":
    main()
