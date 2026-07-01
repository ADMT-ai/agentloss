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
