"""Unit tests for the init heuristics; the full draft->run proof lives in
examples/gateway_init_eval.py (run via tests/test_evals.py)."""
import glob
import json
import os

from agentloss.gateway import Manifest
from agentloss.gateway_init import _is_money_mover, _is_reversal_read, draft_manifest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool(name, props=None, required=None):
    return {"name": name, "inputSchema": {"type": "object", "properties": props or {},
                                          "required": required or []}}


def test_money_mover_heuristics():
    assert _is_money_mover(_tool("create_payment", {"amount": {"type": "number"}}))
    assert _is_money_mover(_tool("send_invoice"))           # verb+noun, no amount prop
    assert _is_money_mover(_tool("submit_order", {"total": {"type": "number"}}))
    assert not _is_money_mover(_tool("list_payments"))      # read prefix wins
    assert not _is_money_mover(_tool("get_charge"))
    assert not _is_money_mover(_tool("create_label"))       # commit verb, no money signal


def test_reversal_read_heuristics():
    assert _is_reversal_read(_tool("list_disputes"))
    assert _is_reversal_read(_tool("get_credit_memos"))
    assert not _is_reversal_read(_tool("create_refund"))    # a money-mover, not a read
    assert not _is_reversal_read(_tool("list_customers"))


def test_draft_without_probe_marks_todos():
    m = draft_manifest([_tool("create_payment", {"amount": {"type": "number"},
                                                 "currency": {"type": "string"}}),
                        _tool("list_disputes")], use_case="x", call=None)
    assert m["tools"]["create_payment"]["amount"] == "arguments.amount"
    assert m["tools"]["create_payment"]["currency"] == "arguments.currency"
    out = m["outcomes"]["list_disputes"]
    assert "_todo" in out["items"] and out["error_statuses"] == ["_todo"]


def test_minor_units_detected_from_description():
    m = draft_manifest([_tool("create_refund", {
        "amount": {"type": "integer",
                   "description": "Amount in cents (smallest currency unit)."}})], call=None)
    assert m["tools"]["create_refund"]["amount_divisor"] == 100


def test_probe_derives_row_paths():
    def call(name, arguments=None):
        rows = [{"payment_id": "p1", "status": "lost", "amount": 10.0},
                {"payment_id": "p2", "status": "won", "amount": 5.0}]
        return {"content": [{"type": "text", "text": json.dumps({"disputes": rows})}]}

    m = draft_manifest([_tool("list_disputes")], call=call)
    out = m["outcomes"]["list_disputes"]
    assert out["items"] == "result.disputes"
    assert out["business_key"] == "item.payment_id"
    assert out["error_statuses"] == ["lost"] and out["correct_statuses"] == ["won"]


def test_shipped_manifests_load_and_are_well_formed():
    for path in glob.glob(os.path.join(ROOT, "manifests", "*.manifest.json")):
        m = Manifest.load(path)
        assert m.tools, path
        for name, spec in m.tools.items():
            assert isinstance(spec.get("business_key"), str), (path, name)
            assert "_todo" not in json.dumps(spec), (path, name)
        for name, spec in m.outcomes.items():
            for field in ("items", "business_key", "status", "loss"):
                assert isinstance(spec.get(field), str), (path, name, field)
            assert spec.get("error_statuses"), (path, name)
            assert "_todo" not in json.dumps(spec), (path, name)


def test_infer_mode_drafted_for_text_only_rows():
    def call(name, arguments=None):
        rows = [{"payment_id": "p1", "note": "chargeback lost — funds clawed back"},
                {"payment_id": "p2", "note": "dispute resolved in merchant favor"}]
        return {"content": [{"type": "text", "text": json.dumps({"cases": rows})}]}

    m = draft_manifest([_tool("list_case_notes")], call=call)
    out = m["outcomes"]["list_case_notes"]
    assert out["mode"] == "infer" and out["source"] == "inferred"
    assert out["evidence"] == ["item.note"]
    assert out["loss_fallback"] == "value_at_risk" and "loss" not in out
    assert m["business_context"]["outcome_basis"] == "inferred from free text"


def test_unknown_vocabulary_learned_from_row_text():
    def call(name, arguments=None):
        rows = [{"payment_id": "p1", "status": "MERCHANT_DEBIT", "amount": 10.0,
                 "summary": "chargeback lost — funds clawed back"},
                {"payment_id": "p2", "status": "CONSUMER_CLAIM_DENIED", "amount": 5.0,
                 "summary": "dispute resolved in merchant favor"},
                {"payment_id": "p3", "status": "IN_ARBITRATION", "amount": 7.0,
                 "summary": "case open, awaiting evidence"}]
        return {"content": [{"type": "text", "text": json.dumps({"disputes": rows})}]}

    m = draft_manifest([_tool("list_disputes")], call=call)
    out = m["outcomes"]["list_disputes"]
    assert out.get("mode", "status") == "status"            # execution stays gold
    assert out["error_statuses"] == ["MERCHANT_DEBIT"]
    assert out["correct_statuses"] == ["CONSUMER_CLAIM_DENIED"]
    assert "_learned_statuses" in out                        # declared, not silent


def test_ambiguous_learned_status_lands_in_neither():
    # the same status carries error text on one row, correct text on another —
    # trusting either side would be a lie, so it must stay non-final
    def call(name, arguments=None):
        rows = [{"payment_id": "p1", "status": "CLOSED",
                 "summary": "chargeback lost — funds clawed back"},
                {"payment_id": "p2", "status": "CLOSED",
                 "summary": "dispute resolved in merchant favor"},
                {"payment_id": "p3", "status": "SETTLED_MERCHANT_FAULT",
                 "summary": "complaint upheld, refund issued"}]
        return {"content": [{"type": "text", "text": json.dumps({"disputes": rows})}]}

    m = draft_manifest([_tool("list_disputes")], call=call)
    out = m["outcomes"]["list_disputes"]
    assert out["error_statuses"] == ["SETTLED_MERCHANT_FAULT"]
    assert "CLOSED" not in out["error_statuses"] + out["correct_statuses"]
