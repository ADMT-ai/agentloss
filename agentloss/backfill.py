"""Backfill — build the audit record RETROACTIVELY from a historical export.

The chicken-and-egg of insuring an agent: an underwriter prices from loss history, and a
newly deployed agent has none. But the system of record does — years of tickets, refunds,
and resolutions, in prose. Backfill reads a historical export (CSV) and produces the same
audit record live capture would have: one Decision per historical concession (the
`decider` column becomes the decision's `model`, so human history and agent history land
as SEGMENTS of one record), and one Outcome per row adjudicated from the evidence —

- a mapped `status` column with error/correct vocabularies -> gold (the export already
  ruled), same contract as `agentloss import`;
- else the `evidence` text, judged by the marker vocabulary or, when
  AGENTLOSS_REASONER=path.py:fn is set, a reasoning agent -> SILVER (estimated loss,
  confidence carried; calibrate against a QA gold budget for the honest number).

Readout: `agentloss underwrite --store s.jsonl --agent <decider> --baseline <decider>`
— day-one actuarial history plus the agent-vs-human incremental risk.
"""
import csv
import re

from .core import STORE, Decision, report_outcome
from .importer import parse_money
from .inference import infer_outcome, load_reasoner
from .persist import append_decision, append_outcome

__all__ = ["backfill_csv", "backfill_rows", "suggest_backfill_mapping"]

# mapping keys: business_key + amount are required; the rest optional
_KNOWN = ("business_key", "amount", "decider", "action", "evidence", "status",
          "customer", "ts")

# Column-name conventions of the exports people actually have (Zendesk, Intercom,
# Front, homegrown warehouse pulls), normalized: lowercase, non-alnum -> _.
# Order = priority. Bare "status" is deliberately ABSENT from the status synonyms:
# a ticket-workflow status (open/solved/closed) is not a ruling — only QA/review/audit
# verdict columns qualify.
_SYNONYMS = {
    "business_key": ("ticket_id", "conversation_id", "case_id", "refund_id",
                     "transaction_id", "ticket", "id"),
    "amount": ("refund_amount", "credit_amount", "concession_amount", "amount_refunded",
               "refund_total", "amount", "refund", "credit", "total", "value"),
    "decider": ("decider", "agent_name", "assignee", "admin_assignee", "assignee_name",
                "resolved_by", "handled_by", "agent", "owner", "author"),
    "action": ("action", "decision"),
    "evidence": ("resolution_notes", "resolution_note", "case_notes", "resolution",
                 "notes", "note", "comments", "comment", "transcript", "thread",
                 "body", "description", "summary"),
    "status": ("qa_status", "qa_verdict", "qa_outcome", "review_status",
               "review_outcome", "audit_status", "audit_outcome", "verdict"),
    "customer": ("customer_id", "customer", "requester_id", "requester", "user_id",
                 "account_id", "end_user"),
    "ts": ("timestamp", "created_at", "opened_at", "date", "created", "resolved_at",
           "closed_at"),
}
_AMOUNT_HINTS = ("amount", "refund", "credit", "value", "total")


def _norm(col):
    return re.sub(r"[^a-z0-9]+", "_", col.lower()).strip("_")


def _samples(rows, col, n=50):
    return [str(r[col]).strip() for r in rows[:n]
            if r.get(col) not in (None, "") and str(r[col]).strip()]


def _is_money_col(rows, col):
    vals = _samples(rows, col)
    return bool(vals) and all(parse_money(v) is not None for v in vals)


def _is_text_col(rows, col):
    vals = _samples(rows, col)
    return bool(vals) and any(" " in v for v in vals)


def suggest_backfill_mapping(fieldnames, sample_rows=()):
    """Draft a backfill --map from the export's own header (+ sample rows), the
    `gateway init` move for a file. Sample rows validate the guesses: an amount column
    must parse as money, an evidence column must read like text. Unresolvable required
    fields come back as '_todo: ...' strings; returns (mapping, notes)."""
    sample_rows = list(sample_rows)
    cols = {}                                   # normalized -> original, first wins
    for c in fieldnames or []:
        cols.setdefault(_norm(c), c)
    notes = []

    def pick(key, validate=None):
        for cand in _SYNONYMS[key]:
            col = cols.get(cand)
            if col is not None and (validate is None or not sample_rows
                                    or validate(sample_rows, col)):
                return col
        return None

    mapping = {}
    key = pick("business_key") or next(
        (orig for norm, orig in cols.items() if norm.endswith("_id")), None)
    mapping["business_key"] = key or "_todo: which column names the ticket/refund?"

    amount = pick("amount", _is_money_col)
    if amount is None and sample_rows:          # name hint + the samples parse as money
        amount = next((orig for norm, orig in cols.items()
                       if any(h in norm for h in _AMOUNT_HINTS)
                       and _is_money_col(sample_rows, orig)), None)
    mapping["amount"] = amount or "_todo: which column carries the concession amount?"

    for optional, validate in (("decider", None), ("action", None),
                               ("evidence", _is_text_col), ("status", None),
                               ("customer", None), ("ts", None)):
        col = pick(optional, validate)
        if col is not None:
            mapping[optional] = col
    if "evidence" not in mapping and "status" not in mapping:
        notes.append("no evidence or QA-verdict column found — every row would be "
                     "non-final; point evidence= at the resolution text.")
    if "decider" not in mapping:
        notes.append("no decider column found — all history lands in one segment "
                     "(no agent-vs-human baseline).")
    if "status" in mapping:
        observed = sorted(set(_samples(sample_rows, mapping["status"])))
        notes.append(f"observed {mapping['status']} values: {', '.join(observed)} — "
                     "pass --error-statuses / --correct-statuses from these.")
    return mapping, notes


def _money(value):
    if value in (None, ""):
        return None
    return parse_money(str(value))


def backfill_rows(rows, mapping, *, use_case="support_concession",
                  error_statuses=(), correct_statuses=(), source="recovery_audit",
                  default_action="grant", store_path=None):
    """Backfill from an iterable of dict rows. Returns counts. See backfill_csv."""
    for req in ("business_key", "amount"):
        if req not in mapping:
            raise ValueError(f"mapping must include {req}=<column>")
    unknown = set(mapping) - set(_KNOWN)
    if unknown:
        raise ValueError(f"unknown mapping key(s) {sorted(unknown)}; known: {_KNOWN}")
    reasoner = load_reasoner()
    counts = {"decisions": 0, "errors": 0, "correct": 0, "nonfinal": 0, "skipped": 0}
    for row in rows:
        key = row.get(mapping["business_key"])
        amount = _money(row.get(mapping["amount"]))
        if not key or amount is None:
            counts["skipped"] += 1
            continue
        key = str(key)
        action = str(row.get(mapping["action"], default_action) or default_action) \
            if "action" in mapping else default_action
        decider = str(row.get(mapping["decider"], "") or "unknown") \
            if "decider" in mapping else "unknown"
        customer = str(row.get(mapping["customer"], "") or "") \
            if "customer" in mapping else ""
        # historical time comes from the export itself, so the record IS the history
        ts = str(row.get(mapping["ts"], "") or "") if "ts" in mapping else ""
        d = STORE.record(Decision(action=action, value_at_risk_usd=amount,
                                  business_key=key, use_case=use_case, model=decider,
                                  customer=customer, ts=ts))
        if store_path:
            append_decision(d, store_path)
        counts["decisions"] += 1

        status = row.get(mapping["status"]) if "status" in mapping else None
        if status is not None and str(status).strip():
            status = str(status).strip()
            if status in error_statuses:
                _record(key, _contrary(action), source, realized=amount,
                        store_path=store_path)
                counts["errors"] += 1
            elif status in correct_statuses:
                _record(key, action, source, realized=0.0, store_path=store_path)
                counts["correct"] += 1
            else:
                counts["nonfinal"] += 1
            continue

        evidence = str(row.get(mapping["evidence"], "") or "") \
            if "evidence" in mapping else ""
        verdict = _adjudicate(evidence, amount, reasoner)
        if verdict is None:
            counts["nonfinal"] += 1
            continue
        wrongful, est, confidence = verdict
        _record(key, _contrary(action) if wrongful else action,
                "verification_agent" if reasoner else "inferred",
                estimated=est if wrongful else 0.0, confidence=confidence,
                store_path=store_path)
        counts["errors" if wrongful else "correct"] += 1
    return counts


def _contrary(action):
    """The ground truth of a wrongful decision: what should have happened instead."""
    return "deny" if action in ("grant", "partial", "approve") else "grant"


def _adjudicate(evidence, amount, reasoner):
    """The historical row's outcome, from its prose. None = non-final/unjudgeable."""
    if reasoner is not None:
        try:
            v = reasoner(evidence, {"value_at_risk": amount}) or {}
        except Exception:
            return None
        judgment = str(v.get("should_have_been") or "").lower()
        if judgment not in ("approve", "reject"):
            return None
        est = v.get("estimated_loss")
        try:
            est = None if est is None else float(est)
        except (TypeError, ValueError):
            est = None
        confidence = v.get("confidence")
        return (judgment == "reject", amount if est is None else est,
                0.7 if confidence is None else float(confidence))
    v = infer_outcome(evidence, value_at_risk=amount)
    if v["ground_truth"] is None:
        return None
    return v["ground_truth"] == "reject", v["estimated_loss_usd"], v["confidence"]


def _record(key, ground_truth, source, realized=None, estimated=None,
            confidence=1.0, store_path=None):
    silver = source in ("inferred", "verification_agent")
    report_outcome(key, ground_truth=ground_truth, source=source,
                   fidelity="silver" if silver else "gold", confidence=confidence,
                   realized_loss_usd=None if silver else realized,
                   estimated_loss_usd=estimated if silver else realized)
    if store_path:
        append_outcome(key, STORE.outcomes[key], store_path)


def backfill_csv(path, mapping, **kw):
    """Backfill the audit record from a CSV export.

    mapping: column names for business_key, amount (required), and decider, action,
    evidence, status (optional). With `status` + error/correct vocabularies the export's
    own rulings are gold; else `evidence` prose is adjudicated (markers, or the
    AGENTLOSS_REASONER agent) into silver outcomes. Returns counts."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return backfill_rows(csv.DictReader(f), mapping, **kw)
