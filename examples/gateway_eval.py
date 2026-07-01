"""Oracle eval for the MCP gateway (docs/GATEWAY.md) — the house pattern: seed a system of
record with KNOWN errors, run an agent through the gateway, and assert agentloss recovers the
true error rate and dollar loss exactly. Deterministic, no network, no deps.

    python examples/gateway_eval.py    # -> PASS/FAIL per check; exits nonzero on any fail

Flow: scripted MCP client -> `agentloss gateway` (subprocess) -> mock SoR server (subprocess
of the gateway). The client creates payments (some destined to be disputed, per the mock's
oracle rule), makes non-consequential lookups, then asks for the measurement THROUGH THE SAME
CONNECTION: agentloss_sync_outcomes -> agentloss_report -> agentloss_doctor. Finally the
persisted JSONL store is replayed in this process (`agentloss.load_store`) and must give the
same numbers out-of-process.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "examples", "gateway", "payments.manifest.json")
MOCK = os.path.join(ROOT, "examples", "gateway", "mock_sor_server.py")

# (customer, amount): `-fraud` -> disputed LOST (an agent error, full loss);
# `-won` -> disputed WON (correct); `-pending` -> non-final (skipped); else undisputed correct.
PAYMENTS = [
    ("acme", 120.0), ("globex", 340.0), ("initech-fraud", 900.0), ("umbrella", 55.0),
    ("hooli-won", 210.0), ("stark", 75.0), ("wayne-fraud", 1400.0), ("cyberdyne", 60.0),
    ("tyrell-pending", 500.0), ("oscorp", 95.0),
]
ORACLE_ERRORS = 2
ORACLE_LOSS = 900.0 + 1400.0
ORACLE_DECISIONS = len(PAYMENTS)
# rate denominator = sampled approvals; the pending payment has no final outcome yet
ORACLE_RATE = ORACLE_ERRORS / (ORACLE_DECISIONS - 1)

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


class Client:
    """Minimal newline-delimited JSON-RPC client over a subprocess's pipes."""

    def __init__(self, argv):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        req = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.proc.stdin.write((json.dumps(req) + "\n").encode())
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("gateway closed the stream")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    def notify(self, method, params=None):
        self.proc.stdin.write((json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n").encode())
        self.proc.stdin.flush()

    def call_tool(self, name, arguments=None):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        for block in result.get("content") or []:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"]), result
                except ValueError:
                    pass
        return result.get("structuredContent"), result

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def main():
    store = os.path.join(tempfile.mkdtemp(prefix="agentloss_gw_"), "store.jsonl")
    client = Client([sys.executable, "-m", "agentloss.gateway",
                     "--manifest", MANIFEST, "--store", store,
                     "--", sys.executable, MOCK])

    init = client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "eval", "version": "0"}})
    check("initialize passes through", init["serverInfo"]["name"] == "mock-sor")
    client.notify("notifications/initialized")

    tools = {t["name"] for t in client.rpc("tools/list")["tools"]}
    check("downstream tools intact", {"create_payment", "lookup_customer",
                                      "list_disputes"} <= tools, str(tools))
    check("agentloss tools injected", {"agentloss_report", "agentloss_doctor",
                                       "agentloss_sync_outcomes",
                                       "agentloss_record_outcome"} <= tools, str(tools))

    for customer, amount in PAYMENTS:
        data, _ = client.call_tool("create_payment",
                                   {"amount": amount, "currency": "USD", "customer": customer})
        assert data["id"].startswith("pay_")
        client.call_tool("lookup_customer", {"customer": customer})  # non-consequential

    synced, _ = client.call_tool("agentloss_sync_outcomes")
    check("sync: oracle errors", synced["errors"] == ORACLE_ERRORS, str(synced))
    check("sync: won dispute correct", synced["correct"] == 1, str(synced))
    check("sync: pending skipped", synced["skipped_nonfinal"] == 1, str(synced))
    check("sync: census fills denominator",
          synced["census_correct"] == ORACLE_DECISIONS - ORACLE_ERRORS - 1 - 1, str(synced))

    r, _ = client.call_tool("agentloss_report")
    check("report: only consequential calls captured",
          r["decisions"] == ORACLE_DECISIONS, str(r["decisions"]))
    check("report: oracle error rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    check("report: oracle realized loss", abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6,
          str(r["realized_loss_usd"]))
    check("report: expected == realized (census)",
          abs(r["expected_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r["expected_loss_usd"]))

    d, _ = client.call_tool("agentloss_doctor")
    check("doctor: wiring OK through the connection", d["ok"] and d["level"] == "ok",
          json.dumps(d))

    client.close()

    # out-of-process readout: replay the persisted store in THIS process
    import agentloss
    loaded = agentloss.load_store(store)
    check("store: decisions persisted", loaded["decisions"] == ORACLE_DECISIONS, str(loaded))
    r2 = agentloss.report()
    check("store: replay matches oracle loss",
          abs(r2["realized_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r2["realized_loss_usd"]))
    check("store: replay matches oracle rate",
          abs(r2["error_rate"] - ORACLE_RATE) < 1e-9, str(r2["error_rate"]))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the gateway recovers the oracle truth at the MCP boundary.")


if __name__ == "__main__":
    main()
