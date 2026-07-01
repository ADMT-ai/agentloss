"""Oracle eval for `agentloss import` — the warehouse/CSV outcome channel. A finance-style
export with KNOWN errors must produce the exact oracle error rate and dollar loss, through
the real CLI. Deterministic, no network, no deps.

    python examples/import_eval.py   # -> PASS/FAIL per check; exits nonzero on any fail

Covers what real exports throw: money formatting ("$1,400.00"), a won dispute (correct, not
a loss), a pending row (non-final -> skipped AND kept out of the census), a row with no key,
a duplicate key (last row wins), --all-errors mode, and the no---map drafting path.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentloss.core import Store  # noqa: E402
from agentloss.persist import append_decision  # noqa: E402
from agentloss.core import Decision  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def _seed_store(path, n=10):
    """Ten approved invoices, as an agent (or the gateway) would have captured them."""
    store = Store()
    for i in range(n):
        d = store.record(Decision(action="approve", value_at_risk_usd=100.0 + i,
                                  business_key=f"INV-{i}", use_case="ap"))
        append_decision(d, path)


CSV = """invoice_no,resolution,amount,notes
INV-0,lost,"$1,400.00",fraud
INV-1,won,$210.00,customer withdrew
INV-2,under_review,$500.00,pending
INV-3,lost,900,duplicate payment
INV-3,won,900,overturned on appeal
,lost,50,row with no key
"""
# oracle: INV-0 error ($1400); INV-1 correct; INV-2 non-final (out of census);
# INV-3 last-wins -> correct; 6 undisputed -> census-correct. rate = 1/9, loss = 1400.
ORACLE_ERRORS, ORACLE_LOSS, ORACLE_RATE = 1, 1400.0, 1 / 9


def _run(args):
    return subprocess.run([sys.executable, "-m", "agentloss.cli"] + args,
                          capture_output=True, text=True, timeout=60)


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_import_")
    store = os.path.join(tmp, "store.jsonl")
    csv_path = os.path.join(tmp, "disputes.csv")
    _seed_store(store)
    with open(csv_path, "w") as f:
        f.write(CSV)

    # -- draft mode: no --map -> a usable draft from the header
    out = _run(["import", "--csv", csv_path, "--store", store])
    check("draft mode exits 0", out.returncode == 0, out.stderr)
    check("draft finds the columns",
          "business_key=invoice_no" in out.stdout and "status=resolution" in out.stdout
          and "loss=amount" in out.stdout, out.stdout)
    check("draft reports observed statuses",
          "lost" in out.stdout and "won" in out.stdout and "under_review" in out.stdout,
          out.stdout)

    # -- the real import
    out = _run(["import", "--csv", csv_path, "--store", store,
                "--map", "business_key=invoice_no,status=resolution,loss=amount",
                "--error-statuses", "lost", "--correct-statuses", "won",
                "--source", "chargeback", "--census", "--json"])
    check("import exits 0", out.returncode == 0, out.stderr)
    counts = json.loads(out.stdout)
    check("oracle errors (money parsing, last-wins)", counts["errors"] == ORACLE_ERRORS,
          str(counts))
    check("correct rows (won + overturned)", counts["correct"] == 2, str(counts))
    check("pending kept OUT of census", counts["census_correct"] == 6, str(counts))
    check("keyless row skipped", counts["skipped"]["no_key"] == 1, str(counts))

    out = _run(["report", "--json", "--store", store])
    r = json.loads(out.stdout)
    check("report: oracle rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    check("report: oracle loss ($1,400.00 parsed)",
          abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r["realized_loss_usd"]))

    # -- --all-errors mode: a pure chargebacks export (no status column)
    store2 = os.path.join(tmp, "store2.jsonl")
    csv2 = os.path.join(tmp, "chargebacks.csv")
    _seed_store(store2)
    with open(csv2, "w") as f:
        f.write("charge_id,amount\nINV-4,80.00\nINV-7,120.50\n")
    out = _run(["import", "--csv", csv2, "--store", store2,
                "--map", "business_key=charge_id,loss=amount",
                "--all-errors", "--census", "--source", "chargeback", "--json"])
    counts = json.loads(out.stdout)
    check("--all-errors: every row an error", counts["errors"] == 2, str(counts))
    out = _run(["report", "--json", "--store", store2])
    r = json.loads(out.stdout)
    check("--all-errors + census: oracle rate 2/10", abs(r["error_rate"] - 0.2) < 1e-9,
          str(r["error_rate"]))
    check("--all-errors: oracle loss", abs(r["realized_loss_usd"] - 200.5) < 1e-6,
          str(r["realized_loss_usd"]))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — a finance export in, the oracle error rate + dollar loss out.")


if __name__ == "__main__":
    main()
