"""Offline tests for the Langfuse + Braintrust connector mapping logic (no servers/keys).

    python examples/connectors_offline_test.py
"""
from agentloss import STORE, Decision, report_outcome
from agentloss.connectors import braintrust as bt
from agentloss.connectors import langfuse as lf


def _seed():
    STORE.decisions.clear(); STORE.outcomes.clear()
    STORE.record(Decision(action="approve", value_at_risk_usd=1000, business_key="INV1"))
    STORE.record(Decision(action="approve", value_at_risk_usd=2000, business_key="INV2"))
    report_outcome("INV1", ground_truth="approve", source="verification_agent",
                   fidelity="silver", estimated_loss_usd=0.0)
    report_outcome("INV2", ground_truth="reject", source="verification_agent",
                   fidelity="silver", estimated_loss_usd=2000.0)


def test_langfuse():
    md = {"agentloss.action": "approve", "agentloss.business_key": "INV1",
          "agentloss.value_at_risk_usd": 1000, "other": "ignored"}
    assert lf._obs_to_span(md)["attributes"]["agentloss.action"] == "approve"
    assert lf._obs_to_span({"foo": "bar"}) is None
    _seed()
    rows = lf.score_rows({"INV1": {"trace_id": "t1", "observation_id": "o1"},
                          "INV2": {"trace_id": "t2", "observation_id": "o2"}})
    by = {r["observation_id"]: r for r in rows}
    assert by["o2"]["error"] == 1.0 and by["o2"]["loss"] == 2000.0
    assert by["o1"]["error"] == 0.0 and by["o1"]["loss"] == 0.0


def test_braintrust():
    _seed()
    rows = bt.feedback_rows({"INV1": "s1", "INV2": "s2"})
    by = {r["id"]: r for r in rows}
    assert by["s2"]["scores"]["agentloss_error"] == 1.0
    assert by["s2"]["metadata"]["agentloss_loss_usd"] == 2000.0
    assert by["s1"]["scores"]["agentloss_error"] == 0.0


if __name__ == "__main__":
    test_langfuse()
    test_braintrust()
    print("langfuse + braintrust connector offline logic: OK")
