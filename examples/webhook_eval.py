"""Oracle eval for `agentloss listen` — the push outcome channel. Stripe-shaped dispute
events POSTed at the listener must land as gold outcomes and produce the exact oracle error
rate and dollar loss. Deterministic, loopback-only, no deps.

    python examples/webhook_eval.py   # -> PASS/FAIL per check; exits nonzero on any fail

Covers the contract, not a happy path: lost dispute (error, minor-unit divisor), won dispute
(correct — the decision's own action), non-final status (skipped, 200), unknown event type
(skipped, 200 — retries must settle), wrong/missing shared secret (401), malformed body
(400), health check, and the persisted store replaying to the oracle numbers out-of-process.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentloss.core import Decision, Store  # noqa: E402
from agentloss.persist import append_decision, load_store  # noqa: E402
from agentloss.webhook import serve  # noqa: E402
import agentloss  # noqa: E402

SECRET = "hook-secret-1"
MAPPING = {
    "type": "event.type",
    "events": {
        "charge.dispute.closed": {
            "business_key": "event.data.object.payment_intent",
            "status": "event.data.object.status",
            "loss": "event.data.object.amount",
            "amount_divisor": 100,
            "error_statuses": ["lost"],
            "correct_statuses": ["won"],
            "source": "chargeback",
        }
    },
}

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def post(url, payload, secret=SECRET, raw=None):
    req = urllib.request.Request(url, data=raw if raw is not None else
                                 json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if secret:
        req.add_header("X-Agentloss-Secret", secret)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def dispute(pi, status, amount_minor):
    return {"type": "charge.dispute.closed",
            "data": {"object": {"payment_intent": pi, "status": status,
                                "amount": amount_minor}}}


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_webhook_")
    store = os.path.join(tmp, "store.jsonl")
    # decisions as the agent side (SDK or gateway) would have persisted them
    seeded = Store()
    for i in range(5):
        append_decision(seeded.record(Decision(
            action="approve", value_at_risk_usd=100.0, business_key=f"pi_{i}",
            use_case="payments")), store)
    load_store(store)  # the listener process holds the decisions

    httpd = serve(MAPPING, store_path=store, port=0, secret=SECRET)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    code, r = post(url, dispute("pi_0", "lost", 140000))
    check("lost dispute -> error with divisor applied",
          code == 200 and r.get("recorded") == "pi_0" and r["realized_loss_usd"] == 1400.0,
          f"{code} {r}")
    code, r = post(url, dispute("pi_1", "won", 5000))
    check("won dispute -> correct, no loss",
          code == 200 and r.get("ground_truth") == "approve", f"{code} {r}")
    code, r = post(url, dispute("pi_2", "needs_response", 5000))
    check("non-final -> skipped with 200", code == 200 and "non-final" in r.get("skipped", ""),
          f"{code} {r}")
    code, r = post(url, {"type": "customer.created", "data": {}})
    check("unknown event type -> skipped with 200",
          code == 200 and "no rule" in r.get("skipped", ""), f"{code} {r}")
    code, r = post(url, dispute("pi_3", "lost", 100), secret="wrong")
    check("wrong secret -> 401, nothing recorded",
          code == 401 and "pi_3" not in agentloss.STORE.outcomes, f"{code} {r}")
    code, r = post(url, None, raw=b"{not json")
    check("malformed body -> 400", code == 400, f"{code} {r}")
    with urllib.request.urlopen(url + "healthz", timeout=10) as resp:
        check("healthz", resp.status == 200)
    httpd.shutdown()

    # out-of-process readout: fresh process state -> replay the JSONL -> oracle numbers
    agentloss.STORE.decisions.clear()
    agentloss.STORE.outcomes.clear()
    load_store(store)
    r = agentloss.report()
    check("replay: oracle loss", abs(r["realized_loss_usd"] - 1400.0) < 1e-6,
          str(r["realized_loss_usd"]))
    check("replay: 1 error / 2 resolved", abs(r["error_rate"] - 0.5) < 1e-9,
          str(r["error_rate"]))
    check("replay: decisions intact", r["decisions"] == 5, str(r["decisions"]))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the SoR pushes, the loss number updates in real time.")


if __name__ == "__main__":
    main()
