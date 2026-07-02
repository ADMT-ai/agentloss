"""Unit tests for agentloss.inference — infer the outcome, estimate the loss."""
from agentloss.inference import infer_outcome, infer_outcomes, parse_money


def test_error_marker_infers_reject():
    v = infer_outcome("chargeback lost — funds clawed back from merchant", loss=80.0)
    assert v["ground_truth"] == "reject"
    assert v["estimated_loss_usd"] == 80.0
    assert v["loss_basis"] == "explicit"


def test_correct_marker_infers_approve_with_zero_loss():
    v = infer_outcome("dispute resolved in merchant favor — charge stands")
    assert v["ground_truth"] == "approve"
    assert v["estimated_loss_usd"] == 0.0


def test_no_marker_is_nonfinal():
    v = infer_outcome("case open, awaiting customer evidence", value_at_risk=500.0)
    assert v["ground_truth"] is None
    assert v["confidence"] == 0.0


def test_last_marker_wins_when_both_sides_match():
    # error language early, resolution language last -> the conclusion wins
    v = infer_outcome("customer says they were wrongly charged; complaint dismissed")
    assert v["ground_truth"] == "approve"
    assert v["confidence"] < 0.9  # both sides matched -> less sure
    v = infer_outcome("complaint dismissed at first; on appeal, complaint upheld")
    assert v["ground_truth"] == "reject"


def test_loss_parsed_from_text_beats_value_at_risk():
    v = infer_outcome("complaint upheld in part — refunded $1,200.50 to customer",
                      value_at_risk=5000.0)
    assert v["ground_truth"] == "reject"
    assert v["estimated_loss_usd"] == 1200.50
    assert v["loss_basis"] == "parsed"


def test_loss_falls_back_to_value_at_risk():
    v = infer_outcome("fraudulent charge confirmed; full amount refunded",
                      value_at_risk=900.0)
    assert v["estimated_loss_usd"] == 900.0
    assert v["loss_basis"] == "value_at_risk"
    assert v["confidence"] <= 0.7  # a bound, not a read


def test_no_loss_information_estimates_zero():
    v = infer_outcome("billed in error")
    assert v["ground_truth"] == "reject"
    assert v["estimated_loss_usd"] == 0.0
    assert v["loss_basis"] is None


def test_custom_markers_override_defaults():
    v = infer_outcome("order kaputt", error_markers=["kaputt"], correct_markers=["prima"])
    assert v["ground_truth"] == "reject"
    v = infer_outcome("alles prima", error_markers=["kaputt"], correct_markers=["prima"])
    assert v["ground_truth"] == "approve"


def test_parse_money_requires_currency_marker():
    assert parse_money("refunded $1,400.00 in full") == 1400.0
    assert parse_money("refunded USD 90.50") == 90.50
    assert parse_money("ticket 1400 escalated") is None  # a number is not money
    assert parse_money("") is None


def test_batch_shape_is_silver_and_skips_nonfinal():
    rows = infer_outcomes([
        ("k1", "chargeback lost", 100.0),
        ("k2", "case open, awaiting evidence", 50.0),
        ("k3", "no merchant error"),
    ])
    assert [r["business_key"] for r in rows] == ["k1", "k3"]
    assert all(r["fidelity"] == "silver" for r in rows)
    assert rows[0]["ground_truth"] == "reject"
    assert rows[0]["estimated_loss_usd"] == 100.0
    assert rows[1]["ground_truth"] == "approve"
