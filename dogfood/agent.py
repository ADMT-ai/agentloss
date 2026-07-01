"""The AP agent under test. Deliberately imperfect: exact-match dedup within a 90-day
window, PO-price checks (not contract-price), receipt-based qty checks, and a crude
new-vendor heuristic that occasionally false-blocks. Instrumented with @ailoss.decision.
"""
import ailoss


def gather_evidence(inv, erp, cfg):
    vendor = erp.get_vendor(inv["vendor_id"]) or {}
    po = erp.get_po(inv["po_no"])
    receipt = erp.get_receipt(inv["po_no"])
    exact = erp.find_exact_duplicate(inv, cfg.agent_dup_window_days)

    po_overbill = False
    if po:
        po_price = {l["item"]: l["unit_price"] for l in po["lines"]}
        for l in inv["lines"]:
            if l["item"] in po_price and l["unit_price"] > po_price[l["item"]] * (1 + cfg.price_tolerance):
                po_overbill = True

    qty_over = False
    if receipt:
        for l in inv["lines"]:
            if l["qty"] > receipt.get(l["item"], 10**12):
                qty_over = True

    amt = inv["amount"]
    false_trap = vendor.get("recently_added", False) and float(amt).is_integer() and int(amt) % 1000 == 0

    return {
        "vendor_off_master": not vendor.get("on_master", True),
        "exact_dup": bool(exact),
        "po_overbill": po_overbill,
        "qty_over": qty_over,
        "false_trap_heuristic": false_trap,
    }


@ailoss.decision
def _decide(inv, action, cfg):
    return ailoss.Decision(
        action=action,
        value_at_risk_usd=inv["amount"],
        business_key=inv["invoice_no"],
        model=cfg.llm_mode,
    )


def run(stream, erp, cfg, llm):
    for i, inv in enumerate(stream):
        ev = gather_evidence(inv, erp, cfg)
        action, _reason = llm.decide(ev)
        _decide(inv, action, cfg)
        if action == "approve":
            erp.dispatch_payment(inv)
        erp.submit(inv)   # record into history AFTER deciding, so later dups can find it
        if (i + 1) % 25 == 0:
            print(f"[agent] decided {i + 1}/{len(stream)}", flush=True)
