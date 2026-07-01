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
def explain_attribute(name: str) -> str:
    """Explain an agentloss.* / Decision attribute."""
    return _ATTRS.get(name, f"Unknown attribute '{name}'. Known: {', '.join(_ATTRS)}")


@mcp.tool()
def validate_integration(repo_path: str = ".") -> str:
    """Run agentloss's self-check on the current process and return structured findings.

    Calls agentloss.validate_integration(), which inspects the in-process store and catches
    the silent failures (outcomes reported but none sampled -> 0% rate; only error outcomes
    reported -> denominator collapse; realized loss on a source that won't be counted; no
    outcomes at all). Falls back to a static checklist if the store is empty (e.g. the tool
    runs in a fresh process, separate from the app that holds the decisions)."""
    import json
    try:
        from agentloss import validate_integration as _vi
        result = _vi()
    except Exception as e:  # keep the tool importable / never crash the agent
        return f"Could not run agentloss.validate_integration(): {e!r}"
    if not result.get("checks") or result.get("level") == "fail" and all(
        c["id"] in ("decisions_present",) for c in result["checks"]
    ):
        result["note"] = (
            "Store empty in this process — decisions/outcomes live in the running app. Call "
            "agentloss.validate_integration() INSIDE the app, or shell out to `agentloss doctor "
            "--json`. Static checklist: (1) only consequential actions wrapped with @decision; "
            "(2) every Decision sets a unique business_key + value_at_risk_usd; (3) report_outcome "
            "or record_outcomes wired to a ground-truth source; (4) no raw records leave the boundary."
        )
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
