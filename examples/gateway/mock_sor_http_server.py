"""Streamable-HTTP flavor of the mock SoR server, for the gateway's HTTP-transport eval.

Same tools and oracle dispute rule as mock_sor_server.py (it delegates to its `handle`),
served the way a hosted MCP server serves them:

- every JSON-RPC message is a POST to /mcp
- `initialize` responses carry an `Mcp-Session-Id` header; every later request MUST echo it
  (enforced with a 400 — proving the gateway's session handling, not just tolerating it)
- `tools/call` responses come back as `text/event-stream` (exercising the gateway's SSE
  parser); everything else as `application/json`; notifications as 202 with no body

Standalone: `python mock_sor_http_server.py [--seed] [--port N]` (prints the port, serves
until killed). In-process: `serve(port=0, seed=False)` returns the ThreadingHTTPServer.
"""
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_sor_server as sor  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, body=b"", content_type=None, session=None):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        if self.path != "/mcp":
            return self._reply(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            msg = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._reply(400, b"bad json", "text/plain")

        method = msg.get("method")
        session = None
        if method == "initialize":
            self.server.session_id = session = uuid.uuid4().hex
        elif self.server.session_id and \
                self.headers.get("Mcp-Session-Id") != self.server.session_id:
            return self._reply(400, b"missing or wrong Mcp-Session-Id", "text/plain")

        resp = sor.handle(msg)
        if resp is None:  # notification
            return self._reply(202)
        body = json.dumps(resp).encode()
        if method == "tools/call":
            sse = b"event: message\ndata: " + body + b"\n\n"
            return self._reply(200, sse, "text/event-stream")
        return self._reply(200, body, "application/json", session=session)


def serve(port=0, seed=False):
    if seed:
        sor.seed()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.session_id = None
    return httpd


def main():
    port = 0
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    httpd = serve(port=port, seed="--seed" in sys.argv)
    print(f"listening on http://127.0.0.1:{httpd.server_address[1]}/mcp", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
