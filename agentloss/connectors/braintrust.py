"""Braintrust connector — write agentloss loss/verdict back as span feedback (scores).

⚠️ Built to the Braintrust docs; NOT yet live-verified (unlike the Phoenix connector).

Braintrust is logging/experiment-oriented, so reading production spans programmatically goes
through BTQL rather than a simple dataframe. This connector focuses on the clear, differentiating
half — the write-back — via `log_feedback(id=span_id, scores=..., metadata=...)`. Supply the
`business_key -> span_id` map from your own logging (Braintrust returns span ids when you log),
or adapt `read_decisions()` to your BTQL query.

Install: pip install "agentloss[braintrust]"

    import agentloss
    from agentloss.connectors import braintrust as bt
    # ... you already captured decisions (e.g. via ingest_spans / @decision) and have key_to_span
    agentloss.sample_and_verify()
    bt.write_back(key_to_span, project="my-agent")   # scores -> Braintrust UI
    agentloss.print_report()

The pure mapping (`feedback_rows`) is offline-tested; only write_back touches Braintrust.
"""
from ..core import STORE


def feedback_rows(key_to_span):
    """Build Braintrust feedback payloads from captured outcomes (pure — no Braintrust)."""
    rows = []
    for key, o in STORE.outcomes.items():
        span_id = key_to_span.get(key)
        if not span_id:
            continue
        is_err = o.ground_truth != "approve"
        loss = o.realized_loss_usd if o.realized_loss_usd is not None else (o.estimated_loss_usd or 0.0)
        rows.append({
            "id": span_id,
            "scores": {"agentloss_error": 1.0 if is_err else 0.0},
            "metadata": {
                "agentloss_loss_usd": float(loss or 0.0),
                "agentloss_should_have_been": o.ground_truth,
                "agentloss_source": o.source,
            },
        })
    return rows


def write_back(key_to_span, project=None):
    """Write per-decision loss/verdict as Braintrust feedback (shown in the UI)."""
    import braintrust
    logger = braintrust.init_logger(project=project) if project else braintrust.init_logger()
    rows = feedback_rows(key_to_span)
    for r in rows:
        logger.log_feedback(id=r["id"], scores=r["scores"], metadata=r["metadata"])
    logger.flush()
    return len(rows)
