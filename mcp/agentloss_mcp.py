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
    "source": "Where the outcome came from: recovery_audit | dispute | chargeback | refund | "
              "human_queue | verification_agent | inferred. The last two are SILVER: their "
              "dollars flow through expected loss, never realized.",
    "fidelity": "gold = looked-up/confirmed truth (realized dollars); silver = inferred, "
                "estimated, or machine-learned (expected dollars; bias-correctable via "
                "agentloss.calibrate).",
    "confidence": "The verifier/reasoner's own confidence in a silver verdict (0..1). 0.0 is a "
                  "real value (a self-declared guess), never coerced upward.",
    "estimated_loss_usd": "The silver dollar figure for an inferred/estimated outcome; feeds "
                          "expected loss. realized_loss_usd stays None until truth is gold.",
}

# The gateway manifest's outcome-spec fields (docs/GATEWAY.md). `gateway init` drafts each
# automatically when it probes the shape from real rows.
_MANIFEST_FIELDS = {
    "items": "Dotted path to the row array in the outcome tool's result (e.g. result.disputes).",
    "business_key": "Per-row path (item.*, or join.* after a join) naming the ORIGINAL "
                    "decision — the payment/invoice id, not the reversal's own id.",
    "status": "Per-row path to the resolution field for status-mode outcomes.",
    "error_statuses": "Status values meaning the decision was WRONG -> ground_truth=reject with "
                      "the row's loss. Unknown vocabularies are learned by init from the rows' "
                      "own free text (then marked fidelity: silver until reviewed).",
    "correct_statuses": "Status values meaning the decision stood. Rows matching neither list "
                        "are non-final: skipped and census-excluded.",
    "loss": "Per-row path to the dollar amount (item.amount, or join.amount after a join).",
    "loss_fallback": "\"value_at_risk\": when an error row carries no dollar, estimate the loss "
                     "at the decision's own exposure (silver, expected loss).",
    "mode": "\"infer\": rows carry free-text evidence instead of a status enum; the outcome is "
            "inferred from a marker vocabulary and the loss estimated. All verdicts silver.",
    "evidence": "Infer mode: per-row path(s) to the free-text field(s) to judge.",
    "error_markers": "Infer mode: override the resolution language meaning the decision was "
                     "wrong (defaults in agentloss.inference).",
    "correct_markers": "Infer mode: override the language meaning the decision stood.",
    "reasoner": "\"llm\": a reasoning agent judges the evidence instead of the marker "
                "vocabulary. Set AGENTLOSS_REASONER=path/to/file.py:fn; verdicts land under "
                "source verification_agent so agentloss.calibrate can bias-correct them.",
    "paginate": "{\"cursor\": \"result.next_cursor\", \"arg\": \"cursor\"}: follow the cursor "
                "to the end so page one alone never under-counts.",
    "join": "{\"tool\", \"items\", \"left\", \"right\"}: the dollar lives in a sibling read; "
            "the joined row is exposed under join.* paths.",
    "latest_by": "Per-row path ordering duplicated keys (appeal revisions); the greatest value "
                 "wins (numeric compared numerically, ISO timestamps as text).",
    "fidelity": "\"silver\": force this channel's outcomes to expected-loss accounting (e.g. a "
                "learned, not-yet-reviewed status vocabulary). Delete to promote to gold.",
    "census": "true: decisions appearing in NO reversal are marked correct, keeping the error "
              "rate's denominator honest. Enable only when the channel catches all errors.",
    "source": "The outcome source label; see explain_attribute('source').",
    "amount_divisor": "Divide row amounts (e.g. 100 for minor units / cents).",
    "arguments": "Fixed arguments to pass when sync calls the outcome tool.",
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
        "don't instrument code — put the agentloss gateway in front of that server. The "
        "no-hands loop (run all three yourself):\n\n"
        "    agentloss gateway init --out m.json -- <server cmd>     # onboard: draft manifest\n"
        "    agentloss gateway --manifest m.json --store .agentloss/store.jsonl -- <server cmd>\n"
        "    agentloss doctor --json --store .agentloss/store.jsonl  # verify the wiring\n\n"
        "(hosted servers: --url https://... --header 'Authorization: Bearer ...')\n\n"
        "The manifest declares the consequential tools (where the amount and business key "
        "live) and the outcome tool(s) — status enums are gold; free-text rows get "
        '"mode": "infer" (outcome inferred, loss estimated, recorded silver). Example:\n\n'
        '    {"version": 1, "use_case": "payments",\n'
        '     "tools": {"create_payment": {"amount": "arguments.amount",\n'
        '                                  "business_key": "result.id"}},\n'
        '     "outcomes": {"list_disputes": {"items": "result.disputes",\n'
        '                                    "business_key": "item.payment_id",\n'
        '                                    "status": "item.status", "loss": "item.amount",\n'
        '                                    "error_statuses": ["lost"],\n'
        '                                    "correct_statuses": ["won"],\n'
        '                                    "source": "chargeback", "census": true}}}\n\n'
        "Other outcome-spec fields init drafts when the shape needs them: paginate (cursors), "
        "join (dollar in a sibling read), latest_by (appeal revisions), reasoner (LLM judges "
        "prose), fidelity: silver (learned vocabularies) — explain_manifest_field(name) for "
        "each. The gateway injects agentloss_report / agentloss_doctor / "
        "agentloss_sync_outcomes / agentloss_record_outcome into tools/list, so the agent "
        "reads its own error rate and dollar loss through the same connection. Readout "
        "out-of-process: `agentloss report --store <path>`. Works for any agent runtime "
        "(not only Python)."
    )


@mcp.tool()
def how_to_onboard_sor() -> str:
    """The agentic onboarding runbook: connect ANY system of record's MCP server and get an
    error rate + dollar loss out, including when the SoR has no explicit outcome data."""
    return (
        "1. DRAFT — `agentloss gateway init --out m.json -- <server cmd>` (or --url ...). "
        "It reads the server's own tools/list, classifies money-movers, probes the outcome "
        "reads (reads are safe), and derives row paths from real data. It detects pagination, "
        "cross-tool joins, revision dedupe (latest_by), free-text outcomes (mode: infer), and "
        "unknown status vocabularies (learned from the rows' text, marked fidelity: silver). "
        "It emits a business_context block naming the domain, money-movers, and each outcome "
        "channel's mode — review it: that block IS the onboarding judgment.\n"
        "2. RESOLVE — fix every `_todo` in the draft (call the tool once, read the shape). "
        "Check business_key names the ORIGINAL decision, not the reversal's own id.\n"
        "3. RUN — `agentloss gateway --manifest m.json --store s.jsonl -- <server cmd>`; point "
        "the agent at the gateway instead of the server (same tools, plus agentloss_*).\n"
        "4. VERIFY — after some traffic, call the injected agentloss_doctor tool or "
        "`agentloss doctor --json --store s.jsonl`. It names the silent failures in plain "
        "language (0% rate, only-errors, uncounted dollars).\n"
        "5. DELIVER — call agentloss_sync_outcomes (pulls the SoR's reversals; follows "
        "cursors; executes joins; dedupes revisions; infers free-text outcomes), then "
        "agentloss_report: error rate with CI + realized and expected dollar loss.\n"
        "NO OUTCOME DATA? Free-text resolutions are inferred (loss estimated from the text, "
        "else the decision's value-at-risk). Prose beyond the marker vocabulary: set "
        "AGENTLOSS_REASONER=path.py:fn (an LLM reasoner file) — verdicts are silver and "
        "bias-corrected against a small gold budget via agentloss.calibrate. Silver dollars "
        "always flow through EXPECTED loss, never realized — the number stays honest."
    )


@mcp.tool()
def explain_manifest_field(name: str) -> str:
    """Explain a gateway-manifest outcome-spec field (docs/GATEWAY.md)."""
    return _MANIFEST_FIELDS.get(
        name, f"Unknown field '{name}'. Known: {', '.join(_MANIFEST_FIELDS)}")


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
