"""Oracle eval for `agentloss gateway init` — the manifest scaffolder must produce a manifest
that WORKS, not just plausible JSON. Deterministic, no network, no deps.

    python examples/gateway_init_eval.py   # -> PASS/FAIL per check; exits nonzero on any fail

Two stages:
1. Run `gateway init` against the mock SoR server with pre-seeded history (`--seed`, as a real
   SoR would have) and assert the draft: the money-mover classified (and ONLY it), amount /
   currency / business-key paths right, the reversal read probed into working row paths and a
   status mapping.
2. Prove the draft by RUNNING it: drive the full gateway flow (payments -> sync -> report)
   with the drafted manifest and assert the recovered error rate and dollar loss match the
   same oracle as examples/gateway_eval.py.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "examples"))
from gateway_eval import (Client, ORACLE_DECISIONS, ORACLE_ERRORS, ORACLE_LOSS, ORACLE_RATE,
                          PAYMENTS)  # noqa: E402

MOCK = os.path.join(ROOT, "examples", "gateway", "mock_sor_server.py")

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_init_")
    manifest_path = os.path.join(tmp, "drafted.manifest.json")

    # -- stage 1: draft against a server with history
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.gateway", "init", "--out", manifest_path,
         "--use-case", "payments", "--", sys.executable, MOCK, "--seed"],
        capture_output=True, text=True, timeout=60)
    check("init exits 0", proc.returncode == 0, proc.stderr)
    with open(manifest_path) as f:
        m = json.load(f)

    check("money-mover classified", "create_payment" in m["tools"], json.dumps(m["tools"]))
    check("read-only tools NOT classified",
          "lookup_customer" not in m["tools"] and "list_disputes" not in m["tools"],
          json.dumps(list(m["tools"])))
    spec = m["tools"].get("create_payment", {})
    check("amount path", spec.get("amount") == "arguments.amount", json.dumps(spec))
    check("currency path", spec.get("currency") == "arguments.currency", json.dumps(spec))
    check("business_key default", spec.get("business_key") == "result.id", json.dumps(spec))

    out = m["outcomes"].get("list_disputes", {})
    check("reversal read classified", bool(out), json.dumps(m["outcomes"]))
    check("probe found the rows", out.get("items") == "result.disputes", json.dumps(out))
    check("probe found the join key", out.get("business_key") == "item.payment_id",
          json.dumps(out))
    check("probe mapped the statuses",
          out.get("error_statuses") == ["lost"] and out.get("correct_statuses") == ["won"]
          and out.get("status") == "item.status" and out.get("loss") == "item.amount",
          json.dumps(out))

    # -- stage 2: the draft must WORK — same flow + oracle as gateway_eval, drafted manifest
    store = os.path.join(tmp, "store.jsonl")
    client = Client([sys.executable, "-m", "agentloss.gateway",
                     "--manifest", manifest_path, "--store", store,
                     "--", sys.executable, MOCK])
    client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                              "clientInfo": {"name": "eval", "version": "0"}})
    client.notify("notifications/initialized")
    for customer, amount in PAYMENTS:
        client.call_tool("create_payment",
                         {"amount": amount, "currency": "USD", "customer": customer})
    synced, _ = client.call_tool("agentloss_sync_outcomes")
    check("drafted manifest: sync recovers oracle errors",
          synced["errors"] == ORACLE_ERRORS, str(synced))
    r, _ = client.call_tool("agentloss_report")
    check("drafted manifest: oracle decisions", r["decisions"] == ORACLE_DECISIONS,
          str(r["decisions"]))
    check("drafted manifest: oracle error rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    check("drafted manifest: oracle loss", abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6,
          str(r["realized_loss_usd"]))
    d, _ = client.call_tool("agentloss_doctor")
    check("drafted manifest: doctor OK", d["ok"] and d["level"] == "ok", json.dumps(d))
    client.close()

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — `gateway init` drafts a manifest that recovers the oracle truth.")


if __name__ == "__main__":
    main()
