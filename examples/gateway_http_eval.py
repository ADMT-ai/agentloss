"""Oracle eval for the gateway's HTTP transport — the same truth-recovery bar as the stdio
eval, but against a REMOTE (Streamable HTTP) MCP server. Deterministic, loopback-only, no deps.

    python examples/gateway_http_eval.py   # -> PASS/FAIL per check; exits nonzero on any fail

The mock HTTP SoR server (examples/gateway/mock_sor_http_server.py) is deliberately strict:
it assigns an Mcp-Session-Id on initialize and 400s any request that doesn't echo it, and it
answers tools/call as text/event-stream — so this eval proves the gateway's session handling
and SSE parsing, not merely a happy path. The agent-facing flow and the oracle are identical
to examples/gateway_eval.py: known disputes seeded, payments driven through the gateway
(`--url`), then sync -> report -> doctor through the same connection.
"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "examples"))
sys.path.insert(0, os.path.join(ROOT, "examples", "gateway"))
from gateway_eval import (Client, ORACLE_DECISIONS, ORACLE_ERRORS, ORACLE_LOSS, ORACLE_RATE,
                          PAYMENTS)  # noqa: E402
from mock_sor_http_server import serve  # noqa: E402

MANIFEST = os.path.join(ROOT, "examples", "gateway", "payments.manifest.json")

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def main():
    httpd = serve(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
    store = os.path.join(tempfile.mkdtemp(prefix="agentloss_http_"), "store.jsonl")

    client = Client([sys.executable, "-m", "agentloss.gateway",
                     "--manifest", MANIFEST, "--store", store, "--url", url])
    init = client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "eval", "version": "0"}})
    check("initialize over HTTP", init["serverInfo"]["name"] == "mock-sor")
    check("server assigned a session", httpd.session_id is not None)
    client.notify("notifications/initialized")

    tools = {t["name"] for t in client.rpc("tools/list")["tools"]}
    check("session id echoed (strict server accepted tools/list)",
          "create_payment" in tools, str(tools))
    check("agentloss tools injected over HTTP", "agentloss_report" in tools, str(tools))

    for customer, amount in PAYMENTS:
        data, _ = client.call_tool("create_payment",
                                   {"amount": amount, "currency": "USD", "customer": customer})
        assert data["id"].startswith("pay_")   # tools/call rides the SSE parse path
        client.call_tool("lookup_customer", {"customer": customer})

    synced, _ = client.call_tool("agentloss_sync_outcomes")
    check("sync over HTTP: oracle errors", synced["errors"] == ORACLE_ERRORS, str(synced))
    r, _ = client.call_tool("agentloss_report")
    check("report: oracle decisions", r["decisions"] == ORACLE_DECISIONS, str(r["decisions"]))
    check("report: oracle error rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    check("report: oracle realized loss", abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6,
          str(r["realized_loss_usd"]))
    d, _ = client.call_tool("agentloss_doctor")
    check("doctor OK over HTTP", d["ok"] and d["level"] == "ok", json.dumps(d))
    client.close()
    httpd.shutdown()

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the gateway recovers the oracle truth against a remote (HTTP) server.")


if __name__ == "__main__":
    main()
