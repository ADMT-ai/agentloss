"""Unit tests for the gateway's pure pieces; the full proxy flow runs in
tests/test_evals.py via examples/gateway_eval.py (the oracle eval)."""
from agentloss.gateway import Manifest, _resolve, _result_data


def test_resolve_paths_and_literals():
    roots = {"arguments": {"amount": 12, "meta": {"cur": "eur"}},
             "result": {"items": [{"id": "a"}, {"id": "b"}]}}
    assert _resolve("arguments.amount", roots) == 12
    assert _resolve("arguments.meta.cur", roots) == "eur"
    assert _resolve("result.items.1.id", roots) == "b"
    assert _resolve("approve", roots) == "approve"          # literal
    assert _resolve("arguments.missing", roots) is None     # miss -> None
    assert _resolve("result.items.9.id", roots) is None     # bad index -> None


def test_result_data_prefers_structured_then_text_json():
    assert _result_data({"structuredContent": {"id": "x"},
                         "content": [{"type": "text", "text": "{\"id\": \"y\"}"}]}) == {"id": "x"}
    assert _result_data({"content": [{"type": "text", "text": "{\"id\": \"y\"}"}]}) == {"id": "y"}
    assert _result_data({"content": [{"type": "text", "text": "not json"}]}) is None
    assert _result_data("nope") is None


def test_manifest_defaults():
    m = Manifest({})
    assert m.use_case == "gateway" and m.tools == {} and m.outcomes == {}


def test_latest_rows_orders_numeric_ranks_numerically():
    from agentloss.gateway import Gateway
    gw = Gateway.__new__(Gateway)
    rows = [{"payment_id": "p1", "status": "lost", "revision": 9},
            {"payment_id": "p1", "status": "won", "revision": 10}]
    spec = {"business_key": "item.payment_id", "latest_by": "item.revision"}
    assert gw._latest_rows(rows, spec)[0]["status"] == "won"   # 10 > 9, not "9" > "10"


def test_latest_rows_final_verdict_beats_open_duplicate():
    from agentloss.gateway import Gateway
    gw = Gateway.__new__(Gateway)
    rows = [{"payment_id": "p1", "status": "lost", "amount": 500},
            {"payment_id": "p1", "status": "needs_response"}]
    spec = {"business_key": "item.payment_id", "status": "item.status",
            "error_statuses": ["lost"], "correct_statuses": ["won"]}
    assert gw._latest_rows(rows, spec)[0]["status"] == "lost"


def test_latest_rows_resolves_join_rooted_business_key():
    from agentloss.gateway import Gateway
    gw = Gateway.__new__(Gateway)
    rows = [{"case_id": "c1"}, {"case_id": "c2"}]
    spec = {"business_key": "join.payment_id",
            "join": {"left": "item.case_id", "right": "item.case_id"}}
    joined = {"c1": {"payment_id": "p1"}, "c2": {"payment_id": "p2"}}
    assert len(gw._latest_rows(rows, spec, joined)) == 2
