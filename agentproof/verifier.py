"""Verification agent: gathers THOROUGH evidence from the ERP verifier surface, then asks
the LLM to re-adjudicate. This is the engine behind Tier-A ground truth — legitimate
because it uses more data/time than the production agent did."""


def gather_evidence(inv, erp, cfg):
    vr = erp.vendor_risk(inv["vendor_id"])
    fuzzy, overlap = erp.find_fuzzy_duplicate(inv)
    fuzzy_full = fuzzy is not None and overlap >= 0.99
    fuzzy_partial = fuzzy is not None and 0.3 <= overlap < 0.99

    contract_overbill, overbill_amt = False, 0.0
    for l in inv["lines"]:
        cp = erp.contract_price(inv["vendor_id"], l["item"])
        if cp and l["unit_price"] > cp * (1 + cfg.price_tolerance):
            contract_overbill = True
            overbill_amt += (l["unit_price"] - cp) * l["qty"]

    qty_over, qty_amt = False, 0.0
    po = erp.get_po(inv["po_no"])
    if po:
        ordered = {l["item"]: l["qty"] for l in po["lines"]}
        price = {l["item"]: l["unit_price"] for l in po["lines"]}
        for l in inv["lines"]:
            if l["qty"] > ordered.get(l["item"], 10**12):
                qty_over = True
                qty_amt += (l["qty"] - ordered.get(l["item"], 0)) * price.get(l["item"], l["unit_price"])

    return {
        "vr": vr,
        "bank_changed": inv.get("bank_changed", False),
        "fuzzy_full": fuzzy_full,
        "fuzzy_partial": fuzzy_partial,
        "contract_overbill": contract_overbill,
        "overbill_amt": round(overbill_amt, 2),
        "qty_over": qty_over,
        "qty_amt": round(qty_amt, 2),
        "amount": inv["amount"],
    }


def make_verifier(llm):
    def verify(inv, erp, cfg):
        return llm.verify(gather_evidence(inv, erp, cfg))
    return verify


def make_fallible(base_verify, cfg):
    """Perturb a verifier to simulate real-world fallibility (false alarms / misses).
    A no-op when both knobs are 0 (e.g. real Claude, whose errors are already inherent)."""
    from random import Random
    fp, fn = cfg.verifier_fp_rate, cfg.verifier_fn_rate
    if fp <= 0 and fn <= 0:
        return base_verify

    def verify(inv, erp, cfg_):
        v = base_verify(inv, erp, cfg_)
        r = Random(f"{cfg.seed}:{inv['invoice_no']}")    # deterministic per decision
        if v["should_have_been"] == "approve":
            if r.random() < fp:                          # false alarm
                return {"should_have_been": "hold", "confidence": 0.5,
                        "failed_check": "spurious", "estimated_loss": round(inv["amount"] * 0.5, 2)}
        else:
            if r.random() < fn:                          # miss a real error
                return {"should_have_been": "approve", "confidence": 0.5,
                        "failed_check": None, "estimated_loss": 0.0}
        return v
    return verify
