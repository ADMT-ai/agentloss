"""Oracle eval for backfill — day-one actuarial history (docs/SUPPORT-CONCESSION.md).

A historical support export (18 concessions: a human team's 8, an agent's 10, wrongful
ones written only as PROSE in the resolution notes) is backfilled into the audit record,
and the underwriting report must recover the exact seeded truths — per SEGMENT, because
the decider column is the record's agent-vs-human baseline:

    human_team   : 8 grants, $800, 2 wrongful ($60 each) -> rate 2/7, LTX 15.0%
    support_agent: 10 grants, $1,000, 1 wrongful ($40)   -> rate 1/9, LTX  4.0%
    comparison   : the agent is CHEAPER to insure than the humans it replaced

    python examples/backfill_eval.py   # -> PASS/FAIL per check; exits nonzero on fail
"""
import csv
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


WRONGFUL = "complaint upheld — refunded ${loss:.2f} to customer"
CORRECT = "reviewed: no merchant error, case closed in merchant favor"
OPEN = "case open, awaiting customer evidence"


def write_history(path, header=("ticket_id", "refund_amount", "agent_name",
                                "resolution_notes"), extra=()):
    rows = []
    for i in range(1, 9):       # the human team's history
        note = WRONGFUL.format(loss=60.0) if i <= 2 else CORRECT if i <= 7 else OPEN
        rows.append([f"H{i}", "100.00", "human_team", note])
    for i in range(1, 11):      # the agent's history
        note = WRONGFUL.format(loss=40.0) if i == 1 else CORRECT if i <= 9 else OPEN
        rows.append([f"A{i}", "100.00", "support_agent", note])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(header) + [c for c, _ in extra])
        for i, row in enumerate(rows):
            w.writerow(row + [fill(i) for _, fill in extra])


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_bf_")
    history = os.path.join(tmp, "history.csv")
    store = os.path.join(tmp, "store.jsonl")
    write_history(history)

    # backfill via the CLI — the whole loop must work out-of-process, zero code
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "backfill", "--csv", history,
         "--map", "business_key=ticket_id,amount=refund_amount,"
                  "decider=agent_name,evidence=resolution_notes",
         "--store", store, "--json"],
        capture_output=True, text=True, timeout=60)
    check("backfill exits 0", proc.returncode == 0, proc.stderr)
    counts = json.loads(proc.stdout)
    check("backfill: decisions", counts["decisions"] == 18, str(counts))
    check("backfill: wrongful adjudicated from prose", counts["errors"] == 3, str(counts))
    check("backfill: correct adjudicated", counts["correct"] == 13, str(counts))
    check("backfill: open tickets stay non-final", counts["nonfinal"] == 2, str(counts))

    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "underwrite", "--store", store,
         "--agent", "support_agent", "--baseline", "human_team", "--json"],
        capture_output=True, text=True, timeout=60)
    check("underwrite exits 0 (qualifies)", proc.returncode == 0, proc.stderr)
    r = json.loads(proc.stdout)

    check("exposure: total written", abs(r["exposure"]["total_usd"] - 1800.0) < 1e-9,
          str(r["exposure"]))
    check("frequency: overall rate", abs(r["frequency"]["wrongful_grant_rate"] - 3 / 16) < 1e-9,
          str(r["frequency"]))
    check("loss: expected (all silver, estimated from the prose)",
          abs(r["loss"]["expected_usd"] - 160.0) < 1e-9, str(r["loss"]))
    check("loss: nothing claimed realized", abs(r["loss"]["realized_usd"]) < 1e-9,
          str(r["loss"]))
    check("severity: mean/max from the notes' own dollars",
          abs(r["severity"]["mean_loss_usd"] - 160.0 / 3) < 1e-9
          and abs(r["severity"]["max_loss_usd"] - 60.0) < 1e-9, str(r["severity"]))

    seg = r["segments"]
    check("segments: both deciders present",
          set(seg) == {"human_team", "support_agent"}, str(set(seg)))
    h, a = seg["human_team"], seg["support_agent"]
    check("segment human: rate 2/7", abs(h["wrongful_grant_rate"] - 2 / 7) < 1e-9, str(h))
    check("segment human: LTX 15%", abs(h["loss_to_exposure"] - 0.15) < 1e-9, str(h))
    check("segment agent: rate 1/9", abs(a["wrongful_grant_rate"] - 1 / 9) < 1e-9, str(a))
    check("segment agent: LTX 4%", abs(a["loss_to_exposure"] - 0.04) < 1e-9, str(a))

    cmp = r["baseline_comparison"]
    check("comparison: rate delta", abs(cmp["rate_delta"] - (1 / 9 - 2 / 7)) < 1e-9, str(cmp))
    check("comparison: LTX delta", abs(cmp["loss_to_exposure_delta"] + 0.11) < 1e-9, str(cmp))
    check("comparison: the agent prices cheaper than the humans",
          cmp["cheaper_to_insure"] is True, str(cmp))

    check("honesty: silver-only history warns (uncalibrated)",
          r["level"] == "warn" and any(f["id"] == "silver_uncalibrated"
                                       for f in r["qualification"]
                                       if f["level"] == "warn"), str(r["level"]))

    # the funnel: a backfilled history is an ASSESSMENT — it qualifies you, but binding
    # coverage requires the middleware capturing live decisions
    b = r["binding"]
    check("funnel: backfilled record is assessment-grade", b["capture"] == "historical",
          str(b))
    check("funnel: not bound-ready without the middleware", b["bound_ready"] is False,
          str(b))
    check("funnel: the requirement names the gateway",
          "gateway" in (b["requirement"] or ""), str(b))

    # ZERO-CONFIG: a Zendesk-shaped export (different header names, workflow-status and
    # subject noise columns) with NO --map must draft the mapping itself and recover the
    # identical oracle — bare "Status" (open/solved) must NOT be mistaken for a ruling
    zd = os.path.join(tmp, "zendesk.csv")
    store2 = os.path.join(tmp, "store2.jsonl")
    write_history(zd, header=("Ticket Id", "Refund Amount", "Assignee",
                              "Resolution Notes"),
                  extra=(("Status", lambda i: "solved" if i % 3 else "closed"),
                         ("Subject", lambda i: f"Refund request #{i}")))
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "backfill", "--csv", zd,
         "--store", store2, "--json"],
        capture_output=True, text=True, timeout=60)
    check("zero-config: backfill exits 0 with no --map", proc.returncode == 0,
          proc.stderr)
    check("zero-config: the drafted map is announced",
          "drafted from the header" in proc.stderr and "Resolution Notes" in proc.stderr,
          proc.stderr)
    counts2 = json.loads(proc.stdout)
    check("zero-config: identical adjudication", counts2 == counts,
          f"{counts2} vs {counts}")
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "underwrite", "--store", store2,
         "--agent", "support_agent", "--baseline", "human_team", "--json"],
        capture_output=True, text=True, timeout=60)
    r2 = json.loads(proc.stdout)
    check("zero-config: identical segment truths",
          abs(r2["segments"]["support_agent"]["loss_to_exposure"] - 0.04) < 1e-9
          and abs(r2["segments"]["human_team"]["loss_to_exposure"] - 0.15) < 1e-9,
          str(r2["segments"]))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — a prose-only history backfills into the exact seeded "
          "actuarial truth, segmented agent vs human.")


if __name__ == "__main__":
    main()
