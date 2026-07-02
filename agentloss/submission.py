"""Underwriting submissions — render the audit record in the format an insurer's own
data-submission requirements ask for.

First format: **Munich Re aiSure (Agentic AI)**. Its risk-assessment questionnaire
requires "historical agent performance data … at least 1 year of records" in a fixed
template — Timestamp, Customer ID, Use Case ID, Agent Output / Action, Ground Truth /
Expected Outcome, Financial Loss (US$; expected loss). That template is the agentloss
record, column for column: capture live through the gateway, or build the year of
history retroactively with `agentloss backfill`, then

    agentloss export --format aisure --store s.jsonl --out submission.csv

One row per decision with an evidenced outcome (a decision the world has not yet ruled
on has no ground truth to submit). The loss column carries realized dollars for gold
outcomes and the estimated figure for silver ones — the insurer's template itself says
"expected loss" — and correct decisions submit 0.00, which keeps the denominator
honest in the submission exactly as it is in the report.
"""
import csv

from .core import STORE

__all__ = ["aisure_rows", "write_aisure_csv", "AISURE_HEADER"]

AISURE_HEADER = ("Timestamp", "Customer ID", "Use Case ID", "Agent Output / Action",
                 "Ground Truth / Expected Outcome",
                 "Financial Loss (US$; expected loss)")


def aisure_rows(store=None):
    """The record as Munich Re aiSure submission rows (list of tuples, header order)."""
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
        rows.append((d.ts, d.customer, d.use_case, d.action, o.ground_truth,
                     f"{loss:.2f}"))
    return rows


def write_aisure_csv(path, store=None):
    """Write the submission CSV; returns the number of data rows."""
    rows = aisure_rows(store)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(AISURE_HEADER)
        w.writerows(rows)
    return len(rows)
