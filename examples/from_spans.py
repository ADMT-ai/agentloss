"""agentloss as the loss layer on top of existing tracing.

No re-instrumentation: your agent is already traced (Phoenix / Langfuse / Braintrust / OTel).
You add a few `agentloss.*` attributes to the consequential span; agentloss reads those spans
and produces the error rate + dollar loss.

Here the "spans" are synthetic dicts (the shape a platform client returns after parsing), and
ground truth comes from a stub verification agent (Tier A) — so we get a number with no
external labels wired.

    python examples/from_spans.py
"""
import random

from agentloss import ingest_spans, sample_and_verify, print_report


def make_spans(n=1000, seed=7):
    """Synthetic OpenInference-style decision spans carrying agentloss.* attributes."""
    rng = random.Random(seed)
    spans = []
    for i in range(n):
        bad = rng.random() < 0.03                      # ~3% should have been blocked
        spans.append({
            "name": "approve_payment",
            "attributes": {
                "openinference.span.kind": "AGENT",
                "agentloss.action": "approve",
                "agentloss.business_key": f"INV{i:05d}{'-BAD' if bad else ''}",
                "agentloss.value_at_risk_usd": round(rng.uniform(50, 20000), 2),
                "agentloss.use_case": "ap_3way_match",
                "agentloss.model": "claude-opus-4-x",
            },
        })
    return spans


def verify(decision):
    """Stub verification agent — re-adjudicates a decision. (Real one = an LLM + more evidence.)"""
    bad = decision.business_key.endswith("-BAD")
    return {
        "should_have_been": "reject" if bad else "approve",
        "confidence": 0.9,
        "estimated_loss": decision.value_at_risk_usd if bad else 0.0,
    }


if __name__ == "__main__":
    spans = make_spans()
    print(f"ingested {ingest_spans(spans)} decisions from spans")
    print(f"verified {sample_and_verify(verify, target_n=600)} sampled decisions (Tier A)")
    print_report()
