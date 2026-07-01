"""Unit tests for handle_event; the live HTTP flow runs in tests/test_evals.py via
examples/webhook_eval.py."""
from agentloss.core import STORE, Decision
from agentloss.webhook import handle_event

MAPPING = {
    "type": "event.type",
    "events": {"dispute.closed": {
        "business_key": "event.data.payment", "status": "event.data.status",
        "loss": "event.data.amount", "amount_divisor": 100,
        "error_statuses": ["lost"], "correct_statuses": ["won"],
        "source": "chargeback"}},
}


def _event(payment, status, amount=1000, etype="dispute.closed"):
    return {"type": etype, "data": {"payment": payment, "status": status, "amount": amount}}


def test_error_event_records_loss():
    r = handle_event(_event("p1", "lost", 12345), MAPPING)
    assert r == {"recorded": "p1", "ground_truth": "reject", "realized_loss_usd": 123.45}
    assert STORE.outcomes["p1"].source == "chargeback"


def test_correct_event_uses_decision_action():
    STORE.record(Decision(action="refund", value_at_risk_usd=1.0, business_key="p2",
                          use_case="t"))
    r = handle_event(_event("p2", "won"), MAPPING)
    assert r["ground_truth"] == "refund" and STORE.outcomes["p2"].realized_loss_usd == 0.0


def test_nonfinal_and_unknown_type_skip():
    assert "non-final" in handle_event(_event("p3", "under_review"), MAPPING)["skipped"]
    assert "no rule" in handle_event(_event("p4", "lost", etype="ping"), MAPPING)["skipped"]
    assert "p3" not in STORE.outcomes and "p4" not in STORE.outcomes


def test_missing_key_path_skips():
    r = handle_event({"type": "dispute.closed", "data": {"status": "lost"}}, MAPPING)
    assert "business_key" in r["skipped"]
