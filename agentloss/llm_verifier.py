"""Default verification agent (Tier A): an LLM re-adjudicates a decision.

So a user gets a number with no external labels *and* no hand-written verifier:

    import agentloss
    agentloss.sample_and_verify()            # uses Claude by default (needs agentloss[claude])

Or plug any LLM by passing a text-completion callable:

    v = agentloss.llm_verifier(complete=my_llm)   # my_llm(prompt:str) -> str
    agentloss.sample_and_verify(v)

The verifier judges the decision against its `context` (the agent's input/output, carried from
the span). Runs locally; only derived metrics leave. A verdict it can't parse falls back to
"the action was correct" (0 loss) so a flaky model never inflates the error rate.
"""
import json
import os

_PROMPT = """You are a verification auditor double-checking an AI agent's decision, with more
scrutiny than the agent had. Decide whether the agent's action was correct.

Use case: {use_case}
Agent action: {action}
Value at risk (USD): {var}
Context (the agent's input and output):
{context}

Respond ONLY with JSON:
{{"should_have_been": "<the correct action; equal to the agent's action if it was right>",
  "confidence": <number 0..1>,
  "estimated_loss": <USD lost if the action was wrong, else 0>}}"""


def _extract_json(text):
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in response")
    return json.loads(text[i:j + 1])


def _claude_complete(model=None):
    import anthropic  # requires: pip install "agentloss[claude]" + ANTHROPIC_API_KEY
    client = anthropic.Anthropic()
    m = model or os.environ.get("AGENTLOSS_VERIFIER_MODEL", "claude-sonnet-4-6")

    def complete(prompt):
        msg = client.messages.create(model=m, max_tokens=400,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text

    return complete


def llm_verifier(complete=None, model=None):
    """Return verify_fn(decision) -> {should_have_been, confidence, estimated_loss}."""
    complete = complete or _claude_complete(model)

    def verify(decision):
        prompt = _PROMPT.format(
            use_case=decision.use_case,
            action=decision.action,
            var=decision.value_at_risk_usd,
            context=(getattr(decision, "context", "") or "(none provided)")[:4000],
        )
        try:
            r = _extract_json(complete(prompt))
        except Exception:
            return {"should_have_been": decision.action, "confidence": 0.0, "estimated_loss": 0.0}
        return {
            "should_have_been": r.get("should_have_been", decision.action),
            "confidence": float(r.get("confidence", 0.5) or 0.5),
            "estimated_loss": float(r.get("estimated_loss", 0) or 0),
        }

    return verify
