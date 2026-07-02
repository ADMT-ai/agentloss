"""Underwriting submissions — export the audit record as the tabular data submission an
insurer's application process asks for.

Underwriters who insure agentic systems ask for historical performance data — typically
a year or more of records across customers and use cases, as a flat table of decisions
joined to ground truth with the financial loss per row. The audit record carries exactly
that: capture live through the gateway, or build the history retroactively with
`agentloss backfill`, then

    agentloss export --store s.jsonl --out submission.csv [--template insurer.json]

The exported FIELDS are fixed (they are the record's semantics); a template file maps
them onto a specific insurer's column headers and order, so one record serves any
application form without republishing anyone's paperwork:

    {"columns": [["Decision Time", "ts"], ["Client", "customer"],
                 ["Task", "use_case"], ["Agent Decision", "action"],
                 ["Correct Decision", "ground_truth"], ["Loss (USD)", "loss"]]}

One row per decision with an evidenced outcome (a decision the world has not yet ruled
on has no ground truth to submit). The loss field carries realized dollars for gold
outcomes and the estimated figure for silver ones, and correct decisions submit 0.00 —
the submission's denominator stays as honest as the report's.
"""
import csv
import json

from .core import STORE

__all__ = ["submission_rows", "write_submission_csv", "load_template",
           "DEFAULT_COLUMNS", "FIELDS"]

FIELDS = ("ts", "customer", "use_case", "action", "ground_truth", "loss")

DEFAULT_COLUMNS = (("timestamp", "ts"), ("customer_id", "customer"),
                   ("use_case", "use_case"), ("action", "action"),
                   ("ground_truth", "ground_truth"), ("expected_loss_usd", "loss"))


def load_template(path):
    """A template JSON file -> ((header, field), ...). Unknown fields are refused —
    a submission must never carry a column whose meaning the record can't back."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    columns = tuple((str(h), str(field)) for h, field in data["columns"])
    unknown = [field for _, field in columns if field not in FIELDS]
    if unknown:
        raise ValueError(f"unknown field(s) {unknown}; known: {FIELDS}")
    return columns


def submission_rows(columns=DEFAULT_COLUMNS, store=None):
    """The record as submission rows (list of tuples in `columns` order)."""
    store = store if store is not None else STORE
    rows = []
    for key, d in store.decisions.items():
        o = store.outcomes.get(key)
        if o is None:
            continue                    # unresolved: nothing to submit yet
        if o.ground_truth == d.action:
            loss = 0.0
        else:
            loss = (o.realized_loss_usd if o.realized_loss_usd is not None
                    else o.estimated_loss_usd) or 0.0
        values = {"ts": d.ts, "customer": d.customer, "use_case": d.use_case,
                  "action": d.action, "ground_truth": o.ground_truth,
                  "loss": f"{loss:.2f}"}
        rows.append(tuple(values[field] for _, field in columns))
    return rows


def write_submission_csv(path, columns=DEFAULT_COLUMNS, store=None):
    """Write the submission CSV; returns the number of data rows."""
    rows = submission_rows(columns, store)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([h for h, _ in columns])
        w.writerows(rows)
    return len(rows)
