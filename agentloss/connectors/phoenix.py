"""Arize Phoenix connector — read decision spans, write loss/verdict annotations back.

agentloss rides the tracing you already run: your agent is traced with OpenInference/OTel and
lands in Phoenix; you set a few `agentloss.*` attributes on the consequential span; agentloss
reads those spans, computes the error rate + dollar loss, and writes the result back as span
annotations that show up in the Phoenix UI.

Install:  pip install "agentloss[phoenix]"       (arize-phoenix-client + pandas)
Endpoint: defaults to http://localhost:6006

    from agentloss.connectors import phoenix as ph
    import agentloss

    n, key_to_span = ph.read_decisions(project="my-agent")   # ingest agentloss.* spans
    agentloss.sample_and_verify(my_verify_fn)                 # Tier A (or push report_outcome)
    ph.write_back(key_to_span)                                # annotations -> Phoenix UI
    agentloss.print_report()                                  # error rate + dollar loss

The DataFrame<->agentloss mapping (`_row_to_span`, `annotation_rows`) is pure and unit-tested
offline; only `read_decisions`/`write_back` touch a live Phoenix.
"""
from ..core import STORE
from ..spans import A_ACTION, A_KEY, ingest_spans

_ATTR_PREFIX = "attributes."


def _row_to_span(row):
    """A Phoenix span row (dict) -> ({'attributes': {agentloss.*}}, span_id) or (None, None)."""
    attrs = {}
    for col, val in row.items():
        if isinstance(col, str) and col.startswith(_ATTR_PREFIX + "agentloss."):
            attrs[col[len(_ATTR_PREFIX):]] = val
    if A_ACTION not in attrs or A_KEY not in attrs:
        return None, None
    span_id = row.get("context.span_id") or row.get("span_id")
    return {"attributes": attrs}, span_id


def annotation_rows(key_to_span):
    """Build annotation rows from captured outcomes (pure — no pandas/phoenix)."""
    rows = []
    for key, o in STORE.outcomes.items():
        sid = key_to_span.get(key)
        if sid is None:
            continue
        is_err = o.ground_truth != "approve"
        loss = o.realized_loss_usd if o.realized_loss_usd is not None else (o.estimated_loss_usd or 0.0)
        rows.append({
            "span_id": sid,
            "label": "error" if is_err else "ok",
            "score": float(loss or 0.0),
            "explanation": f"agentloss: should_have_been={o.ground_truth}, source={o.source}",
        })
    return rows


def read_decisions(project=None, endpoint=None, limit=5000):
    """Pull spans from Phoenix, ingest agentloss decisions. Returns (count, business_key->span_id)."""
    from phoenix.client import Client
    client = Client(base_url=endpoint) if endpoint else Client()
    df = client.spans.get_spans_dataframe(project_identifier=project, limit=limit)
    if df is None or len(df) == 0:
        return 0, {}
    spans, key_to_span = [], {}
    for row in df.reset_index().to_dict("records"):
        span, sid = _row_to_span(row)
        if span is None:
            continue
        spans.append(span)
        key_to_span[span["attributes"][A_KEY]] = sid
    return ingest_spans(spans), key_to_span


def write_back(key_to_span, annotation_name="agentloss", endpoint=None):
    """Write per-decision loss/verdict back as Phoenix span annotations (shown in the UI)."""
    import pandas as pd
    from phoenix.client import Client
    rows = annotation_rows(key_to_span)
    if not rows:
        return 0
    df = pd.DataFrame(rows).set_index("span_id")
    client = Client(base_url=endpoint) if endpoint else Client()
    client.spans.log_span_annotations_dataframe(
        dataframe=df, annotation_name=annotation_name, annotator_kind="CODE")
    return len(rows)
