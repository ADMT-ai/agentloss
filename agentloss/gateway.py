"""The agentloss gateway — measure any agent at the MCP boundary. See docs/GATEWAY.md.

A transparent stdio MCP proxy you put in front of a system-of-record's MCP server:

    agentloss gateway --manifest stripe.manifest.json -- stripe-mcp --api-key ...     # local (stdio)
    agentloss gateway --manifest stripe.manifest.json --url https://mcp.stripe.com \
        --header "Authorization: Bearer $KEY"                                          # remote (HTTP)

A JSON **manifest** (a pack, as data) declares which downstream tools are consequential and
where the exposure / join key live; every such `tools/call` through the proxy records a
Decision. The manifest's `outcomes` section declares the reversal tool (disputes,
credit-memos); `agentloss_sync_outcomes` calls it and maps its rows to gold outcomes. The
gateway also injects `agentloss_report` / `agentloss_doctor` / `agentloss_record_outcome`
into `tools/list`, so the agent reads its own error rate and dollar loss through the same
connection it acts through. Decisions/outcomes are appended to a JSONL store (`--store`)
for out-of-process readout (`agentloss report --store`).

Zero dependencies: the agent side is stdio (newline-delimited JSON-RPC 2.0, relayed raw); the
downstream side is either a spawned stdio server (`-- <command>`) or a remote Streamable-HTTP
server (`--url`, stdlib urllib — see gateway_http.py). Only `tools/list` responses and
`tools/call` request/response pairs are inspected. Instrumentation FAILS OPEN — a bad manifest
path or unparsable result never blocks the business call.
"""
import json
import subprocess
import sys
import threading

from .core import STORE, Decision, report_outcome
from .doctor import validate_integration
from .persist import DEFAULT_STORE_PATH, append_decision, append_outcome
from .report import report

__all__ = ["Manifest", "Gateway", "StdioDownstream", "main"]


# ---------------------------------------------------------------- manifest

class Manifest:
    """Parsed manifest: `tools` (consequential tools -> Decision paths) and `outcomes`
    (reversal tools -> outcome-row paths). See docs/GATEWAY.md for the format."""

    def __init__(self, data):
        self.use_case = data.get("use_case", "gateway")
        self.tools = data.get("tools", {}) or {}
        self.outcomes = data.get("outcomes", {}) or {}

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))


def _resolve(path, roots):
    """Resolve a dotted path ('arguments.amount', 'result.id', 'item.status') against roots.
    A path that doesn't start with a known root is returned as a literal. None on any miss."""
    if not isinstance(path, str):
        return path
    head, _, rest = path.partition(".")
    if head not in roots:
        return path  # literal (e.g. "action": "approve")
    node = roots[head]
    for part in rest.split(".") if rest else []:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if node is None:
            return None
    return node


def _result_data(result):
    """The tool's structured result: MCP structuredContent, else the first text content
    block JSON-parsed, else None."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("structuredContent"), (dict, list)):
        return result["structuredContent"]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                return json.loads(block.get("text", ""))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------- injected tools

def _schema(props, required):
    return {"type": "object", "properties": props, "required": required}

_AGENTLOSS_TOOLS = [
    {"name": "agentloss_report",
     "description": "Error rate (with confidence interval) and expected + realized dollar "
                    "loss of the decisions captured through this gateway.",
     "inputSchema": _schema({}, [])},
    {"name": "agentloss_doctor",
     "description": "Self-check the measurement wiring; catches the silent failures "
                    "(0% rate, only-errors reported, uncounted loss) in plain language.",
     "inputSchema": _schema({}, [])},
    {"name": "agentloss_sync_outcomes",
     "description": "Fetch the system of record's reversals (via the manifest's outcome "
                    "tool) and record them as ground-truth outcomes — gold when the rows "
                    "carry a status enum, silver (inferred outcome, estimated loss) when "
                    "the manifest declares mode=infer.",
     "inputSchema": _schema({"tool": {"type": "string", "description":
                             "Which manifest outcome tool to sync (default: all)."}}, [])},
    {"name": "agentloss_record_outcome",
     "description": "Record one resolved outcome by hand (ground truth from outside the "
                    "rail — a correction, audit result, or human review).",
     "inputSchema": _schema({
         "business_key": {"type": "string"},
         "ground_truth": {"type": "string"},
         "source": {"type": "string", "description":
                    "recovery_audit|dispute|chargeback|refund|human_queue"},
         "realized_loss_usd": {"type": "number"},
     }, ["business_key", "ground_truth", "source"])},
]


# ---------------------------------------------------------------- downstreams

class StdioDownstream:
    """A spawned local MCP server; the original transport. send() writes its stdin, a pump
    thread feeds its stdout lines to the gateway's on_msg callback."""

    def __init__(self, argv):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._lock = threading.Lock()

    def start(self, on_msg):
        def pump():
            for line in iter(self.proc.stdout.readline, b""):
                try:
                    msg = json.loads(line)
                except ValueError:
                    msg = None
                on_msg(msg, line)
        threading.Thread(target=pump, daemon=True).start()

    def send(self, data):
        raw = data if isinstance(data, bytes) else (json.dumps(data) + "\n").encode()
        with self._lock:
            self.proc.stdin.write(raw)
            self.proc.stdin.flush()

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


# ---------------------------------------------------------------- gateway

class Gateway:
    """Relays JSON-RPC between a stdio client (binary file-likes) and a downstream — a
    StdioDownstream or gateway_http.HttpDownstream — intercepting tools/list + tools/call
    per the manifest."""

    def __init__(self, manifest, client_in, client_out, downstream,
                 store_path=DEFAULT_STORE_PATH):
        self.m = manifest
        self.client_in, self.client_out = client_in, client_out
        self.downstream = downstream
        self.store_path = store_path
        self._client_lock = threading.Lock()   # writes to client_out
        self._pending_calls = {}               # request id -> (tool_name, arguments)
        self._pending_lists = set()            # request ids of client tools/list calls
        self._internal = {}                    # internal request id -> {event, result}
        self._internal_n = 0

    # ---- low-level I/O

    def to_client(self, msg):
        data = msg if isinstance(msg, bytes) else (json.dumps(msg) + "\n").encode()
        with self._client_lock:
            self.client_out.write(data)
            self.client_out.flush()

    def to_server(self, msg):
        self.downstream.send(msg)

    # ---- pumps

    def run(self):
        """Pump both directions; returns when the client closes its side."""
        self.downstream.start(self._on_server_msg)
        for line in iter(self.client_in.readline, b""):
            self._on_client_line(line)

    def _on_client_line(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            self.to_server(line)
            return
        method = msg.get("method")
        if method == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            if name.startswith("agentloss_"):
                self.to_client({"jsonrpc": "2.0", "id": msg.get("id"),
                                "result": self._local_tool(name, msg)})
                return
            if name in self.m.tools and msg.get("id") is not None:
                self._pending_calls[msg["id"]] = (
                    name, (msg.get("params") or {}).get("arguments") or {})
        elif method == "tools/list" and msg.get("id") is not None:
            self._pending_lists.add(msg["id"])
        self.to_server(line)

    def _on_server_msg(self, msg, raw=None):
        """One downstream message (from the stdio pump or an HTTP response body)."""
        if not isinstance(msg, dict):
            if raw is not None:
                self.to_client(raw)
            return
        mid = msg.get("id")
        if mid in self._internal:                       # our own downstream call
            holder = self._internal.pop(mid)
            holder["msg"] = msg
            holder["event"].set()
            return
        if "method" not in msg and mid in self._pending_calls:
            self._record_decision(msg, *self._pending_calls.pop(mid))
        if "method" not in msg and mid in self._pending_lists:
            self._pending_lists.discard(mid)
            self.to_client(self._inject_tools(msg))
            return
        self.to_client(raw if raw is not None else msg)

    # ---- interception

    def _inject_tools(self, msg):
        try:
            msg.setdefault("result", {}).setdefault("tools", []).extend(_AGENTLOSS_TOOLS)
        except (AttributeError, TypeError):
            pass
        return msg

    def _record_decision(self, response, tool_name, arguments):
        """Extract a Decision from a consequential tools/call round trip. Fails open."""
        try:
            result = response.get("result")
            if response.get("error") or (isinstance(result, dict) and result.get("isError")):
                return  # the action didn't commit; nothing at risk
            spec = self.m.tools[tool_name]
            roots = {"arguments": arguments, "result": _result_data(result)}
            amount = _resolve(spec.get("amount"), roots)
            key = _resolve(spec.get("business_key"), roots)
            if key is None or amount is None:
                return
            d = STORE.record(Decision(
                action=str(_resolve(spec.get("action", "approve"), roots)),
                value_at_risk_usd=float(amount) / float(spec.get("amount_divisor", 1)),
                business_key=str(key),
                use_case=spec.get("use_case", self.m.use_case),
                currency=str(_resolve(spec.get("currency"), roots) or "USD").upper(),
                model="gateway"))
            if self.store_path:
                append_decision(d, self.store_path)
        except Exception:
            pass

    # ---- local (injected) tools

    def _local_tool(self, name, msg):
        args = ((msg.get("params") or {}).get("arguments")) or {}
        try:
            if name == "agentloss_report":
                payload = report()
            elif name == "agentloss_doctor":
                payload = validate_integration()
            elif name == "agentloss_sync_outcomes":
                payload = self.sync_outcomes(args.get("tool"))
            elif name == "agentloss_record_outcome":
                payload = self._record_outcome(args)
            else:
                payload = {"error": f"unknown tool {name}"}
        except Exception as e:
            payload = {"error": repr(e)}
        text = json.dumps(payload, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": "error" in payload}

    def _record_outcome(self, args):
        key = str(args["business_key"])
        loss = args.get("realized_loss_usd")
        report_outcome(key, ground_truth=str(args["ground_truth"]),
                       source=str(args["source"]),
                       realized_loss_usd=None if loss is None else float(loss),
                       estimated_loss_usd=None if loss is None else float(loss))
        if self.store_path:
            append_outcome(key, STORE.outcomes[key], self.store_path)
        return {"recorded": key}

    # ---- outcome sync (the detector, driven by the manifest)

    def call_downstream(self, tool, arguments=None, timeout=30):
        """Issue our own tools/call to the downstream server (reserved id namespace)."""
        self._internal_n += 1
        rid = f"agentloss-{self._internal_n}"
        holder = {"event": threading.Event(), "msg": None}
        self._internal[rid] = holder
        self.to_server({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments or {}}})
        if not holder["event"].wait(timeout):
            self._internal.pop(rid, None)
            raise TimeoutError(f"downstream {tool} timed out after {timeout}s")
        msg = holder["msg"]
        if msg.get("error"):
            raise RuntimeError(f"downstream {tool} error: {msg['error']}")
        return msg.get("result")

    def sync_outcomes(self, only_tool=None):
        """Call the manifest's reversal tool(s); map rows -> outcomes. Two modes per spec:

        - `"mode": "status"` (default) — the row carries a status enum; matches are GOLD,
          realized dollars. Mirrors packs.outcomes_from_reversals.
        - `"mode": "infer"` — the row carries free-text evidence, no reliable enum; the
          outcome is INFERRED and the loss ESTIMATED (agentloss.inference). Verdicts are
          SILVER: the dollars flow through expected loss, never realized.

        census=True also marks the uncontested captured decisions correct, so the
        denominator is right."""
        totals = {"errors": 0, "correct": 0, "skipped_nonfinal": 0, "census_correct": 0,
                  "inferred": 0}
        specs = ({only_tool: self.m.outcomes[only_tool]} if only_tool
                 else dict(self.m.outcomes))
        seen = set()
        census = False
        for tool, spec in specs.items():
            census = census or bool(spec.get("census", True))
            data = _result_data(self.call_downstream(tool, spec.get("arguments")))
            rows = _resolve(spec.get("items", "result"), {"result": data})
            infer = spec.get("mode") == "infer"
            for row in rows if isinstance(rows, list) else []:
                roots = {"item": row}
                key = _resolve(spec.get("business_key"), roots)
                if key is None:
                    continue
                key = str(key)
                if infer:
                    self._sync_inferred(key, spec, roots, seen, totals)
                    continue
                status = _resolve(spec.get("status"), roots)
                if status is None:
                    continue
                status = str(status)
                # any dispute row — final or not — takes the key out of the census
                # ("no reversal" means correct; "unresolved reversal" means unknown)
                seen.add(key)
                if status in (spec.get("error_statuses") or []):
                    loss = _resolve(spec.get("loss"), roots)
                    if loss is None and spec.get("loss_fallback") == "value_at_risk":
                        # the SoR names the error but not the dollar: estimate the loss
                        # from the decision's own exposure (expected, not realized)
                        self._sync_one(key, "reject", spec, self._value_at_risk(key),
                                       realized=False)
                    else:
                        loss = (float(loss) if loss is not None else 0.0) \
                            / float(spec.get("amount_divisor", 1))
                        self._sync_one(key, "reject", spec, loss)
                    totals["errors"] += 1
                elif status in (spec.get("correct_statuses") or []):
                    self._sync_one(key, self._action_of(key), spec, 0.0)
                    totals["correct"] += 1
                else:
                    totals["skipped_nonfinal"] += 1
        if census:
            first = next(iter(specs.values()))
            source = first.get("source", "dispute")
            # census fills inherit the channel's fidelity: an absence observed through an
            # inferred channel is silver, like the channel itself
            realized = first.get("mode") != "infer"
            for key, d in list(STORE.decisions.items()):
                if key not in seen and key not in STORE.outcomes:
                    self._sync_one(key, d.action, {"source": source}, 0.0,
                                   realized=realized)
                    totals["census_correct"] += 1
        return totals

    def _sync_inferred(self, key, spec, roots, seen, totals):
        """One infer-mode row: read the evidence, infer the outcome, estimate the loss."""
        from .inference import infer_outcome
        paths = spec.get("evidence") or []
        paths = [paths] if isinstance(paths, str) else paths
        evidence = " | ".join(str(v) for p in paths
                              if (v := _resolve(p, roots)) is not None)
        loss = _resolve(spec.get("loss"), roots)
        var = self._value_at_risk(key) \
            if spec.get("loss_fallback", "value_at_risk") == "value_at_risk" else None
        v = infer_outcome(evidence,
                          loss=None if loss is None else
                          float(loss) / float(spec.get("amount_divisor", 1)),
                          value_at_risk=var,
                          error_markers=spec.get("error_markers"),
                          correct_markers=spec.get("correct_markers"))
        seen.add(key)          # even a non-final case note takes the key out of the census
        if v["ground_truth"] is None:
            totals["skipped_nonfinal"] += 1
            return
        totals["inferred"] += 1
        if v["ground_truth"] == "reject":
            self._sync_one(key, "reject", spec, v["estimated_loss_usd"],
                           realized=False, confidence=v["confidence"])
            totals["errors"] += 1
        else:
            self._sync_one(key, self._action_of(key), spec, 0.0,
                           realized=False, confidence=v["confidence"])
            totals["correct"] += 1

    def _value_at_risk(self, key):
        d = STORE.decisions.get(key)
        return d.value_at_risk_usd if d else 0.0

    def _action_of(self, key):
        d = STORE.decisions.get(key)
        return d.action if d else "approve"

    def _sync_one(self, key, ground_truth, spec, loss, realized=True, confidence=1.0):
        """realized=True: gold ground truth, realized dollars. realized=False: an inferred
        or estimated outcome — silver, the dollars count as expected loss only."""
        report_outcome(key, ground_truth=ground_truth,
                       source=spec.get("source", "dispute"),
                       fidelity="gold" if realized else "silver",
                       confidence=confidence,
                       realized_loss_usd=loss if realized else None,
                       estimated_loss_usd=loss)
        if self.store_path:
            append_outcome(key, STORE.outcomes[key], self.store_path)


# ---------------------------------------------------------------- entrypoint

_USAGE = ("usage: agentloss gateway --manifest m.json [--store path] "
          "(-- <command...> | --url https://... [--header 'Name: value']...)\n"
          "       agentloss gateway init [--out m.json] -- <command...>")


def main(argv=None):
    """agentloss gateway --manifest m.json [--store path] -- <downstream command...>
    agentloss gateway --manifest m.json --url https://... [--header 'Authorization: ...']
    agentloss gateway init [--out m.json] -- <downstream command...>   (draft the manifest)"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["init"]:
        from .gateway_init import main as init_main
        return init_main(argv[1:])
    if "--" in argv:
        split = argv.index("--")
        opts, command = argv[:split], argv[split + 1:]
    else:
        opts, command = argv, None
    manifest_path, store_path, url, headers = None, DEFAULT_STORE_PATH, None, {}
    i = 0
    while i < len(opts):
        if opts[i] == "--manifest":
            manifest_path, i = opts[i + 1], i + 2
        elif opts[i] == "--store":
            store_path, i = opts[i + 1], i + 2
        elif opts[i] == "--url":
            url, i = opts[i + 1], i + 2
        elif opts[i] == "--header":
            name, _, value = opts[i + 1].partition(":")
            headers[name.strip()] = value.strip()
            i += 2
        else:
            print(f"unknown option {opts[i]}\n{_USAGE}", file=sys.stderr)
            return 2
    if not manifest_path or not (bool(url) ^ bool(command)):
        print(_USAGE, file=sys.stderr)
        return 2
    manifest = Manifest.load(manifest_path)
    if url:
        from .gateway_http import HttpDownstream
        downstream = HttpDownstream(url, headers=headers)
    else:
        downstream = StdioDownstream(command)
    gw = Gateway(manifest, sys.stdin.buffer, sys.stdout.buffer, downstream,
                 store_path=store_path)
    try:
        gw.run()
    finally:
        downstream.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
