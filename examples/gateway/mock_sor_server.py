"""A mock system-of-record MCP server (pure stdio JSON-RPC, no deps) for the gateway eval.

Plays a payment SoR with a seeded, ORACLE-KNOWN dispute rule so the eval can check the
gateway recovers the truth exactly:

- `create_payment(amount, currency, customer)` -> {"id": "pay_N"}   (the money-mover;
  returned as MCP structuredContent)
- `lookup_customer(customer)` -> profile                            (NON-consequential —
  the gateway must record nothing for it)
- `list_disputes()` -> {"disputes": [...]}                          (the reversal read;
  returned as a text content block, exercising the gateway's other parse path)

Dispute rule (the oracle): a payment whose customer ends in `-fraud` is disputed and LOST
(full amount); a customer ending in `-won` is disputed and WON; `-pending` is under review
(non-final). Everything else is undisputed (correct).
"""
import json
import sys

PAYMENTS = []          # (id, amount, currency, customer) in creation order

TOOLS = [
    {"name": "create_payment",
     "description": "Charge a customer. THE consequential action.",
     "inputSchema": {"type": "object", "properties": {
         "amount": {"type": "number"}, "currency": {"type": "string"},
         "customer": {"type": "string"}}, "required": ["amount", "customer"]}},
    {"name": "lookup_customer",
     "description": "Read-only customer profile lookup.",
     "inputSchema": {"type": "object", "properties": {
         "customer": {"type": "string"}}, "required": ["customer"]}},
    {"name": "list_disputes",
     "description": "All disputes raised against payments.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _disputes():
    rows = []
    for pid, amount, currency, customer in PAYMENTS:
        if customer.endswith("-fraud"):
            rows.append({"payment_id": pid, "status": "lost", "amount": amount})
        elif customer.endswith("-won"):
            rows.append({"payment_id": pid, "status": "won", "amount": amount})
        elif customer.endswith("-pending"):
            rows.append({"payment_id": pid, "status": "under_review", "amount": amount})
    return rows


def call_tool(name, args):
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
    if name == "list_disputes":
        # text-only result (no structuredContent) — the gateway must JSON-parse the block
        return {"content": [{"type": "text",
                             "text": json.dumps({"disputes": _disputes()})}],
                "isError": False}
    return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-sor", "version": "0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid,
                "result": call_tool(params.get("name"), params.get("arguments") or {})}
    if mid is not None:  # unknown request -> error; notifications are ignored
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"unknown method {method}"}}
    return None


def seed():
    """Pre-existing SoR history, so `gateway init --probe` sees real dispute rows."""
    for cust, amount in [("legacy-a", 80.0), ("legacy-fraud", 250.0),
                         ("legacy-won", 40.0), ("legacy-pending", 66.0)]:
        PAYMENTS.append((f"pay_seed_{len(PAYMENTS) + 1}", amount, "USD", cust))


def main():
    if "--seed" in sys.argv:
        seed()
    for line in sys.stdin.buffer:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.buffer.write((json.dumps(resp) + "\n").encode())
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
