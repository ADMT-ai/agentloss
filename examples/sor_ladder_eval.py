"""Oracle eval for the synthetic SoR ladder — the WHOLE agentic loop, per rung.

Every system of record writes its outcomes differently; the ladder proves the same loop
(onboard -> execute -> deliver) recovers the same oracle truth as the SoR gets messier:

    level 0 — explicit status enum + amount   -> gold outcomes, realized dollars
    level 1 — free-text note, amount column   -> INFERRED outcomes, explicit loss (silver)
    level 2 — free-text note only             -> inferred outcomes, ESTIMATED loss
                                                 (parsed from the text, else value-at-risk)
    level 3 — unknown status vocabulary       -> onboarding LEARNS the mapping from the
                                                 rows' own text; execution runs status
                                                 mode — gold, realized dollars again
    level 4 — paginated outcome read          -> the cursor is detected at onboarding
                                                 and followed to the end at sync; page
                                                 one alone would under-count
    level 5 — outcome split across two tools  -> the case list carries the verdict, a
                                                 sibling read carries the dollar; the
                                                 join is discovered and executed

Per level, with zero hand-written config:
1. **Onboard**: `agentloss gateway init` against the seeded server; assert it understood
   the business (domain, money-mover, outcome channel + mode) from the server itself.
2. **Execute**: a scripted agent drives payments through the gateway under the DRAFTED
   manifest, unedited.
3. **Deliver**: sync + report + doctor through the same connection; assert the recovered
   error rate and dollar loss match the oracle exactly — realized dollars at level 0,
   expected (estimated) dollars at levels 1-2, silver fidelity on every inferred row.

    python examples/sor_ladder_eval.py    # -> PASS/FAIL per check; exits nonzero on fail
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "examples"))
from gateway_eval import Client  # noqa: E402

SERVER = os.path.join(ROOT, "examples", "gateway", "sor_ladder_server.py")

# The oracle (suffix rule lives in the server): -fraud = error, full loss; -partial =
# error, 40% lost; -won / -contested = disputed but correct; -pending = non-final.
PAYMENTS = [
    ("acme", 120.0), ("globex", 340.0), ("initech-fraud", 900.0), ("umbrella", 55.0),
    ("hooli-won", 210.0), ("stark", 75.0), ("wayne-partial", 500.0), ("cyberdyne", 60.0),
    ("tyrell-pending", 800.0), ("oscorp-contested", 95.0),
]
ORACLE_ERRORS = 2
ORACLE_LOSS = 900.0 + 0.4 * 500.0
ORACLE_DECISIONS = len(PAYMENTS)
ORACLE_CORRECT = 2          # won + contested resolve in the agent's favor
ORACLE_NONFINAL = 1
ORACLE_CENSUS = ORACLE_DECISIONS - ORACLE_ERRORS - ORACLE_CORRECT - ORACLE_NONFINAL
ORACLE_RATE = ORACLE_ERRORS / (ORACLE_DECISIONS - ORACLE_NONFINAL)

OUTCOME_TOOLS = {0: "list_disputes", 1: "list_resolution_notes", 2: "list_case_notes",
                 3: "list_dispute_settlements", 4: "list_disputes",
                 5: "list_return_cases"}
GOLD_LEVELS = (0, 3, 4, 5)  # rungs whose execution yields gold, realized dollars

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def onboard(level, tmp):
    """Stage 1 — draft the manifest from the seeded server; assert the understanding."""
    manifest_path = os.path.join(tmp, f"l{level}.manifest.json")
    proc = subprocess.run(
        [sys.executable, "-m", "agentloss.gateway", "init", "--out", manifest_path,
         "--", sys.executable, SERVER, "--level", str(level), "--seed"],
        capture_output=True, text=True, timeout=60)
    check(f"L{level} onboard: init exits 0", proc.returncode == 0, proc.stderr)
    with open(manifest_path) as f:
        m = json.load(f)

    ctx = m.get("business_context", {})
    check(f"L{level} onboard: domain understood", ctx.get("domain") == "payments",
          json.dumps(ctx))
    check(f"L{level} onboard: use_case from domain", m.get("use_case") == "payments",
          json.dumps(m.get("use_case")))
    check(f"L{level} onboard: money-mover classified",
          ctx.get("money_movers") == ["create_payment"], json.dumps(ctx))

    tool = OUTCOME_TOOLS[level]
    out = m["outcomes"].get(tool, {})
    check(f"L{level} onboard: outcome channel found", bool(out), json.dumps(m["outcomes"]))
    mode = "status" if level in GOLD_LEVELS else "infer"
    check(f"L{level} onboard: channel mode = {mode}", out.get("mode", "status") == mode,
          json.dumps(out))
    check(f"L{level} onboard: join key probed", out.get("business_key") == "item.payment_id",
          json.dumps(out))
    if level in (0, 4, 5):
        check(f"L{level} onboard: statuses mapped",
              out.get("error_statuses") == ["lost"] and out.get("correct_statuses") == ["won"],
              json.dumps(out))
    elif level in (1, 2):
        check(f"L{level} onboard: evidence = the note", out.get("evidence") == ["item.note"],
              json.dumps(out))
    if level == 1:
        check("L1 onboard: explicit loss column kept", out.get("loss") == "item.amount",
              json.dumps(out))
    if level == 2:
        check("L2 onboard: loss falls back to value-at-risk",
              out.get("loss_fallback") == "value_at_risk" and "loss" not in out,
              json.dumps(out))
    if level == 3:
        check("L3 onboard: unknown vocabulary LEARNED from the rows' text",
              out.get("error_statuses") == ["MERCHANT_DEBIT", "MERCHANT_DEBIT_PARTIAL"]
              and out.get("correct_statuses") == ["CONSUMER_CLAIM_DENIED"],
              json.dumps(out))
        check("L3 onboard: learning is declared, not silent",
              "_learned_statuses" in out, json.dumps(out))
        channel = next((c for c in ctx.get("outcome_channels", [])
                        if c.get("tool") == tool), {})
        check("L3 onboard: business_context marks the vocabulary learned",
              channel.get("vocabulary") == "learned", json.dumps(ctx))
    if level == 4:
        # mapping both statuses REQUIRES following pages: page one carries only errors
        check("L4 onboard: pagination detected and declared",
              out.get("paginate") == {"cursor": "result.next_cursor", "arg": "cursor"},
              json.dumps(out))
    if level == 5:
        # the rows carry case_id AND payment_id: the business key must be the one that
        # joins back to the decisions, and the dollar must come from the sibling read
        check("L5 onboard: sibling read NOT mistaken for an outcome channel",
              "list_settlement_amounts" not in m["outcomes"], json.dumps(m["outcomes"]))
        check("L5 onboard: join discovered",
              out.get("join", {}).get("tool") == "list_settlement_amounts"
              and out["join"].get("left") == "item.case_id"
              and out["join"].get("right") == "item.case_id",
              json.dumps(out))
        check("L5 onboard: loss taken from the joined row",
              out.get("loss") == "join.amount", json.dumps(out))
    return manifest_path


def execute_and_deliver(level, manifest_path, tmp):
    """Stages 2+3 — run the agent under the drafted manifest; read the number back."""
    store = os.path.join(tmp, f"l{level}.store.jsonl")
    client = Client([sys.executable, "-m", "agentloss.gateway",
                     "--manifest", manifest_path, "--store", store,
                     "--", sys.executable, SERVER, "--level", str(level)])
    client.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                              "clientInfo": {"name": "eval", "version": "0"}})
    client.notify("notifications/initialized")
    for customer, amount in PAYMENTS:
        client.call_tool("create_payment",
                         {"amount": amount, "currency": "USD", "customer": customer})
        client.call_tool("lookup_customer", {"customer": customer})  # non-consequential

    synced, _ = client.call_tool("agentloss_sync_outcomes")
    check(f"L{level} deliver: oracle errors", synced["errors"] == ORACLE_ERRORS, str(synced))
    check(f"L{level} deliver: channel-correct outcomes",
          synced["correct"] == ORACLE_CORRECT, str(synced))
    check(f"L{level} deliver: non-final skipped",
          synced["skipped_nonfinal"] == ORACLE_NONFINAL, str(synced))
    check(f"L{level} deliver: census fills denominator",
          synced["census_correct"] == ORACLE_CENSUS, str(synced))
    check(f"L{level} deliver: inferred count",
          synced["inferred"] == (0 if level in GOLD_LEVELS
                                 else ORACLE_ERRORS + ORACLE_CORRECT),
          str(synced))

    r, _ = client.call_tool("agentloss_report")
    check(f"L{level} deliver: only consequential captured",
          r["decisions"] == ORACLE_DECISIONS, str(r["decisions"]))
    check(f"L{level} deliver: oracle error rate", abs(r["error_rate"] - ORACLE_RATE) < 1e-9,
          f"{r['error_rate']} vs {ORACLE_RATE}")
    if level in GOLD_LEVELS:
        check(f"L{level} deliver: oracle realized loss (gold)",
              abs(r["realized_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r["realized_loss_usd"]))
    else:
        check(f"L{level} deliver: inferred dollars are EXPECTED loss",
              abs(r["expected_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r["expected_loss_usd"]))
        check(f"L{level} deliver: no realized dollars claimed",
              abs(r["realized_loss_usd"]) < 1e-9, str(r["realized_loss_usd"]))

    d, _ = client.call_tool("agentloss_doctor")
    check(f"L{level} deliver: doctor OK", d["ok"] and d["level"] == "ok", json.dumps(d))
    client.close()
    return store


def check_silver_semantics(store):
    """The honesty contract on the hardest rung: every inferred row is silver, its loss
    estimated (never realized), and the estimate's basis is visible in the numbers."""
    rows = [json.loads(l) for l in open(store) if l.strip()]
    outcomes = {r["business_key"]: r for r in rows if r["type"] == "outcome"}
    # decision keys are pay_N in creation order — map them back to the payment list
    keys = [r["business_key"] for r in rows if r["type"] == "decision"]
    cust = {keys[i]: PAYMENTS[i][0] for i in range(len(keys))}
    fraud = next(k for k, c in cust.items() if c.endswith("-fraud"))
    partial = next(k for k, c in cust.items() if c.endswith("-partial"))
    o_fraud, o_partial = outcomes.get(fraud, {}), outcomes.get(partial, {})
    check("L2 silver: fraud row inferred silver", o_fraud.get("fidelity") == "silver",
          json.dumps(o_fraud))
    check("L2 silver: fraud loss estimated at value-at-risk",
          o_fraud.get("realized_loss_usd") is None
          and abs((o_fraud.get("estimated_loss_usd") or 0) - 900.0) < 1e-6,
          json.dumps(o_fraud))
    check("L2 silver: partial loss parsed from the note text",
          o_partial.get("realized_loss_usd") is None
          and abs((o_partial.get("estimated_loss_usd") or 0) - 200.0) < 1e-6,
          json.dumps(o_partial))
    check("L2 silver: confidence below certainty",
          0 < (o_fraud.get("confidence") or 0) < 1.0, json.dumps(o_fraud))


def main():
    tmp = tempfile.mkdtemp(prefix="agentloss_ladder_")
    silver_store = None
    for level in sorted(OUTCOME_TOOLS):
        manifest_path = onboard(level, tmp)
        store = execute_and_deliver(level, manifest_path, tmp)
        if level == 2:
            silver_store = store
            check_silver_semantics(store)

    # out-of-process readout of the estimated-loss rung: replay the persisted store here
    import agentloss
    from agentloss.core import STORE
    STORE.decisions.clear()
    STORE.outcomes.clear()
    loaded = agentloss.load_store(silver_store)
    check("store: decisions persisted", loaded["decisions"] == ORACLE_DECISIONS, str(loaded))
    r2 = agentloss.report()
    check("store: replay matches oracle expected loss",
          abs(r2["expected_loss_usd"] - ORACLE_LOSS) < 1e-6, str(r2["expected_loss_usd"]))
    check("store: replay matches oracle rate",
          abs(r2["error_rate"] - ORACLE_RATE) < 1e-9, str(r2["error_rate"]))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the same loop recovers the same oracle truth up the whole ladder.")


if __name__ == "__main__":
    main()
