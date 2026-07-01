"""Ingest OpenTelemetry / OpenInference spans into agentloss Decisions.

The integration contract with the ecosystem: instrument your consequential action as an
OTel/OpenInference span (as Phoenix, Langfuse, Braintrust already do) and set these span
attributes on it — no re-instrumentation with a second SDK:

    agentloss.action              "approve" | "hold" | "reject" | ...   (required)
    agentloss.business_key        stable id outcomes can be joined on   (required)
    agentloss.value_at_risk_usd   financial exposure of this action     (recommended)
    agentloss.use_case            short slug                            (optional)
    agentloss.model               foundation model / adaptation id      (optional)

Then point agentloss at your spans — a live OTel exporter, a Phoenix/Langfuse pull, or an
OTLP/JSON export. agentloss reads what your tracer already emits and adds the loss/outcome
layer on top; results can be written back as scores on the same spans.

Spans here are dicts with a flat `attributes` map (the shape platform clients return after
parsing). Raw OTLP JSON (attributes as a key/value list) should be flattened first.
"""
from .core import Decision, STORE

A_ACTION = "agentloss.action"
A_KEY = "agentloss.business_key"
A_VAR = "agentloss.value_at_risk_usd"
A_USECASE = "agentloss.use_case"
A_MODEL = "agentloss.model"
A_CONTEXT = "agentloss.context"


def _attrs(span):
    if isinstance(span, dict):
        return span.get("attributes") or {}
    return getattr(span, "attributes", {}) or {}


def decision_from_span(span):
    """Return a Decision if the span is a consequential agentloss decision, else None."""
    a = _attrs(span)
    action, key = a.get(A_ACTION), a.get(A_KEY)
    if action is None or key is None:
        return None
    try:
        var = float(a.get(A_VAR, 0) or 0)
    except (TypeError, ValueError):
        var = 0.0
    ctx = a.get(A_CONTEXT)
    if not ctx:  # fall back to OpenInference input/output as the verifier's evidence
        ctx = "\n".join(f"{k}: {a[k]}" for k in ("input.value", "output.value") if a.get(k))
    return Decision(
        action=str(action),
        value_at_risk_usd=var,
        business_key=str(key),
        use_case=a.get(A_USECASE, "default"),
        model=a.get(A_MODEL, "unknown"),
        context=str(ctx or ""),
    )


def ingest_spans(spans):
    """Read an iterable of OTel/OpenInference spans; record each agentloss decision.

    Returns the number of decisions ingested."""
    n = 0
    for s in spans:
        d = decision_from_span(s)
        if d is not None:
            STORE.record(d)
            n += 1
    return n
