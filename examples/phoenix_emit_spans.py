"""Seed a running Phoenix with synthetic AP decision spans, so you can try agentloss
end-to-end without building an agent.

Each span carries `agentloss.*` attributes; ~4% are "bad" (should have been rejected),
flagged in `agentloss.context` so a verifier can catch them.

    pip install arize-phoenix
    phoenix serve                       # http://localhost:6006
    python examples/phoenix_emit_spans.py
"""
import os
import random

from opentelemetry import trace
from phoenix.otel import register


def main(n=500, project=None, endpoint=None):
    project = project or os.environ.get("PHOENIX_PROJECT", "agentloss-demo")
    endpoint = endpoint or os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")
    tp = register(project_name=project, endpoint=endpoint)   # wire OTel -> Phoenix
    tracer = trace.get_tracer("agentloss-demo")
    rng = random.Random(7)
    for i in range(n):
        bad = rng.random() < 0.04
        with tracer.start_as_current_span("approve_payment") as span:
            span.set_attribute("openinference.span.kind", "AGENT")
            span.set_attribute("input.value", f"invoice INV{i:05d} from Acme, 3-way match")
            span.set_attribute("output.value", "approve")
            span.set_attribute("agentloss.action", "approve")
            span.set_attribute("agentloss.business_key", f"INV{i:05d}")
            span.set_attribute("agentloss.value_at_risk_usd", round(rng.uniform(50, 20000), 2))
            span.set_attribute("agentloss.use_case", "ap_3way_match")
            span.set_attribute("agentloss.context",
                               "DUPLICATE of a prior invoice" if bad else "clean 3-way match")
    tp.force_flush()
    print(f"emitted {n} decision spans to Phoenix project '{project}' ({endpoint})")


if __name__ == "__main__":
    main()
