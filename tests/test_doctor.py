from agentloss import Decision, doctor, report_outcome, validate_integration
from agentloss.core import STORE


def _approve(key, amount=10.0):
    STORE.record(Decision(action="approve", value_at_risk_usd=amount,
                          business_key=key, use_case="test"))


def _by_id(result):
    return {f["id"]: f["level"] for f in result["findings"]}


def test_empty_store_fails():
    r = doctor()
    assert not r["ok"] and _by_id(r)["decisions_present"] == "fail"


def test_no_outcomes_fails():
    _approve("K-1")
    r = doctor()
    assert not r["ok"] and _by_id(r)["outcomes_present"] == "fail"


def test_only_errors_warns_denominator_collapse():
    _approve("K-1")
    _approve("K-2")
    report_outcome("K-1", ground_truth="reject", source="chargeback",
                   realized_loss_usd=10.0)
    r = doctor()
    assert _by_id(r)["correct_outcomes_present"] == "warn"


def test_uncounted_loss_source_warns():
    _approve("K-1")
    report_outcome("K-1", ground_truth="reject", source="verification_agent",
                   realized_loss_usd=10.0)
    assert _by_id(doctor())["loss_source_counts"] == "warn"


def test_healthy_wiring_is_ok():
    _approve("K-1")
    _approve("K-2")
    report_outcome("K-1", ground_truth="reject", source="chargeback",
                   realized_loss_usd=10.0)
    report_outcome("K-2", ground_truth="approve", source="dispute",
                   realized_loss_usd=0.0)
    r = validate_integration()
    assert r["ok"] and r["level"] == "ok" and r["failures"] == 0
