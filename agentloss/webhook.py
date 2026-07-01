"""`agentloss listen` — outcomes pushed by the system of record, the moment the world rules.

Reversals resolve weeks or months after the decision; polling (`agentloss_sync_outcomes`,
`agentloss import`) means someone has to remember to run it. Most rails can push instead:
Stripe webhooks, ERP event subscriptions, an internal reconciliation job's HTTP hook. This is
a tiny stdlib HTTP listener that maps those events onto resolved Outcomes in real time:

    agentloss listen --map events.json --store .agentloss/store.jsonl --port 8787

The event map is the manifest idea, for pushes — dotted paths rooted at `event` (the POSTed
JSON body), with the same status contract as everywhere else (neither list -> non-final,
skipped):

    {"type": "event.type",
     "events": {"charge.dispute.closed": {
         "business_key": "event.data.object.payment_intent",
         "status": "event.data.object.status",
         "loss": "event.data.object.amount", "amount_divisor": 100,
         "error_statuses": ["lost"], "correct_statuses": ["won"],
         "source": "chargeback"}}}

Every response is JSON and (except auth/malformed input) 200, so upstream retry machinery
settles: {"recorded": ...} / {"skipped": <reason>}. `--secret X` requires callers to present
`X-Agentloss-Secret: X` — a basic shared-secret gate; put provider signature verification
(e.g. Stripe-Signature) in front of this listener or verify upstream, since schemes are
provider-specific.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import STORE, report_outcome
from .gateway import _resolve
from .persist import append_outcome, load_store

__all__ = ["handle_event", "serve", "main"]


def handle_event(event, mapping, store_path=None):
    """Pure-ish: one pushed event -> {"recorded": key, ...} or {"skipped": reason}.
    Records into the store (+ JSONL) when it maps to a final outcome."""
    roots = {"event": event}
    etype = _resolve(mapping.get("type", "event.type"), roots)
    spec = (mapping.get("events") or {}).get(str(etype))
    if spec is None:
        return {"skipped": f"no rule for event type {etype!r}"}
    key = _resolve(spec.get("business_key"), roots)
    status = _resolve(spec.get("status"), roots)
    if key is None:
        return {"skipped": "business_key path resolved to nothing"}
    key = str(key)
    status = None if status is None else str(status)
    if status in (spec.get("error_statuses") or []):
        loss = _resolve(spec.get("loss"), roots)
        loss = (float(loss) if loss is not None else 0.0) / float(
            spec.get("amount_divisor", 1))
        ground_truth = "reject"
    elif status in (spec.get("correct_statuses") or []):
        d = STORE.decisions.get(key)
        ground_truth, loss = (d.action if d else "approve"), 0.0
    else:
        return {"skipped": f"status {status!r} is non-final", "business_key": key}
    report_outcome(key, ground_truth=ground_truth, source=spec.get("source", "dispute"),
                   fidelity="gold", realized_loss_usd=loss, estimated_loss_usd=loss)
    if store_path:
        append_outcome(key, STORE.outcomes[key], store_path)
    return {"recorded": key, "ground_truth": ground_truth, "realized_loss_usd": loss}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._reply(200, {"ok": True, "outcomes": len(STORE.outcomes)})
        return self._reply(404, {"error": "not found"})

    def do_POST(self):
        cfg = self.server.cfg
        if cfg["secret"] and self.headers.get("X-Agentloss-Secret") != cfg["secret"]:
            return self._reply(401, {"error": "missing or wrong X-Agentloss-Secret"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            event = json.loads(self.rfile.read(length) or b"")
        except ValueError:
            return self._reply(400, {"error": "body is not JSON"})
        try:
            result = handle_event(event, cfg["mapping"], store_path=cfg["store"])
        except Exception as e:  # a bad path spec must not 5xx-loop the provider's retries
            result = {"skipped": f"mapping failed: {e!r}"}
        return self._reply(200, result)


def serve(mapping, store_path=None, port=0, secret=None, host="127.0.0.1"):
    """Build the listener (call .serve_forever() yourself; port=0 picks a free one)."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.cfg = {"mapping": mapping, "store": store_path, "secret": secret}
    return httpd


def main(args):
    """Wired from the CLI: agentloss listen --map events.json --store s.jsonl [--port N]
    [--secret X] [--host H]."""
    with open(args.map, encoding="utf-8") as f:
        mapping = json.load(f)
    if args.store:
        try:
            loaded = load_store(args.store)
            print(f"loaded store: {loaded}", file=sys.stderr)
        except FileNotFoundError:
            pass  # first run; decisions will arrive from the agent side
    httpd = serve(mapping, store_path=args.store, port=args.port, secret=args.secret,
                  host=args.host)
    print(f"agentloss listen: http://{httpd.server_address[0]}:{httpd.server_address[1]} "
          f"({len(mapping.get('events') or {})} event rule(s); POST events, GET /healthz)",
          file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
