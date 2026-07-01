"""Oracle eval for the FULL no-hands hosted loop: `gateway init --url` drafts a manifest
from a remote (Streamable HTTP) MCP server, and that draft — zero edits — measures the truth
through the HTTP gateway. Deterministic, loopback-only, no deps.

    python examples/gateway_init_http_eval.py   # -> PASS/FAIL per check; exits nonzero on fail

The mock hosted server is the strict one (session-id enforced with a 400, tools/call served
as SSE), so the probe path itself proves session handling and stream parsing. Stage 1 drafts
against a seeded server (real dispute history, as a live SoR has); stage 2 runs the drafted
manifest via `gateway --url` against a fresh server and asserts the oracle numbers.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "examples"))
sys.path.insert(0, os.path.join(ROOT, "examples", "gateway"))
from gateway_eval import (Client, ORACLE_DECISIONS, ORACLE_ERRORS, ORACLE_LOSS, ORACLE_RATE,
                          PAYMENTS)  # noqa: E402
from mock_sor_http_server import serve  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def _start(seed):
    httpd = serve(port=0, seed=seed)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/mcp"


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_init_http_")
    manifest_path = os.path.join(tmp, "drafted.manifest.json")

    # -- stage 1: draft from the hosted server (with history)
    seeded, seeded_url = _start(seed=True)
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.gateway", "init", "--out", manifest_path,
         "--use-case", "payments", "--url", seeded_url],
        capture_output=True, text=True, timeout=60)
    seeded.shutdown()
    check("init --url exits 0", proc.returncode == 0, proc.stderr)
    with open(manifest_path) as f:
        m = json.load(f)
    check("money-mover drafted over HTTP", "create_payment" in m.get("tools", {}),
          json.dumps(m.get("tools", {})))
    out = m.get("outcomes", {}).get("list_disputes", {})
    check("reversal probed over HTTP (SSE + session)",
          out.get("items") == "result.disputes"
          and out.get("business_key") == "item.payment_id"
          and out.get("error_statuses") == ["lost"]
          and out.get("correct_statuses") == ["won"], json.dumps(out))
    check("no _todo left for the mock", "_todo" not in json.dumps(
        {"tools": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                   for k, v in m["tools"].items()},
         "outcomes": m["outcomes"]}), json.dumps(m))

    # -- stage 2: the draft measures the truth through the HTTP gateway
    fresh, fresh_url = _start(seed=False)
    store = os.path.join(tmp, "store.jsonl")
    client = Client([sys.executable, "-m", "agentloss.gateway",
                     "--manifest", manifest_path, "--store", store, "--url", fresh_url])
    client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                              "clientInfo": {"name": "eval", "version": "0"}})
    client.notify("notifications/initialized")
    for customer, amount in PAYMENTS:
        client.call_tool("create_payment",
                         {"amount": amount, "currency": "USD", "customer": customer})
    synced, _ = client.call_tool("agentloss_sync_outcomes")
    check("hosted no-hands loop: oracle errors", synced["errors"] == ORACLE_ERRORS, str(synced))
    r, _ = client.call_tool("agentloss_report")
    check("hosted no-hands loop: oracle decisions", r["decisions"] == ORACLE_DECISIONS,
          str(r["decisions"]))
    check("hosted no-hands loop: oracle rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    check("hosted no-hands loop: oracle loss", abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6,
          str(r["realized_loss_usd"]))
    client.close()
    fresh.shutdown()

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — URL in, dollar-loss numbers out: no code, no hand-written config.")


if __name__ == "__main__":
    main()
