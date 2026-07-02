"""Unit tests for the backfill mapping suggester (zero-config assessments)."""
from agentloss.backfill import suggest_backfill_mapping


def test_zendesk_shaped_header_maps_itself():
    rows = [{"Ticket Id": "T-1", "Refund Amount": "25.00", "Assignee": "fin-bot",
             "Resolution Notes": "goodwill credit applied after review",
             "Status": "solved", "Subject": "Refund request"}]
    mapping, notes = suggest_backfill_mapping(list(rows[0]), rows)
    assert mapping["business_key"] == "Ticket Id"
    assert mapping["amount"] == "Refund Amount"
    assert mapping["decider"] == "Assignee"
    assert mapping["evidence"] == "Resolution Notes"
    assert "status" not in mapping        # workflow status is NOT a ruling


def test_amount_must_parse_as_money_in_the_sample():
    rows = [{"conversation_id": "c1", "refund": "n/a", "credit_amount": "12.50",
             "body": "refund issued to the customer"}]
    mapping, _ = suggest_backfill_mapping(list(rows[0]), rows)
    assert mapping["amount"] == "credit_amount"   # "refund" ranked higher but not money


def test_qa_verdict_column_is_recognized_and_observed():
    rows = [{"ticket_id": "t1", "amount": "10.00", "qa_verdict": "upheld",
             "notes": "reviewed by QA"},
            {"ticket_id": "t2", "amount": "5.00", "qa_verdict": "correct",
             "notes": "reviewed by QA"}]
    mapping, notes = suggest_backfill_mapping(list(rows[0]), rows)
    assert mapping["status"] == "qa_verdict"
    assert any("upheld" in n and "correct" in n for n in notes)


def test_unresolvable_required_fields_come_back_as_todos():
    rows = [{"foo": "x", "bar": "y"}]
    mapping, _ = suggest_backfill_mapping(list(rows[0]), rows)
    assert mapping["business_key"].startswith("_todo")
    assert mapping["amount"].startswith("_todo")
