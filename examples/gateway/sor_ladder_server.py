"""The synthetic SoR ladder — one mock system-of-record MCP server, three rungs of mess.

Every system of record is different; what varies most is HOW the outcome is written down.
This server plays the same payments business at three levels of outcome fidelity, so the
whole loop (onboard -> execute -> deliver) can be dogfooded per rung and the recovered
numbers compared against one oracle:

    python examples/gateway/sor_ladder_server.py --level 0 [--seed]

- **level 0 — explicit**: `list_disputes` rows carry a status enum + a dollar amount.
  The basic case: outcomes are looked up (gold, realized dollars).
- **level 1 — inferred outcome, explicit loss**: `list_resolution_notes` rows carry a
  FREE-TEXT note (no status field) + an amount column. The outcome must be inferred;
  the dollar is still a lookup.
- **level 2 — inferred outcome, estimated loss**: `list_case_notes` rows carry only a
  note. The loss must be estimated too — parsed from the text when written there
  ("refunded $200.00"), else bounded by the decision's value-at-risk.
- **level 3 — unknown status vocabulary**: `list_dispute_settlements` rows carry a
  status enum NOBODY has seen (MERCHANT_DEBIT, CONSUMER_CLAIM_DENIED, IN_ARBITRATION)
  plus a free-text summary and an amount. Onboarding must LEARN the mapping from the
  rows' own text; execution then runs in plain status mode — gold, realized dollars.
- **level 4 — paginated outcome read**: level 0's rows, served two per page behind an
  opaque cursor (`next_cursor` in the response, `cursor` argument in). Reading only
  page one would silently under-count; onboarding must detect the cursor and the
  gateway must follow it to the end.
- **level 5 — outcome split across two tools**: `list_return_cases` rows carry the
  payment, the case id, and the status — but NO dollar; the amounts live in
  `list_settlement_amounts`, keyed by case. Onboarding must pick `payment_id` (not
  `case_id`) as the join key back to the decisions, discover the sibling read, and
  draft the join; sync executes it — gold, realized dollars.
- **level 6 — revised rulings (delayed/duplicated resolutions)**: `list_dispute_rulings`
  keeps the appeal HISTORY — the same payment appears twice, and the list is served
  newest-first, so "last row wins" picks the STALE ruling and counting every row
  double-counts. Onboarding must spot the duplicates and the `revised_at` field;
  sync must keep only each payment's latest ruling.
- **level 7 — evidence beyond the vocabulary**: `list_support_tickets` threads are
  customer-service prose with no marker language at all — a REASONING AGENT must
  judge them (`AGENTLOSS_REASONER`), its verdicts are silver, and its fallibility is
  corrected by two-phase calibration against a small gold budget.

The oracle rule (same at every level, keyed on the customer suffix):
`-fraud` -> error, full amount lost; `-partial` -> error, 40% of the amount lost;
`-won` -> disputed but correct; `-contested` -> disputed, error language in the note,
but resolved correct (exercises last-marker-wins); `-pending` -> non-final; anything
else -> undisputed correct. `--seed` pre-populates history so `gateway init` probing
sees real rows. Pure stdio JSON-RPC, no deps.
"""
import json
import sys

PAYMENTS = []          # (id, amount, currency, customer) in creation order
PARTIAL_FRACTION = 0.4


def _base_tools(outcome_tool, outcome_desc, outcome_props=None):
    return [
        {"name": "create_payment",
         "description": "Charge a customer. THE consequential action.",
         "inputSchema": {"type": "object", "properties": {
             "amount": {"type": "number"}, "currency": {"type": "string"},
             "customer": {"type": "string"}}, "required": ["amount", "customer"]}},
        {"name": "lookup_customer",
         "description": "Read-only customer profile lookup.",
         "inputSchema": {"type": "object", "properties": {
             "customer": {"type": "string"}}, "required": ["customer"]}},
        {"name": outcome_tool, "description": outcome_desc,
         "inputSchema": {"type": "object", "properties": outcome_props or {}}},
    ]


LEVELS = {
    0: ("list_disputes", "All disputes raised against payments.", None),
    1: ("list_resolution_notes", "Resolution notes for contested payments.", None),
    2: ("list_case_notes", "Case notes for payments under review.", None),
    3: ("list_dispute_settlements", "Settlement records for disputed payments.", None),
    4: ("list_disputes", "Disputes raised against payments, two per page.",
        {"cursor": {"type": "string", "description": "Opaque page cursor."}}),
    5: ("list_return_cases", "Return cases opened against payments.", None),
    6: ("list_dispute_rulings", "Dispute rulings, including revisions on appeal.", None),
    7: ("list_support_tickets", "Support tickets about charges.", None),
}
PAGE_SIZE = 2
AMOUNTS_TOOL = {"name": "list_settlement_amounts",
                "description": "Settled dollar amounts, by case.",
                "inputSchema": {"type": "object", "properties": {}}}


def _rows(level):
    if level == 6:
        return _ruling_rows()
    if level == 7:
        return _ticket_rows()
    split = level == 5                      # level 5 = level 0 verdicts, dollar elsewhere
    level = 0 if level in (4, 5) else level  # levels 4/5 reuse level 0's row shapes
    rows = []
    for pid, amount, currency, customer in PAYMENTS:
        partial = round(amount * PARTIAL_FRACTION, 2)
        if customer.endswith("-fraud"):
            row = {0: {"payment_id": pid, "status": "lost", "amount": amount},
                   1: {"payment_id": pid, "amount": amount,
                       "note": "chargeback lost — funds clawed back from merchant"},
                   2: {"payment_id": pid,
                       "note": "fraudulent charge confirmed; customer made whole, "
                               "full amount refunded"},
                   3: {"payment_id": pid, "status": "MERCHANT_DEBIT", "amount": amount,
                       "summary": "chargeback lost — funds clawed back from "
                                  "merchant"}}[level]
        elif customer.endswith("-partial"):
            row = {0: {"payment_id": pid, "status": "lost", "amount": partial},
                   1: {"payment_id": pid, "amount": partial,
                       "note": "complaint upheld in part — partial refund issued"},
                   2: {"payment_id": pid,
                       "note": f"complaint upheld in part — refunded ${partial:.2f} "
                               "to customer"},
                   3: {"payment_id": pid, "status": "MERCHANT_DEBIT_PARTIAL",
                       "amount": partial,
                       "summary": "complaint upheld in part — partial refund "
                                  "issued"}}[level]
        elif customer.endswith("-won"):
            row = {0: {"payment_id": pid, "status": "won", "amount": amount},
                   1: {"payment_id": pid, "amount": amount,
                       "note": "dispute resolved in merchant favor — charge stands"},
                   2: {"payment_id": pid,
                       "note": "reviewed: no merchant error, case closed in "
                               "merchant favor"},
                   3: {"payment_id": pid, "status": "CONSUMER_CLAIM_DENIED",
                       "amount": amount,
                       "summary": "dispute resolved in merchant favor — charge "
                                  "stands"}}[level]
        elif customer.endswith("-contested"):
            row = {0: {"payment_id": pid, "status": "won", "amount": amount},
                   1: {"payment_id": pid, "amount": amount,
                       "note": "customer says they were wrongly charged; after "
                               "review, complaint dismissed"},
                   2: {"payment_id": pid,
                       "note": "customer claimed they were wrongly charged; "
                               "investigation found no merchant error"},
                   3: {"payment_id": pid, "status": "CONSUMER_CLAIM_DENIED",
                       "amount": amount,
                       "summary": "customer says they were wrongly charged; after "
                                  "review, complaint dismissed"}}[level]
        elif customer.endswith("-pending"):
            row = {0: {"payment_id": pid, "status": "under_review", "amount": amount},
                   1: {"payment_id": pid, "amount": amount,
                       "note": "case open, awaiting customer evidence"},
                   2: {"payment_id": pid,
                       "note": "case open, awaiting customer evidence"},
                   3: {"payment_id": pid, "status": "IN_ARBITRATION", "amount": amount,
                       "summary": "case open, awaiting customer evidence"}}[level]
        else:
            continue
        if split:           # the case list: payment + case + status, NO dollar
            row = {"case_id": f"case_{pid}", "payment_id": pid,
                   "status": row["status"]}
        rows.append(row)
    return rows


def _ruling_rows():
    """Level 6: the appeal history, newest ruling FIRST in the list — so naive
    'last row wins' picks the stale ruling, and counting every row double-counts."""
    t_first, t_appeal = "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z"
    rows = []
    for pid, amount, currency, customer in PAYMENTS:
        partial = round(amount * PARTIAL_FRACTION, 2)

        def row(status, amt, ts):
            return {"payment_id": pid, "status": status, "amount": amt,
                    "revised_at": ts}
        if customer.endswith("-fraud"):        # under review, then lost on ruling
            rows += [row("lost", amount, t_appeal),
                     row("under_review", amount, t_first)]
        elif customer.endswith("-partial"):    # won at first, overturned on appeal
            rows += [row("lost", partial, t_appeal),
                     row("won", amount, t_first)]
        elif customer.endswith("-won"):        # lost at first, merchant appeal won
            rows += [row("won", amount, t_appeal),
                     row("lost", amount, t_first)]
        elif customer.endswith("-contested"):
            rows += [row("won", amount, t_first)]
        elif customer.endswith("-pending"):
            rows += [row("under_review", amount, t_first)]
    return rows


def _ticket_rows():
    """Level 7: support-thread prose with NO marker language — only a reasoning agent
    can judge these (and the eval's mock reasoner errs on two of them, on purpose)."""
    threads = {
        "-fraud": "customer reported an unrecognized charge; we confirmed our "
                  "processing mistake and made things right with the customer",
        "-partial": "long call with the customer; a goodwill gesture was applied "
                    "to the account after review",
        "-won": "customer inquiry closed; charge verified with the customer and "
                "billed as agreed",
        "-contested": "customer insisted there was a processing mistake; we reviewed "
                      "the account thoroughly with them",
        "-pending": "ticket open — awaiting a response from the customer",
    }
    rows = []
    for pid, amount, currency, customer in PAYMENTS:
        thread = next((t for s, t in threads.items() if customer.endswith(s)), None)
        if thread is not None:
            rows.append({"payment_id": pid, "thread": thread})
    return rows


def _settlement_amounts():
    """Level 5's sibling read: the dollar for each case, keyed by case_id."""
    rows = []
    for pid, amount, currency, customer in PAYMENTS:
        if customer.split("-")[-1] not in ("fraud", "partial", "won", "contested",
                                           "pending"):
            continue
        settled = round(amount * PARTIAL_FRACTION, 2) \
            if customer.endswith("-partial") else amount
        rows.append({"case_id": f"case_{pid}", "amount": settled})
    return rows


def call_tool(level, name, args):
    outcome_tool = LEVELS[level][0]
    if name == "create_payment":
        pid = f"pay_{len(PAYMENTS) + 1}"
        PAYMENTS.append((pid, float(args["amount"]), args.get("currency", "USD"),
                         str(args["customer"])))
        payload = {"id": pid, "status": "succeeded"}
        return {"content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload, "isError": False}
    if name == "lookup_customer":
        payload = {"customer": args["customer"], "standing": "good"}
        return {"content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload, "isError": False}
    if level == 5 and name == "list_settlement_amounts":
        payload = {"amounts": _settlement_amounts()}
        return {"content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload, "isError": False}
    if name == outcome_tool:
        key = {"list_disputes": "disputes", "list_resolution_notes": "resolutions",
               "list_case_notes": "cases", "list_dispute_settlements": "settlements",
               "list_return_cases": "cases", "list_dispute_rulings": "rulings",
               "list_support_tickets": "tickets"}[outcome_tool]
        rows = _rows(level)
        if level == 4:      # served in pages; the cursor is an opaque offset
            start = int(args.get("cursor") or 0)
            more = start + PAGE_SIZE < len(rows)
            payload = {key: rows[start:start + PAGE_SIZE],
                       "next_cursor": str(start + PAGE_SIZE) if more else None}
        else:
            payload = {key: rows}
        result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                  "isError": False}
        if level != 1:      # level 1 stays text-only, exercising the other parse path
            result["structuredContent"] = payload
        return result
    return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def handle(level, msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": f"sor-ladder-l{level}", "version": "0"}}}
    if method == "tools/list":
        tools = _base_tools(*LEVELS[level])
        if level == 5:
            tools.append(AMOUNTS_TOOL)
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid,
                "result": call_tool(level, params.get("name"),
                                    params.get("arguments") or {})}
    if mid is not None:  # unknown request -> error; notifications are ignored
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"unknown method {method}"}}
    return None


def seed():
    """Pre-existing SoR history covering every row shape, so `gateway init` probing
    derives the paths (and the need to infer) from real data."""
    for cust, amount in [("legacy-a", 80.0), ("legacy-fraud", 250.0),
                         ("legacy-partial", 120.0), ("legacy-won", 40.0),
                         ("legacy-contested", 30.0), ("legacy-pending", 66.0)]:
        PAYMENTS.append((f"pay_seed_{len(PAYMENTS) + 1}", amount, "USD", cust))


def main():
    args = sys.argv[1:]
    level = int(args[args.index("--level") + 1]) if "--level" in args else 0
    if level not in LEVELS:
        print(f"unknown level {level}; choose one of {sorted(LEVELS)}", file=sys.stderr)
        return 2
    if "--seed" in args:
        seed()
    for line in sys.stdin.buffer:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(level, msg)
        if resp is not None:
            sys.stdout.buffer.write((json.dumps(resp) + "\n").encode())
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
