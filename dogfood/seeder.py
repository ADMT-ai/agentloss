"""Generate a realistic AP stream and inject KNOWN errors → the oracle.

The oracle (invoice_no -> {correct_action, error_type, true_loss_usd}) is the ground
truth ailoss must recover. The agent and verifier never see it; only the seeder,
the outcome simulator, and the eval scorecard do.
"""
from random import Random
from .erp import ERP


def _legit_lines(rng, erp, vid, n_lines=None):
    items = [it for (v, it) in erp.price_list if v == vid]
    n = n_lines or rng.randint(1, 3)
    chosen = rng.sample(items, min(n, len(items)))
    lines = []
    for it in chosen:
        price = erp.price_list[(vid, it)]
        qty = rng.randint(1, 20)
        lines.append({"item": it, "qty": qty, "unit_price": round(price, 2)})
    return lines


def _amount(lines):
    return round(sum(l["qty"] * l["unit_price"] for l in lines), 2)


def _make_po(erp, po_no, vid, lines):
    erp.pos[po_no] = {"vendor_id": vid, "lines": [dict(l) for l in lines]}
    erp.receipts[po_no] = {l["item"]: l["qty"] for l in lines}  # fully received


def _roll(rng, cfg):
    r = rng.random()
    for typ, rate in (("duplicate", cfg.rate_duplicate), ("overpay", cfg.rate_overpay),
                      ("qty", cfg.rate_qty), ("fraud", cfg.rate_fraud),
                      ("false_trap", cfg.rate_false_trap), ("ambiguous", cfg.rate_ambiguous)):
        if r < rate:
            return typ
        r -= rate
    return None


def build(cfg):
    rng = Random(cfg.seed)
    erp = ERP()

    # vendors
    for i in range(cfg.n_vendors):
        vid = f"V{i:03d}"
        erp.vendors[vid] = {
            "name": f"Vendor {i}",
            "on_master": rng.random() > 0.03,
            "bank_changed": False,
            "recently_added": rng.random() < 0.12,
        }
    all_items = [f"ITEM{j:03d}" for j in range(60)]
    for vid in erp.vendors:
        for it in rng.sample(all_items, 12):
            erp.price_list[(vid, it)] = round(rng.uniform(10, 500), 2)

    stream, oracle, created = [], {}, []
    on_master_vendors = [v for v, d in erp.vendors.items() if d["on_master"]]

    for n in range(cfg.n_invoices):
        inv_no = f"INV{n:05d}"
        date = rng.randint(0, 365)
        typ = _roll(rng, cfg)
        vid = rng.choice(on_master_vendors)

        if typ == "duplicate" and created:
            base = rng.choice([c for c in created if c["vendor_id"] in on_master_vendors] or created)
            vid = base["vendor_id"]
            lines = [dict(l) for l in base["lines"]]
            po_no = base["po_no"]
            amount = _amount(lines)
            variant = rng.random() < 0.5
            if variant:                       # tweak amount slightly → agent's exact match misses
                bump = round(rng.uniform(0.5, 3.0), 2)
                lines[0] = dict(lines[0]); lines[0]["unit_price"] += bump
                amount = _amount(lines)
            inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
            oracle[inv_no] = {"correct_action": "reject", "error_type": "duplicate",
                              "true_loss_usd": amount}
            stream.append(inv)
            continue

        if typ == "overpay":
            lines = _legit_lines(rng, erp, vid)
            over_idx = 0
            contract = lines[over_idx]["unit_price"]
            lines[over_idx]["unit_price"] = round(contract * rng.uniform(1.15, 1.6), 2)
            amount = _amount(lines)
            po_no = f"PO{n:05d}"
            _make_po(erp, po_no, vid, lines)     # collusive: PO carries the inflated price
            inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
            overbill = (lines[over_idx]["unit_price"] - contract) * lines[over_idx]["qty"]
            oracle[inv_no] = {"correct_action": "hold", "error_type": "overpay",
                              "true_loss_usd": round(overbill, 2)}
            stream.append(inv)
            continue

        if typ == "qty":
            lines = _legit_lines(rng, erp, vid)
            po_no = f"PO{n:05d}"
            _make_po(erp, po_no, vid, lines)
            del erp.receipts[po_no]              # no receipt → agent can't qty-check
            billed = dict(lines[0]); billed["qty"] += rng.randint(3, 12)
            lines[0] = billed
            amount = _amount(lines)
            inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
            over_qty = billed["qty"] - erp.pos[po_no]["lines"][0]["qty"]
            oracle[inv_no] = {"correct_action": "hold", "error_type": "qty",
                              "true_loss_usd": round(over_qty * billed["unit_price"], 2)}
            stream.append(inv)
            continue

        if typ == "fraud":
            lines = _legit_lines(rng, erp, vid)
            amount = _amount(lines)
            po_no = f"PO{n:05d}"; _make_po(erp, po_no, vid, lines)
            inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
            inv["bank_changed"] = True                # per-invoice: bank details differ from master
            oracle[inv_no] = {"correct_action": "reject", "error_type": "fraud",
                              "true_loss_usd": amount}
            stream.append(inv)
            continue

        if typ == "false_trap":
            # valid invoice, but recently-added vendor + round amount → trips the agent
            erp.vendors[vid]["recently_added"] = True
            item = f"TRAP{n:05d}"
            unit = float(rng.choice([1000, 2000, 3000, 5000]))
            erp.price_list[(vid, item)] = unit           # contract == billed → not an overpay
            lines = [{"item": item, "qty": 1, "unit_price": unit}]
            amount = _amount(lines)
            po_no = f"PO{n:05d}"; _make_po(erp, po_no, vid, lines)
            inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
            oracle[inv_no] = {"correct_action": "approve", "error_type": "false_trap",
                              "true_loss_usd": 0.0}
            stream.append(inv); created.append(inv)
            continue

        if typ == "ambiguous" and created:
            base = rng.choice(created)
            vid = base["vendor_id"]
            lines = [dict(base["lines"][0])]                 # overlap ONE line
            lines += _legit_lines(rng, erp, vid, n_lines=2)  # plus new lines → partial match
            amount = _amount(lines)
            inv = _mk(inv_no, vid, erp, amount, base["po_no"], lines, date, n)
            oracle[inv_no] = {"correct_action": "hold", "error_type": "ambiguous",
                              "true_loss_usd": round(amount * 0.5, 2)}
            stream.append(inv)
            continue

        # legit
        lines = _legit_lines(rng, erp, vid)
        amount = _amount(lines)
        po_no = f"PO{n:05d}"; _make_po(erp, po_no, vid, lines)
        inv = _mk(inv_no, vid, erp, amount, po_no, lines, date, n)
        oracle[inv_no] = {"correct_action": "approve", "error_type": None, "true_loss_usd": 0.0}
        stream.append(inv); created.append(inv)

    return erp, stream, oracle


def _mk(inv_no, vid, erp, amount, po_no, lines, date, seq):
    return {
        "invoice_no": inv_no,
        "vendor_id": vid,
        "vendor_name": erp.vendors[vid]["name"],
        "amount": amount,
        "currency": "USD",
        "po_no": po_no,
        "lines": lines,
        "date": date,
        "seq": seq,
        "bank_changed": False,
    }
