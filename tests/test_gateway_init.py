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
