"""Outcome inference — when the system of record has no `status` enum to look up.

Many SoRs never say "lost" / "won" in a field: the resolution lives in free text (a case
note, a complaint thread, an adjustment memo), and the dollar figure may be missing
entirely. This module is the gateway's "soft outcomes" path (docs/GATEWAY.md roadmap):
**infer the outcome, estimate the loss** — deterministically and transparently, so the
plumbing is oracle-eval'd and every verdict is explainable.

Two judgments per row of evidence:

1. **Outcome** — match the text against a marker vocabulary (resolution language, not
   sentiment): error markers ("chargeback lost", "clawed back", "refunded", ...) vs
   correct markers ("in merchant favor", "no merchant error", ...). Neither matching
   means NON-FINAL — unknown, skipped, out of any census. When both sides match (a
   chargeback that was then won), the marker appearing LAST in the text wins: resolution
   language concludes the note.
2. **Loss** — for an error, in order of fidelity: an explicit amount column if the SoR
   has one; else the first dollar amount written in the evidence ("refunded $120.00" —
   partial losses read correctly); else the decision's own value-at-risk (full exposure,
   the conservative bound).

Inferred verdicts are **silver**: record them with `fidelity="silver"` and the loss as
`estimated_loss_usd` (never realized), so they flow through expected loss and can be
bias-corrected by sampling + two-phase calibration exactly like a fallible verifier's
labels (docs/SDK-SPEC.md). An LLM reasoner (`detectors.reasoning`) slots into the same
row shape when marker vocabulary isn't enough; this module is the rung below it — no
model, no network, same contract.
"""
import re

__all__ = ["infer_outcome", "infer_outcomes", "parse_money",
           "DEFAULT_ERROR_MARKERS", "DEFAULT_CORRECT_MARKERS"]

# Resolution language meaning THE DECISION WAS WRONG (money came back out).
DEFAULT_ERROR_MARKERS = (
    "chargeback lost", "dispute lost", "lost the dispute", "clawed back", "claw back",
    "charged back", "refunded", "refund issued", "reversed", "reversal issued",
    "complaint upheld", "upheld against", "charged in error", "billed in error",
    "wrongly charged", "should not have been approved", "should have been blocked",
    "fraudulent", "written off", "credit memo issued", "goodwill credit",
)

# Resolution language meaning THE DECISION STOOD (resolved in the agent's favor).
DEFAULT_CORRECT_MARKERS = (
    "dispute won", "chargeback won", "won the dispute", "in merchant favor",
    "in our favor", "no merchant error", "no error found", "complaint withdrawn",
    "complaint dismissed", "case closed - no action", "no action needed",
    "resolved - charge stands", "charge stands", "correctly approved", "verified correct",
)

# A dollar amount written in text: requires an explicit currency marker ($ or USD) so
# ids/dates never read as money. Thousands separators OK; a DECIMAL comma ("1,23") is
# refused rather than misread 10x — the same caution as `agentloss import`.
_MONEY_RE = re.compile(r"(?:\$\s?|usd\s+)(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_DECIMAL_COMMA_RE = re.compile(r"^\d+(?:,\d{3})*,\d{1,2}$")

_DEFAULT_ERROR_LOWER = tuple(m.lower() for m in DEFAULT_ERROR_MARKERS)
_DEFAULT_CORRECT_LOWER = tuple(m.lower() for m in DEFAULT_CORRECT_MARKERS)


def _to_money(token):
    if _DECIMAL_COMMA_RE.match(token):
        return None
    return float(token.replace(",", ""))


def parse_money(text, near=None):
    """An explicit dollar amount in free text, or None. With `near` (a character
    position — the end of the resolution marker), prefer the first amount at or after
    it, then the closest one before it: the number NEXT TO "refunded" is the loss, not
    the transaction amount the note opened with."""
    matches = [(m.start(), _to_money(m.group(1))) for m in _MONEY_RE.finditer(text or "")]
    matches = [(pos, val) for pos, val in matches if val is not None]
    if not matches:
        return None
    if near is not None:
        after = [val for pos, val in matches if pos >= near]
        if after:
            return after[0]
        return matches[-1][1]              # nearest before the marker
    return matches[0][1]


def _last_match(text, markers):
    """Position just past the last occurrence of any marker, or -1."""
    pos = -1
    for marker in markers:
        i = text.rfind(marker)
        if i >= 0:
            pos = max(pos, i + len(marker))
    return pos


def infer_outcome(evidence, *, value_at_risk=None, loss=None,
                  error_markers=None, correct_markers=None):
    """Infer one outcome from free-text evidence. Returns a verdict dict:

        {"ground_truth": "reject" | "approve" | None,   # None = non-final (unknown)
         "estimated_loss_usd": float,                    # 0.0 unless an error
         "confidence": float,
         "loss_basis": "explicit" | "parsed" | "value_at_risk" | None}

    `loss` is an explicit amount if the SoR row carries one; `value_at_risk` is the
    joined decision's exposure (the conservative fallback when no figure exists).
    """
    text = str(evidence or "").lower()
    err = _last_match(text, tuple(m.lower() for m in error_markers)
                      if error_markers else _DEFAULT_ERROR_LOWER)
    ok = _last_match(text, tuple(m.lower() for m in correct_markers)
                     if correct_markers else _DEFAULT_CORRECT_LOWER)
    if err < 0 and ok < 0:
        return {"ground_truth": None, "estimated_loss_usd": 0.0,
                "confidence": 0.0, "loss_basis": None}
    confidence = 0.9 if (err < 0 or ok < 0) else 0.7   # both sides matched -> less sure
    if ok >= err:                                       # resolution language concludes
        return {"ground_truth": "approve", "estimated_loss_usd": 0.0,
                "confidence": confidence, "loss_basis": None}
    if loss is not None:
        est, basis = float(loss), "explicit"
    else:
        parsed = parse_money(text, near=err)
        if parsed is not None:
            est, basis = parsed, "parsed"
        elif value_at_risk is not None:
            est, basis = float(value_at_risk), "value_at_risk"
            confidence = min(confidence, 0.7)           # full exposure is a bound, not a read
        else:
            est, basis = 0.0, None
    return {"ground_truth": "reject", "estimated_loss_usd": est,
            "confidence": confidence, "loss_basis": basis}


def infer_outcomes(items, *, error_markers=None, correct_markers=None, source="inferred"):
    """Batch: `(business_key, evidence[, value_at_risk])` tuples -> outcome rows in the
    detector shape (see detectors/), skipping non-final rows. Silver by construction."""
    rows = []
    for item in items:
        key, evidence, var = (item if len(item) == 3 else (*item, None))
        v = infer_outcome(evidence, value_at_risk=var,
                          error_markers=error_markers, correct_markers=correct_markers)
        if v["ground_truth"] is None:
            continue
        rows.append({
            "business_key": str(key),
            "ground_truth": v["ground_truth"],
            "estimated_loss_usd": v["estimated_loss_usd"],
            "source": source,
            "fidelity": "silver",
            "confidence": v["confidence"],
        })
    return rows
