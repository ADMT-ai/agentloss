"""`agentloss import` — batch outcomes from the warehouse's export (CSV), the most universal
ground-truth channel there is.

For most businesses the *operational* system of record is a disputes/chargebacks/credit-memo
table in the warehouse or the finance team's export — not an API. Every one of them can
produce a CSV, even when there is no MCP server and no webhook. This maps such a file onto
resolved Outcomes and joins them to the decisions in a persisted store:

    agentloss import --csv disputes.csv --store .agentloss/store.jsonl \\
        --map "business_key=invoice_no,status=resolution,loss=amount" \\
        --error-statuses lost,chargeback --correct-statuses won --source chargeback

Run without --map and it drafts one from the file's own header + observed statuses (the
`gateway init` move, for a file). Two shapes are supported:

- **status-mapped** (the honest default): rows whose status is in neither list are non-final
  and skipped — the detector contract.
- **--all-errors**: the export contains only the reversals (a pure chargebacks file). Every
  row is an error; pair with --census only if this file is the COMPLETE catch of errors.

--census marks every stored decision that appears in NO row (final or not) as correct, so the
denominator is right — same semantics as the gateway's sync and packs.outcomes_from_reversals.
"""
import csv
import re

from .core import STORE, report_outcome
from .persist import append_outcome

__all__ = ["map_rows", "record_mapped", "suggest_mapping", "parse_money", "import_csv"]

_KEY_COLUMNS = ("business_key", "invoice", "invoice_no", "invoice_number", "payment_intent",
                "charge", "charge_id", "order_id", "payment_id", "reference", "ref")
_STATUS_COLUMNS = ("status", "state", "resolution", "outcome", "disposition")
_LOSS_COLUMNS = ("loss", "amount", "amount_usd", "total", "total_amount", "value",
                 "realized_loss", "dispute_amount")


# commas are stripped ONLY as thousands separators ("1,400.00"); a decimal comma ("90,5")
# is ambiguous and refused — silently reading it as 905 would be a 10x loss error.
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def parse_money(value):
    """'$1,400.00' / '1400' / 1400.0 -> float; blank/ambiguous/unparsable -> None."""
    if value is None or isinstance(value, (int, float)):
        return None if value is None else float(value)
    s = str(value).strip().lstrip("$€£").strip()
    if not s:
        return None
    if "," in s:
        if not _THOUSANDS.match(s):
            return None
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def map_rows(rows, mapping, *, error_statuses=(), correct_statuses=(), source="recovery_audit",
             amount_divisor=1.0, all_errors=False, action_of=None):
    """Pure: export rows (dicts) -> (outcome rows, seen keys, skipped counts).

    mapping: {"business_key": <column>, "status": <column>?, "loss": <column>?}.
    Later rows for the same key overwrite earlier ones (last-wins, like the store).
    `seen` includes keys of non-final rows too — they must stay OUT of any census.
    `action_of(key)` supplies the recorded decision's action for correct rows."""
    action_of = action_of or (lambda key: "approve")
    outcomes, seen = {}, set()
    skipped = {"no_key": 0, "nonfinal": 0}
    for row in rows:
        key = str(row.get(mapping["business_key"]) or "").strip()
        if not key:
            skipped["no_key"] += 1
            continue
        seen.add(key)
        loss = parse_money(row.get(mapping["loss"])) if mapping.get("loss") else None
        loss = None if loss is None else loss / float(amount_divisor or 1.0)
        if all_errors or not mapping.get("status"):
            ground_truth = "reject"
        else:
            status = str(row.get(mapping["status"]) or "").strip()
            if status in error_statuses:
                ground_truth = "reject"
            elif status in correct_statuses:
                ground_truth, loss = action_of(key), 0.0
            else:
                skipped["nonfinal"] += 1
                continue
        loss = 0.0 if loss is None else loss
        outcomes[key] = {"business_key": key, "ground_truth": ground_truth, "source": source,
                         "realized_loss_usd": loss, "estimated_loss_usd": loss}
    return list(outcomes.values()), seen, skipped


def record_mapped(outcomes, seen, *, census=False, source="recovery_audit", store_path=None):
    """Record mapped outcomes into the store (+ JSONL). census=True additionally marks every
    decision that appeared in NO export row as correct. Returns counts."""
    n_census = 0
    for o in outcomes:
        report_outcome(**o)
        if store_path:
            append_outcome(o["business_key"], STORE.outcomes[o["business_key"]], store_path)
    if census:
        for key, d in list(STORE.decisions.items()):
            if key not in seen and key not in STORE.outcomes:
                report_outcome(key, ground_truth=d.action, source=source,
                               realized_loss_usd=0.0, estimated_loss_usd=0.0)
                if store_path:
                    append_outcome(key, STORE.outcomes[key], store_path)
                n_census += 1
    errors = sum(1 for o in outcomes if o["ground_truth"] == "reject")
    return {"errors": errors, "correct": len(outcomes) - errors, "census_correct": n_census}


def suggest_mapping(fieldnames, sample_rows=()):
    """Draft a --map from a file's header (+ observed statuses), init-style. Unresolvable
    fields come back as '_todo: ...' strings."""
    cols = {c.lower(): c for c in fieldnames}

    def pick(candidates):
        for cand in candidates:
            if cand in cols:
                return cols[cand]
        return None

    key = pick(_KEY_COLUMNS) or next(
        (cols[c] for c in cols if c.endswith("_id") and c != "id"), None)
    if key is None and "id" in cols:
        key = "_todo: 'id' is likely the reversal's own id — pick the column naming the " \
              "original decision (invoice / payment / order id)"
    mapping = {
        "business_key": key or "_todo: which column names the original decision?",
        "status": pick(_STATUS_COLUMNS) or "_todo: no status-like column; if every row is an "
                                           "error, use --all-errors instead",
        "loss": pick(_LOSS_COLUMNS) or "_todo: which column carries the dollar loss?",
    }
    status_col = mapping["status"] if not mapping["status"].startswith("_todo") else None
    observed = sorted({str(r.get(status_col, "")).strip()
                       for r in sample_rows if status_col and r.get(status_col)}) \
        if status_col else []
    return mapping, observed


def import_csv(path, mapping, **kw):
    """Convenience: read a CSV and map_rows + record_mapped in one call."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    census = kw.pop("census", False)
    store_path = kw.pop("store_path", None)
    action_of = lambda key: (STORE.decisions[key].action    # noqa: E731
                             if key in STORE.decisions else "approve")
    outcomes, seen, skipped = map_rows(rows, mapping, action_of=action_of, **kw)
    counts = record_mapped(outcomes, seen, census=census,
                           source=kw.get("source", "recovery_audit"), store_path=store_path)
    counts["skipped"] = skipped
    return counts
