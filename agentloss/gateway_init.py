"""`agentloss gateway init` — draft a gateway manifest from a live MCP server's own tools/list.

The manifest is the last integration judgment the gateway asks for (which tools move money?
where do the reversals live?). `init` collapses it: probe the downstream server, classify its
tools with transparent heuristics, and emit a manifest that is either ready to run or carries
explicit `_todo` markers a human or coding agent can finish in one pass.

    agentloss gateway init [--out m.json] [--no-probe] -- <server command...>

- **Money-movers**: non-read tools whose name pairs a committing verb (create/send/pay/...)
  with a money noun (payment/refund/order/...), or whose input schema carries an amount-like
  numeric property. Read-prefixed tools (list_/get_/search_/...) are never money-movers.
- **Outcome reads**: read-prefixed tools naming a reversal noun (dispute/chargeback/
  credit_memo/...) or a resolution noun (note/case/complaint/...). With probing on
  (default), init CALLS each candidate that requires no arguments — reads are safe — and
  derives the row paths (`items`, `item.<key>`, `item.status`, `item.<amount>`) from the
  real response shape, mapping any observed statuses through a default vocabulary
  (lost/chargedback -> error, won -> correct). Rows with NO status field but free-text
  fields are drafted as `"mode": "infer"` (soft outcomes — agentloss.inference): the
  outcome will be inferred from the text and, when no amount column exists either, the
  loss estimated (`loss_fallback: value_at_risk`).

It also emits a `business_context` block — the domain it understood the server to be
(payments/billing/orders/...), the money-movers, and each outcome channel's mode — so the
judgment is reviewable, not implicit. Everything init could not establish is a `_todo` in
the emitted JSON; unknown keys are ignored by the gateway, so the notes ride along
harmlessly.
"""
import json
import re
import subprocess
import sys

__all__ = ["draft_manifest", "probe_tools", "probe_tools_http", "main"]

_READ_PREFIXES = ("list", "get", "search", "retrieve", "read", "lookup", "find", "fetch",
                  "describe", "query", "show")
_COMMIT_VERBS = ("create", "send", "issue", "post", "place", "submit", "execute", "approve",
                 "pay", "charge", "refund", "transfer", "capture", "confirm", "finalize")
_MONEY_NOUNS = ("payment", "charge", "invoice", "order", "refund", "payout", "transfer",
                "subscription", "purchase", "billing", "credit", "debit", "price", "quote")
_REVERSAL_NOUNS = ("dispute", "chargeback", "credit_memo", "credit_note", "debit_note",
                   "reversal", "complaint", "return")
# reads whose rows tend to carry the outcome as FREE TEXT instead of a status enum
_RESOLUTION_NOUNS = ("resolution", "note", "case", "ticket", "incident", "adjustment",
                     "review")
# domain guesses for the business_context block, by noun evidence in the tools/list
_DOMAINS = (("payments", ("payment", "charge", "payout", "transfer")),
            ("billing", ("invoice", "billing", "subscription", "credit", "debit")),
            ("orders", ("order", "purchase", "quote")),
            ("support", ("ticket", "case", "complaint")))
_AMOUNT_PROPS = ("amount", "amount_usd", "total", "total_amount", "value", "price",
                 "unit_amount", "amount_minor")
# default status vocabulary for probed reversal rows
_ERROR_STATUSES = ("lost", "charge_refunded", "chargedback", "charged_back", "failed",
                   "upheld", "accepted")
_CORRECT_STATUSES = ("won", "withdrawn", "overturned")


def _words(name):
    return re.split(r"[_\-./]+", name.lower())


def _is_read(name):
    return _words(name)[0] in _READ_PREFIXES


def _amount_prop(tool):
    props = ((tool.get("inputSchema") or {}).get("properties")) or {}
    for cand in _AMOUNT_PROPS:
        if cand in props and props[cand].get("type") in ("number", "integer", None):
            return cand, props[cand]
    return None, None


def _is_money_mover(tool):
    name = tool.get("name", "")
    if _is_read(name):
        return False
    words = _words(name)
    verb_noun = words[0] in _COMMIT_VERBS and any(
        n in "_".join(words) for n in _MONEY_NOUNS)
    return verb_noun or _amount_prop(tool)[0] is not None


def _is_reversal_read(tool):
    name = tool.get("name", "")
    return _is_read(name) and any(n in name.lower() for n in _REVERSAL_NOUNS)


def _is_outcome_read(tool):
    name = tool.get("name", "")
    return _is_read(name) and any(n in name.lower()
                                  for n in _REVERSAL_NOUNS + _RESOLUTION_NOUNS)


def _evidence_fields(rows):
    """Row fields that read like free text (a string with a space in it) — the evidence
    an inferred outcome is judged from."""
    fields = set()
    for row in rows:
        fields |= {f for f, v in row.items() if isinstance(v, str) and " " in v.strip()}
    return sorted(fields)


def _guess_domain(tools):
    text = " ".join("_".join(_words(t.get("name", ""))) for t in tools)
    for domain, nouns in _DOMAINS:
        if any(n in text for n in nouns):
            return domain
    return "transactions"


def _learn_status_vocab(rows, status_field, evidence_fields):
    """A status enum the default vocabulary doesn't know (MERCHANT_DEBIT, ...): LEARN the
    mapping by inferring each probed row's verdict from its free-text fields, then
    grouping the statuses by verdict. A status seen on both sides is ambiguous and lands
    in neither (its rows stay non-final). Returns (error_statuses, correct_statuses,
    rows_used) or None when the text decided nothing."""
    from .inference import infer_outcome
    err, ok = set(), set()
    used = 0
    for row in rows:
        status = row.get(status_field)
        if status is None:
            continue
        evidence = " | ".join(str(row[f]) for f in evidence_fields if row.get(f) is not None)
        verdict = infer_outcome(evidence)["ground_truth"]
        if verdict is None:
            continue
        used += 1
        (err if verdict == "reject" else ok).add(str(status))
    if not err and not ok:
        return None
    return sorted(err - ok), sorted(ok - err), used


def _minor_units(prop_name, prop_schema):
    desc = (prop_schema or {}).get("description", "").lower()
    return (prop_name in ("unit_amount", "amount_minor")
            or "cents" in desc or "minor unit" in desc or "smallest currency unit" in desc)


# ---------------------------------------------------------------- probing

def probe_tools(downstream, timeout=20):
    """Spawn the downstream MCP server, run initialize + tools/list, return (tools, caller).

    `caller(name, arguments)` issues one tools/call against the same live process; call
    `caller.close()` when done."""
    proc = subprocess.Popen(downstream, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    n = [0]

    def rpc(method, params):
        n[0] += 1
        rid = n[0]
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                      "params": params}) + "\n").encode())
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError(f"server exited during {method}")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == rid:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "agentloss-init", "version": "0"}})
    proc.stdin.write((json.dumps({"jsonrpc": "2.0",
                                  "method": "notifications/initialized",
                                  "params": {}}) + "\n").encode())
    proc.stdin.flush()
    tools = rpc("tools/list", {}).get("tools", [])

    def caller(name, arguments=None):
        return rpc("tools/call", {"name": name, "arguments": arguments or {}})

    def close():
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    caller.close = close
    return tools, caller


def probe_tools_http(url, headers=None, timeout=20):
    """The HTTP twin of probe_tools: initialize + tools/list against a remote (Streamable
    HTTP) MCP server, returning the same (tools, caller) contract. Rides HttpDownstream,
    so session-id echo and SSE responses come for free."""
    import threading

    from .gateway_http import HttpDownstream

    ds = HttpDownstream(url, headers=headers, timeout=timeout)
    waiting = {}

    def on_msg(msg, raw=None):
        holder = waiting.pop(msg.get("id"), None) if isinstance(msg, dict) else None
        if holder:
            holder["msg"] = msg
            holder["event"].set()
    ds.start(on_msg)
    n = [0]

    def rpc(method, params):
        n[0] += 1
        rid = f"init-{n[0]}"
        holder = {"event": threading.Event(), "msg": None}
        waiting[rid] = holder
        ds.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not holder["event"].wait(timeout):
            waiting.pop(rid, None)
            raise TimeoutError(f"{method} timed out after {timeout}s")
        msg = holder["msg"]
        if msg.get("error"):
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "agentloss-init", "version": "0"}})
    ds.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    tools = rpc("tools/list", {}).get("tools", [])

    def caller(name, arguments=None):
        return rpc("tools/call", {"name": name, "arguments": arguments or {}})

    caller.close = ds.close
    return tools, caller


def _result_rows(result):
    """A probed reversal result -> (items_path, rows). Accepts a bare list or a dict with
    exactly one obvious list-of-dicts value."""
    from .gateway import _result_data
    data = _result_data(result)
    if isinstance(data, list):
        return "result", data
    if isinstance(data, dict):
        lists = [(k, v) for k, v in data.items()
                 if isinstance(v, list) and all(isinstance(r, dict) for r in v)]
        if len(lists) == 1:
            return f"result.{lists[0][0]}", lists[0][1]
    return None, []


# paginated outcome reads: response fields that carry the next-page cursor, and the
# request arguments servers accept it under
_CURSOR_KEYS = ("next_cursor", "next_page_token", "next_page", "starting_after", "cursor")
_CURSOR_ARGS = ("cursor", "page_token", "starting_after", "after", "page")


def _paginate_spec(result, tool):
    """A cursor in the probed response -> the manifest `paginate` block, or None."""
    from .gateway import _result_data
    data = _result_data(result)
    if not isinstance(data, dict):
        return None
    key = next((k for k in _CURSOR_KEYS if data.get(k)), None)
    if key is None:
        return None
    props = ((tool.get("inputSchema") or {}).get("properties")) or {}
    arg = next((a for a in _CURSOR_ARGS if a in props), "cursor")
    return {"cursor": f"result.{key}", "arg": arg}


def _follow_pages(call, name, first_result, paginate, max_pages=20):
    """Collect the remaining pages' rows so classification sees the whole population,
    not page one. Returns the extra rows."""
    from .gateway import _result_data
    cursor_field = paginate["cursor"].partition(".")[2]
    rows = []
    result = first_result
    for _ in range(max_pages):
        data = _result_data(result)
        cursor = data.get(cursor_field) if isinstance(data, dict) else None
        if not cursor:
            break
        result = call(name, {paginate["arg"]: cursor})
        rows.extend(_result_rows(result)[1])
    return rows


def _row_paths(rows):
    """Derive item.* paths from observed reversal rows."""
    fields = set().union(*[set(r) for r in rows]) if rows else set()
    key = next((f for f in sorted(fields) if f.endswith("_id") and f != "id"), None)
    key_todo = None
    if key is None and "id" in fields:
        key, key_todo = "id", ("'id' is likely the reversal's own id, not the disputed "
                               "decision's business_key — point this at the field that "
                               "names the original payment/invoice.")
    status = "status" if "status" in fields else next(
        (f for f in sorted(fields) if "status" in f or f == "state"), None)
    loss = next((f for f in _AMOUNT_PROPS if f in fields), None)
    observed = sorted({str(r.get(status)) for r in rows if status and r.get(status) is not None})
    return key, key_todo, status, loss, observed


# ---------------------------------------------------------------- drafting

def draft_manifest(tools, use_case="gateway", call=None):
    """Classify a tools/list into a manifest draft. `call(name, args)`, when given, probes
    zero-required-argument reversal candidates to derive row paths from real data."""
    manifest = {"version": 1, "use_case": use_case, "tools": {}, "outcomes": {}}
    notes = []
    for tool in tools:
        name = tool.get("name", "")
        if _is_money_mover(tool):
            prop, schema = _amount_prop(tool)
            spec = {"business_key": "result.id", "action": "approve",
                    "_todo": "verify business_key: run one call and check the result "
                             "carries a durable id at result.id"}
            if prop:
                spec["amount"] = f"arguments.{prop}"
                if _minor_units(prop, schema):
                    spec["amount_divisor"] = 100
                    notes.append(f"{name}.{prop} looks like minor units -> amount_divisor "
                                 "100; zero-decimal currencies (JPY, ...) need care.")
            else:
                spec["amount"] = "_todo: no amount-like argument found; point this at the "\
                                 "exposure of the action (arguments.* or result.*)"
            props = ((tool.get("inputSchema") or {}).get("properties")) or {}
            if "currency" in props:
                spec["currency"] = "arguments.currency"
            manifest["tools"][name] = spec
        elif _is_outcome_read(tool):
            spec = {"source": "chargeback" if "dispute" in name or "chargeback" in name
                    else "refund", "census": True}
            required = ((tool.get("inputSchema") or {}).get("required")) or []
            probed = False
            if call is not None and not required:
                try:
                    result = call(name)
                    items_path, rows = _result_rows(result)
                    paginate = _paginate_spec(result, tool)
                    if paginate and items_path is not None:
                        spec["paginate"] = paginate
                        rows = rows + _follow_pages(call, name, result, paginate)
                    if items_path is not None and rows:
                        key, key_todo, status, loss, observed = _row_paths(rows)
                        evidence = _evidence_fields(rows)
                        spec["items"] = items_path
                        spec["business_key"] = (f"item.{key}" if key else
                                                "_todo: item.<field naming the original "
                                                "decision>")
                        if key_todo:
                            spec["_todo_business_key"] = key_todo
                        if status is None and evidence:
                            # no enum to look up — soft outcomes: infer from the text
                            spec["mode"] = "infer"
                            spec["source"] = "inferred"
                            spec["evidence"] = [f"item.{f}" for f in evidence]
                            if loss:
                                spec["loss"] = f"item.{loss}"
                            else:
                                spec["loss_fallback"] = "value_at_risk"
                                notes.append(f"{name} rows carry no amount field — an "
                                             "error's loss will be parsed from the "
                                             "evidence text, else estimated at the "
                                             "decision's value-at-risk.")
                            probed = True
                            manifest["outcomes"][name] = spec
                            continue
                        spec["status"] = f"item.{status}" if status else \
                            "_todo: item.<the row's resolution field>"
                        spec["loss"] = f"item.{loss}" if loss else \
                            "_todo: item.<the row's dollar amount>"
                        known_err = [s for s in observed if s.lower() in _ERROR_STATUSES]
                        known_ok = [s for s in observed if s.lower() in _CORRECT_STATUSES]
                        if status and observed and not known_err and not known_ok:
                            # an unknown vocabulary — learn it from the rows' own text
                            fields = [f for f in _evidence_fields(rows) if f != status]
                            learned = _learn_status_vocab(rows, status, fields) \
                                if fields else None
                            if learned:
                                known_err, known_ok, used = learned
                                spec["_learned_statuses"] = (
                                    f"vocabulary learned by inferring {used} probed "
                                    "row(s) from their free text "
                                    "(agentloss.inference) — review before trusting "
                                    "realized dollars")
                                notes.append(f"{name}: observed statuses matched no "
                                             "known vocabulary; mapping learned from "
                                             "the rows' free-text fields.")
                        spec["error_statuses"] = known_err or \
                            ["_todo: which observed statuses mean the decision was wrong"]
                        spec["correct_statuses"] = known_ok
                        spec["_observed_statuses"] = observed
                        probed = True
                    elif items_path is not None:
                        notes.append(f"{name} returned zero rows at init time — row "
                                     "fields left as _todo; re-run init once reversals "
                                     "exist, or fill them from the server's docs.")
                        spec["items"] = items_path
                except Exception as e:
                    notes.append(f"probing {name} failed ({e!r}); left as _todo.")
            if not probed:
                spec.setdefault("items", "_todo: path to the row array in the result")
                spec.update({
                    "business_key": "_todo: item.<field naming the original decision>",
                    "status": "item.status",
                    "loss": "item.amount",
                    "error_statuses": ["_todo"],
                    "correct_statuses": ["_todo"],
                })
            manifest["outcomes"][name] = spec
    domain = _guess_domain(tools)
    if use_case == "gateway":               # no slug given: use the understood domain
        manifest["use_case"] = domain
    manifest["business_context"] = {
        "domain": domain,
        "money_movers": sorted(manifest["tools"]),
        "outcome_channels": [
            {"tool": t, "mode": s.get("mode", "status"),
             **({"vocabulary": "learned"} if "_learned_statuses" in s else {})}
            for t, s in manifest["outcomes"].items()],
        "outcome_basis": ("inferred from free text" if any(
            s.get("mode") == "infer" for s in manifest["outcomes"].values())
            else "explicit statuses"),
    }
    manifest["_init"] = {
        "generated_by": "agentloss gateway init",
        "notes": notes,
        "next_steps": [
            "Resolve every _todo (a coding agent can: call the tool once, read the shape).",
            "Run: agentloss gateway --manifest <this file> -- <server command>",
            "After some traffic: call the agentloss_doctor tool (or `agentloss doctor "
            "--store .agentloss/store.jsonl`) to confirm the wiring.",
        ],
    }
    return manifest


_USAGE = ("usage: agentloss gateway init [--out m.json] [--use-case slug] [--no-probe] "
          "(-- <server command...> | --url https://... [--header 'Name: value']...)")


def main(argv):
    """agentloss gateway init [--out m.json] [--use-case slug] [--no-probe]
    (-- <server command...> | --url https://... [--header 'Name: value']...)"""
    if "--" in argv:
        split = argv.index("--")
        opts, downstream = argv[:split], argv[split + 1:]
    else:
        opts, downstream = argv, None
    out, use_case, probe, url, headers = None, "gateway", True, None, {}
    i = 0
    while i < len(opts):
        if opts[i] == "--out":
            out, i = opts[i + 1], i + 2
        elif opts[i] == "--use-case":
            use_case, i = opts[i + 1], i + 2
        elif opts[i] == "--no-probe":
            probe, i = False, i + 1
        elif opts[i] == "--url":
            url, i = opts[i + 1], i + 2
        elif opts[i] == "--header":
            name, _, value = opts[i + 1].partition(":")
            headers[name.strip()] = value.strip()
            i += 2
        else:
            print(f"unknown option {opts[i]}\n{_USAGE}", file=sys.stderr)
            return 2
    if not (bool(url) ^ bool(downstream)):
        print(_USAGE, file=sys.stderr)
        return 2

    tools, call = probe_tools_http(url, headers) if url else probe_tools(downstream)
    try:
        manifest = draft_manifest(tools, use_case=use_case, call=call if probe else None)
    finally:
        call.close()

    text = json.dumps(manifest, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        todos = text.count("_todo")
        print(f"wrote {out}: {len(manifest['tools'])} money-mover(s), "
              f"{len(manifest['outcomes'])} reversal read(s), "
              f"{todos} _todo marker(s) to resolve", file=sys.stderr)
    else:
        print(text)
    return 0
