"""Streamable-HTTP downstream for the gateway — remote MCP servers (mcp.stripe.com, hosted
ERP servers) behind the same interception. Zero dependencies: stdlib urllib.

Speaks the MCP Streamable HTTP transport from the client side: every JSON-RPC message is a
POST to the server URL; the response is either `application/json` (one message or a batch)
or `text/event-stream` (a stream of messages); notifications come back 202 with no body.
The `Mcp-Session-Id` returned by the initialize response is echoed on every later request,
and the negotiated `MCP-Protocol-Version` is sent once known. Auth (e.g. a bearer token)
rides on `--header`.

Requests run on a thread each, so a slow tool call doesn't stall the relay; JSON-RPC ids
keep the correlation. Sends that race the initialize round-trip wait for the session id
first. A transport failure on a request is surfaced to the agent as a JSON-RPC error
response — never a crash, and never a fabricated business result.

Not yet spoken: the optional server-opened GET/SSE channel (server-initiated requests).
Reversal syncs and tool results all flow on POST responses, which covers the SoR servers
the gateway targets today.
"""
import json
import threading
import urllib.error
import urllib.request

__all__ = ["HttpDownstream", "parse_sse"]


def parse_sse(stream):
    """Yield JSON-decoded `data:` payloads from a text/event-stream byte stream."""
    data_lines = []
    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data_lines:
                try:
                    yield json.loads("\n".join(data_lines))
                except ValueError:
                    pass
                data_lines = []
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        # event:/id:/retry:/comment lines are irrelevant here
    if data_lines:
        try:
            yield json.loads("\n".join(data_lines))
        except ValueError:
            pass


class HttpDownstream:
    """Downstream half of the gateway over MCP Streamable HTTP."""

    def __init__(self, url, headers=None, timeout=60):
        self.url = url
        self.extra_headers = dict(headers or {})
        self.timeout = timeout
        self.session_id = None
        self.protocol_version = None
        self._on_msg = None
        self._init_inflight = False
        self._init_done = threading.Event()

    def start(self, on_msg):
        self._on_msg = on_msg

    def close(self):
        pass  # sessions expire server-side; nothing to tear down locally

    def send(self, data):
        if isinstance(data, bytes):
            try:
                msg = json.loads(data)
            except ValueError:
                return
        else:
            msg = data
        if not isinstance(msg, (dict, list)):
            return
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            self._init_inflight = True
        threading.Thread(target=self._post, args=(msg,), daemon=True).start()

    # ---- one POST round trip

    def _post(self, msg):
        is_init = isinstance(msg, dict) and msg.get("method") == "initialize"
        if not is_init and self._init_inflight:
            self._init_done.wait(self.timeout)  # session id must exist before we can echo it
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        if self.protocol_version:
            req.add_header("MCP-Protocol-Version", self.protocol_version)
        for name, value in self.extra_headers.items():
            req.add_header(name, value)

        messages = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                ctype = resp.headers.get("Content-Type", "")
                if "text/event-stream" in ctype:
                    messages = list(parse_sse(resp))
                elif resp.status != 202:
                    body = resp.read()
                    if body.strip():
                        payload = json.loads(body)
                        messages = payload if isinstance(payload, list) else [payload]
        except Exception as e:
            messages = [self._transport_error(m, e) for m in
                        (msg if isinstance(msg, list) else [msg])]
            messages = [m for m in messages if m is not None]
        finally:
            if is_init:
                for m in messages:
                    version = (m.get("result") or {}).get("protocolVersion") \
                        if isinstance(m, dict) else None
                    if version:
                        self.protocol_version = version
                self._init_done.set()
        for m in messages:
            self._on_msg(m, None)

    @staticmethod
    def _transport_error(request_msg, exc):
        """A JSON-RPC error response for a failed request; None for a notification."""
        if not isinstance(request_msg, dict) or request_msg.get("id") is None \
                or "method" not in request_msg:
            return None
        detail = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else repr(exc)
        return {"jsonrpc": "2.0", "id": request_msg["id"],
                "error": {"code": -32000,
                          "message": f"agentloss gateway: downstream transport failed "
                                     f"({detail})"}}
