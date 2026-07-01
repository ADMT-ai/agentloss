import agentloss
from agentloss import Decision, decision, record_outcomes, report, report_outcome
from agentloss.core import STORE


def _approve(key, amount):
    @decision
    def act():
        return Decision(action="approve", value_at_risk_usd=amount,
                        business_key=key, use_case="test")
    return act()


def test_decision_decorator_records():
    d = _approve("K-1", 100.0)
    assert d.decision_id.startswith("d_")
    assert STORE.decisions["K-1"] is d


def test_report_outcome_is_census_by_default():
    _approve("K-1", 100.0)
    report_outcome("K-1", ground_truth="reject", source="chargeback",
                   realized_loss_usd=100.0)
    o = STORE.outcomes["K-1"]
    assert o.sampled and o.pi == 1.0


def test_record_outcomes_batch_and_pairs():
    _approve("K-1", 10.0)
    _approve("K-2", 20.0)
    n = record_outcomes([
        {"business_key": "K-1", "ground_truth": "reject", "source": "chargeback",
         "realized_loss_usd": 10.0},
        ("K-2", {"ground_truth": "approve", "source": "dispute"}),
    ])
    assert n == 2 and set(STORE.outcomes) == {"K-1", "K-2"}


def test_report_recovers_known_rate_and_loss():
    for i in range(10):
        _approve(f"K-{i}", 50.0)
    record_outcomes(
        [{"business_key": "K-0", "ground_truth": "reject", "source": "chargeback",
          "realized_loss_usd": 50.0, "estimated_loss_usd": 50.0},
         {"business_key": "K-1", "ground_truth": "reject", "source": "chargeback",
          "realized_loss_usd": 50.0, "estimated_loss_usd": 50.0}]
        + [{"business_key": f"K-{i}", "ground_truth": "approve", "source": "dispute",
            "realized_loss_usd": 0.0} for i in range(2, 10)])
    r = report()
    assert r["decisions"] == 10
    assert abs(r["error_rate"] - 0.2) < 1e-9
    assert abs(r["realized_loss_usd"] - 100.0) < 1e-9
    lo, hi = r["error_rate_ci"]
    assert lo <= 0.2 <= hi


def test_public_api_surface():
    for name in agentloss.__all__:
        assert getattr(agentloss, name, None) is not None, name
