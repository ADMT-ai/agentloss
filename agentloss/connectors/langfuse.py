"""Langfuse connector — read decision observations, write loss/verdict scores back.

⚠️ Built to the Langfuse docs; NOT yet live-verified (unlike the Phoenix connector). Expect the
same kind of small API mismatches we found + fixed for Phoenix on first real run.

Put `agentloss.*` fields in the observation (or trace) metadata on your consequential step:
    metadata = {"agentloss.action": "approve", "agentloss.business_key": inv_no,
                "agentloss.value_at_risk_usd": total, "agentloss.context": "..."}

Install: pip install "agentloss[langfuse]"

    import agentloss
    from agentloss.connectors import langfuse as lf
    n, key_to_ref = lf.read_decisions()        # ingest agentloss.* observations
    agentloss.sample_and_verify()              # Tier A (or push report_outcome)
    lf.write_back(key_to_ref)                   # create_score() -> Langfuse UI
    agentloss.print_report()

The pure mapping (`_obs_to_span`, `score_rows`) is offline-tested; only read/write touch Langfuse.
"""
from ..core import STORE
from ..spans import A_ACTION, A_KEY, ingest_spans


def _obs_to_span(metadata):
    """A Langfuse observation's metadata dict -> {'attributes': {agentloss.*}} or None."""
    if not isinstance(metadata, dict):
        return None
    attrs = {k: v for k, v in metadata.items()
             if isinstance(k, str) and k.startswith("agentloss.")}
    if A_ACTION not in attrs or A_KEY not in attrs:
        return None
    return {"attributes": attrs}


def score_rows(key_to_ref):
    """Build score payloads from captured outcomes (pure — no Langfuse)."""
    rows = []
    for key, o in STORE.outcomes.items():
        ref = key_to_ref.get(key)
        if not ref:
            continue
        is_err = o.ground_truth != "approve"
        loss = o.realized_loss_usd if o.realized_loss_usd is not None else (o.estimated_loss_usd or 0.0)
        rows.append({
            "trace_id": ref.get("trace_id"),
            "observation_id": ref.get("observation_id"),
            "error": 1.0 if is_err else 0.0,
            "loss": float(loss or 0.0),
            "comment": f"agentloss: should_have_been={o.ground_truth}, source={o.source}",
        })
    return rows


def read_decisions(limit=5000, **get_many_kwargs):
    """Fetch observations, ingest agentloss decisions. Returns (count, business_key->ref)."""
    from langfuse import Langfuse
    client = Langfuse()
    obs = client.api.observations.get_many(limit=limit, **get_many_kwargs).data
    spans, key_to_ref = [], {}
    for o in obs:
        span = _obs_to_span(getattr(o, "metadata", None) or {})
        if span is None:
            continue
        spans.append(span)
        key_to_ref[str(span["attributes"][A_KEY])] = {"trace_id": o.trace_id, "observation_id": o.id}
    return ingest_spans(spans), key_to_ref


def write_back(key_to_ref):
    """Write per-decision loss + error as Langfuse scores (shown in the UI)."""
    from langfuse import Langfuse
    client = Langfuse()
    rows = score_rows(key_to_ref)
    for r in rows:
        client.create_score(name="agentloss.loss", value=r["loss"], data_type="NUMERIC",
                            trace_id=r["trace_id"], observation_id=r["observation_id"], comment=r["comment"])
        client.create_score(name="agentloss.error", value=r["error"], data_type="NUMERIC",
                            trace_id=r["trace_id"], observation_id=r["observation_id"])
    client.flush()
    return len(rows)
