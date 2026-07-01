"""agentloss MCP server (stub).

Exposes tools a coding agent calls WHILE wiring the SDK, so the correct integration is
retrievable at generation time instead of guessed. Run:

    pip install mcp
    python mcp/agentloss_mcp.py
"""
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # keep the file importable without the dep
    raise SystemExit("Install the MCP SDK first: pip install mcp")

mcp = FastMCP("agentloss")

_ATTRS = {
    "value_at_risk_usd": "Financial exposure of THIS single action (e.g. the invoice amount). "
                         "Sets the per-decision sum insured and drives monetary-unit sampling.",
    "business_key": "A stable natural id (e.g. invoice number) that late-arriving outcomes can be "
                    "joined on. Must be unique per decision.",
    "in_envelope": "Whether the action was inside the declared operating envelope (ODD). "
                   "Out-of-envelope actions are excluded from coverage.",
    "ground_truth": "The resolved correct outcome, from a downstream correction, dispute, audit, "
                    "human review, or the verification agent.",
}


@mcp.tool()
def how_to_instrument(framework: str = "python") -> str:
    """Return the shortest correct way to instrument an agent's consequential action."""
    return (
        "Instrument ONLY the consequential action (the tool call that moves money or commits "
        "the business).\n\n"
        "from agentloss import decision, report_outcome, Decision\n\n"
        "@decision\n"
        "def approve_payment(invoice):\n"
        "    action = run_matching(invoice)   # 'approve'|'hold'|'reject'\n"
        "    return Decision(action=action, value_at_risk_usd=invoice.total,\n"
        "                    business_key=invoice.number, use_case='ap_3way_match')\n\n"
        "# when the outcome resolves:\n"
        "report_outcome(business_key='INV-1', ground_truth='duplicate-should-block',\n"
        "               source='recovery_audit', realized_loss_usd=14200)\n"
    )


@mcp.tool()
def how_to_gateway() -> str:
    """How to measure an agent with NO code changes: the MCP gateway (docs/GATEWAY.md)."""
    return (
        "If the agent already reaches its system of record over MCP (Stripe MCP, an ERP MCP), "
        "don't instrument code — put the agentloss gateway in front of that server:\n\n"
        "    agentloss gateway --manifest m.json --store .agentloss/store.jsonl -- <server cmd>\n\n"
        "The manifest declares the consequential tools (where the amount and business key "
        "live) and the reversal tool (disputes/credit-memos -> gold ground truth):\n\n"
        '    {"version": 1, "use_case": "payments",\n'
        '     "tools": {"create_payment": {"amount": "arguments.amount",\n'
        '                                  "business_key": "result.id"}},\n'
        '     "outcomes": {"list_disputes": {"items": "result.disputes",\n'
        '                                    "business_key": "item.payment_id",\n'
        '                                    "status": "item.status", "loss": "item.amount",\n'
        '                                    "error_statuses": ["lost"],\n'
        '                                    "correct_statuses": ["won"],\n'
        '                                    "source": "chargeback", "census": true}}}\n\n'
        "The gateway injects agentloss_report / agentloss_doctor / agentloss_sync_outcomes / "
        "agentloss_record_outcome into tools/list, so the agent reads its own error rate and "
        "dollar loss through the same connection. Readout out-of-process: `agentloss report "
        "--store <path>`. Works for any agent runtime (not only Python)."
    )


@mcp.tool()
def explain_attribute(name: str) -> str:
    """Explain an agentloss.* / Decision attribute."""
    return _ATTRS.get(name, f"Unknown attribute '{name}'. Known: {', '.join(_ATTRS)}")


@mcp.tool()
def validate_integration(store_path: str = "") -> str:
    """Run agentloss's real self-check and return structured findings.

    Inspects, in order: (1) the in-process store, (2) a persisted JSONL store — `store_path`,
    else $AGENTLOSS_STORE, else the gateway default `.agentloss/store.jsonl` — replayed via
    agentloss.load_store(). Catches the silent failures (outcomes reported but none sampled
    -> 0% rate; only error outcomes reported -> denominator collapse; realized loss on a
    source that won't be counted; no outcomes at all). Falls back to a static checklist only
    when there is no store anywhere to inspect."""
    import json
    import os
    try:
        from agentloss import STORE, load_store, validate_integration as _vi
        candidates = [p for p in (store_path, os.environ.get("AGENTLOSS_STORE"),
                                  os.path.join(".agentloss", "store.jsonl"))
                      if p and os.path.exists(p)]
        loaded = None
        if not STORE.decisions and candidates:
            load_store(candidates[0])
            loaded = candidates[0]
        result = _vi()
        if loaded:
            result["store"] = loaded
    except Exception as e:  # keep the tool importable / never crash the agent
        return f"Could not run agentloss.validate_integration(): {e!r}"
    if not result.get("checks") or result.get("level") == "fail" and all(
        c["id"] in ("decisions_present",) for c in result["checks"]
    ):
        result["note"] = (
            "No decisions in this process and no persisted store found. Pass store_path (or "
            "set AGENTLOSS_STORE) to a JSONL store written by the gateway/agentloss.persist, "
            "call agentloss.validate_integration() INSIDE the app, or shell out to `agentloss "
            "doctor --json --store <path>`. Static checklist: (1) only consequential actions "
            "wrapped with @decision; (2) every Decision sets a unique business_key + "
            "value_at_risk_usd; (3) report_outcome or record_outcomes wired to a ground-truth "
            "source; (4) no raw records leave the boundary."
        )
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
