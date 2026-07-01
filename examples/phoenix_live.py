"""Run agentloss over decision spans in a live Phoenix: read -> verify -> write back -> report.

    pip install "agentloss[phoenix]"       # Phoenix running + spans emitted (phoenix_emit_spans.py)
    # optional real verifier: pip install "agentloss[claude]" and set ANTHROPIC_API_KEY
    python examples/phoenix_live.py

Then open http://localhost:6006 and look for `agentloss` annotations (loss/verdict) on the
decision spans, alongside the printed error-rate + dollar-loss report.
"""
import os

import agentloss
from agentloss.connectors import phoenix as ph


def heuristic_verify(decision):
    """No-API-key verifier: flag decisions whose context marks a duplicate."""
    bad = "DUPLICATE" in (decision.context or "")
    return {"should_have_been": "reject" if bad else "approve",
            "confidence": 0.9, "estimated_loss": decision.value_at_risk_usd if bad else 0.0}


if __name__ == "__main__":
    project = os.environ.get("PHOENIX_PROJECT", "agentloss-demo")
    n, key_to_span = ph.read_decisions(project=project)
    print(f"ingested {n} decisions from Phoenix project '{project}'")
    # None -> default Claude verifier (needs agentloss[claude] + ANTHROPIC_API_KEY)
    verify = None if os.environ.get("ANTHROPIC_API_KEY") else heuristic_verify
    agentloss.sample_and_verify(verify)
    print(f"wrote {ph.write_back(key_to_span)} annotations back to Phoenix (see the UI)")
    agentloss.print_report()
