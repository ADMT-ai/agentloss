"""Unit tests for the importer's pure pieces; the CLI + oracle flow runs in
tests/test_evals.py via examples/import_eval.py."""
from agentloss.importer import map_rows, parse_money, suggest_mapping


def test_parse_money_formats():
    assert parse_money("$1,400.00") == 1400.0
    assert parse_money("€ 90,5") is None  # decimal-comma ambiguity -> refuse, don't guess
    assert parse_money("1400") == 1400.0
    assert parse_money(12) == 12.0
    assert parse_money("") is None and parse_money(None) is None
    assert parse_money("n/a") is None


def test_map_rows_status_contract():
    rows = [{"k": "A", "s": "lost", "amt": "100"},
            {"k": "B", "s": "won", "amt": "50"},
            {"k": "C", "s": "pending", "amt": "10"},
            {"k": "", "s": "lost", "amt": "5"}]
    outcomes, seen, skipped = map_rows(
        rows, {"business_key": "k", "status": "s", "loss": "amt"},
        error_statuses=["lost"], correct_statuses=["won"], source="chargeback")
    by_key = {o["business_key"]: o for o in outcomes}
    assert by_key["A"]["ground_truth"] == "reject" and by_key["A"]["realized_loss_usd"] == 100
    assert by_key["B"]["ground_truth"] == "approve" and by_key["B"]["realized_loss_usd"] == 0
    assert "C" not in by_key and "C" in seen        # non-final: skipped but census-excluded
    assert skipped == {"no_key": 1, "nonfinal": 1}


def test_map_rows_last_wins_and_divisor():
    rows = [{"k": "A", "s": "lost", "amt": "9000"},
            {"k": "A", "s": "won", "amt": "9000"}]
    outcomes, _, _ = map_rows(rows, {"business_key": "k", "status": "s", "loss": "amt"},
                              error_statuses=["lost"], correct_statuses=["won"],
                              amount_divisor=100)
    assert len(outcomes) == 1 and outcomes[0]["ground_truth"] == "approve"
    rows = [{"k": "B", "s": "lost", "amt": "9000"}]
    outcomes, _, _ = map_rows(rows, {"business_key": "k", "status": "s", "loss": "amt"},
                              error_statuses=["lost"], amount_divisor=100)
    assert outcomes[0]["realized_loss_usd"] == 90.0


def test_map_rows_all_errors_uses_decision_action():
    outcomes, _, _ = map_rows([{"k": "A", "amt": "5"}], {"business_key": "k", "loss": "amt"},
                              all_errors=True)
    assert outcomes[0]["ground_truth"] == "reject"


def test_suggest_mapping_heuristics():
    mapping, observed = suggest_mapping(
        ["invoice_no", "resolution", "amount", "notes"],
        [{"resolution": "lost"}, {"resolution": "won"}])
    assert mapping == {"business_key": "invoice_no", "status": "resolution", "loss": "amount"}
    assert observed == ["lost", "won"]

    mapping, _ = suggest_mapping(["id", "created"])
    assert mapping["business_key"].startswith("_todo") \
        and mapping["status"].startswith("_todo") and mapping["loss"].startswith("_todo")
