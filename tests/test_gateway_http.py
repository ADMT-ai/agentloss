"""Unit tests for the HTTP downstream's pure pieces; the full remote flow runs in
tests/test_evals.py via examples/gateway_http_eval.py (the oracle eval)."""
import io
import urllib.error

from agentloss.gateway_http import HttpDownstream, parse_sse


def _stream(text):
    return io.BytesIO(text.encode())


def test_parse_sse_single_and_multi_event():
    events = list(parse_sse(_stream(
        'event: message\ndata: {"a": 1}\n\n'
        ': a comment\nid: 7\ndata: {"b": 2}\n\n')))
    assert events == [{"a": 1}, {"b": 2}]


def test_parse_sse_multiline_data_and_trailing_event():
    events = list(parse_sse(_stream('data: {"a":\ndata:  1}\n\ndata: {"b": 2}')))
    assert events == [{"a": 1}, {"b": 2}]


def test_parse_sse_skips_bad_json():
    assert list(parse_sse(_stream("data: not json\n\ndata: 3\n\n"))) == [3]


def test_transport_error_shapes():
    err = HttpDownstream._transport_error(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call"},
        urllib.error.HTTPError("u", 401, "unauthorized", {}, None))
    assert err["id"] == 4 and "HTTP 401" in err["error"]["message"]
    # notifications and responses get no synthesized reply
    assert HttpDownstream._transport_error({"method": "notifications/x"}, OSError()) is None
    assert HttpDownstream._transport_error({"id": 4, "result": {}}, OSError()) is None


def test_send_ignores_garbage_without_spawning():
    ds = HttpDownstream("http://example.invalid/mcp")
    ds.start(lambda m, raw=None: (_ for _ in ()).throw(AssertionError("dispatched")))
    ds.send(b"not json\n")
    ds.send(b"42\n")  # not a dict/list message
