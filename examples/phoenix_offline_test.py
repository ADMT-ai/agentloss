"""Offline unit test of the Phoenix connector's pure mapping logic (no Phoenix/pandas needed).

    python examples/phoenix_offline_test.py
"""
from agentloss import STORE, Decision, report_outcome
from agentloss.connectors import phoenix as ph


def test_row_to_span():
    rows = [
        # a consequential agentloss decision span (as df.reset_index().to_dict('records') yields)
        {"context.span_id": "s1", "name": "approve_payment",
         "attributes.openinference.span.kind": "AGENT",
         "attributes.agentloss.action": "approve",
         "attributes.agentloss.business_key": "INV1",
         "attributes.agentloss.value_at_risk_usd": 1000.0},
        # a non-decision span -> ignored
        {"context.span_id": "s2", "name": "llm", "attributes.openinference.span.kind": "LLM"},
    ]
    span, sid = ph._row_to_span(rows[0])
    assert span["attributes"]["agentloss.action"] == "approve"
    assert span["attributes"]["agentloss.business_key"] == "INV1"
    assert sid == "s1"
    assert ph._row_to_span(rows[1]) == (None, None)


def test_annotation_rows():
    STORE.decisions.clear(); STORE.outcomes.clear()
    STORE.record(Decision(action="approve", value_at_risk_usd=1000.0, business_key="INV1", use_case="ap"))
    report_outcome("INV1", ground_truth="reject", source="verification_agent",
                   fidelity="silver", estimated_loss_usd=1000.0)
    rows = ph.annotation_rows({"INV1": "s1"})
    assert len(rows) == 1
    assert rows[0] == {"span_id": "s1", "label": "error", "score": 1000.0,
                       "explanation": "agentloss: should_have_been=reject, source=verification_agent"}


if __name__ == "__main__":
    test_row_to_span()
    test_annotation_rows()
    print("phoenix connector offline logic: OK")
