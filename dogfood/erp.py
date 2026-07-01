"""In-process ERP with a REST-shaped surface.

Two surfaces on purpose:
  * agent surface  (limited)  — what a fast/cheap production agent affords
  * verifier surface (thorough) — what a re-adjudicator with more time/data affords

This asymmetry is the whole reason the verification agent produces legitimate ground
truth. Later this class gets wrapped in FastAPI (real HTTP) and then swapped for ERPNext.
"""


def _items(lines):
    return {l["item"] for l in lines}


def line_overlap(a, b):
    ia, ib = _items(a), _items(b)
    if not ia or not ib:
        return 0.0
    return len(ia & ib) / max(len(ia), len(ib))


class ERP:
    def __init__(self):
        self.vendors = {}          # vid -> {name, on_master, bank_changed, recently_added}
        self.pos = {}              # po_no -> {vendor_id, lines:[{item,qty,unit_price}]}
        self.receipts = {}         # po_no -> {item: received_qty}
        self.price_list = {}       # (vid, item) -> contract_unit_price
        self.history = []          # submitted invoices (public), grows during the run
        self.payments = []
        self.credit_memos = []     # (invoice_no, amount)

    # ---------- agent surface (limited) ----------
    def get_vendor(self, vid):
        return self.vendors.get(vid)

    def get_po(self, po_no):
        return self.pos.get(po_no) if po_no else None

    def get_receipt(self, po_no):
        return self.receipts.get(po_no) if po_no else None

    def find_exact_duplicate(self, inv, window_days):
        """Same vendor + same amount + same PO, different invoice_no, within window."""
        for h in self.history:
            if h["invoice_no"] == inv["invoice_no"] or h.get("seq", -1) >= inv.get("seq", 10**18):
                continue
            if (h["vendor_id"] == inv["vendor_id"]
                    and abs(h["amount"] - inv["amount"]) < 1e-6
                    and h["po_no"] == inv["po_no"]
                    and abs(h["date"] - inv["date"]) <= window_days):
                return h
        return None

    # ---------- verifier surface (thorough) ----------
    def find_fuzzy_duplicate(self, inv, window_days=365):
        """A duplicate re-bills an already-submitted PO (that's what distinguishes it from a
        legit repeat order, which has its own PO). Match prior same-vendor invoices on the
        same PO, ranked by line overlap. Returns (match, overlap)."""
        best, best_overlap = None, 0.0
        if inv["po_no"] is None:
            return best, best_overlap
        for h in self.history:
            if h["invoice_no"] == inv["invoice_no"] or h.get("seq", -1) >= inv.get("seq", 10**18):
                continue                      # only PRIOR invoices count as duplicates
            if h["vendor_id"] != inv["vendor_id"] or h["po_no"] != inv["po_no"]:
                continue
            if abs(h["date"] - inv["date"]) > window_days:
                continue
            ov = line_overlap(h["lines"], inv["lines"])
            if ov > best_overlap:
                best, best_overlap = h, ov
        return best, best_overlap

    def contract_price(self, vid, item):
        return self.price_list.get((vid, item))

    def vendor_risk(self, vid):
        v = self.vendors.get(vid) or {}
        return {
            "on_master": v.get("on_master", False),
            "bank_changed": v.get("bank_changed", False),
            "recently_added": v.get("recently_added", False),
        }

    # ---------- actions ----------
    def dispatch_payment(self, inv):
        self.payments.append(inv["invoice_no"])

    def submit(self, inv):
        """Record the invoice into history (so later duplicates can find it)."""
        self.history.append(inv)

    def book_credit_memo(self, invoice_no, amount):
        self.credit_memos.append((invoice_no, amount))
