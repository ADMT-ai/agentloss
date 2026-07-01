"""End-to-end agentloss on a live Phoenix instance.

Prereqs:
  pip install "agentloss[phoenix]"
  # Phoenix running (e.g. `phoenix serve` at http://localhost:6006)
  # your agent traced with OpenInference, and the consequential span carrying agentloss.* attrs:
  #   span.set_attribute("agentloss.action", "approve")
  #   span.set_attribute("agentloss.business_key", invoice_no)
  #   span.set_attribute("agentloss.value_at_risk_usd", invoice_total)

    python examples/phoenix_live.py
"""
import agentloss
from agentloss.connectors import phoenix as ph


def verify(decision):
    """Verification agent (Tier A). Replace with an LLM that re-adjudicates with more evidence.

    Return {should_have_been, confidence, estimated_loss}. If you already have real outcomes,
    push them with agentloss.report_outcome(...) instead of sampling+verifying."""
    return {"should_have_been": decision.action, "confidence": 0.5, "estimated_loss": 0.0}


if __name__ == "__main__":
    n, key_to_span = ph.read_decisions(project="my-agent")
    print(f"ingested {n} decisions from Phoenix")
    agentloss.sample_and_verify(verify)
    print(f"wrote {ph.write_back(key_to_span)} annotations back to Phoenix (see the UI)")
    agentloss.print_report()
