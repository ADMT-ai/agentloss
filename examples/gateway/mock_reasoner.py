"""A deterministic, DELIBERATELY FALLIBLE reasoning agent for the ladder eval.

Plays the role real Claude plays in production (AGENTLOSS_REASONER points here): judge a
support thread that the marker vocabulary can't read. Its rule is legible and its
failures are the oracle-known ones the eval needs:

- flags anything mentioning "processing mistake" -> catches the fraud thread (true
  positive) but ALSO the contested thread where the customer merely alleged one (false
  alarm), and MISSES the partial-refund thread worded as a "goodwill gesture";
- estimates dollars badly on purpose (700 for a 900 loss, 300 for a non-loss), so the
  eval can show raw silver dollars are biased and two-phase calibration corrects them.
"""


def reasoner(evidence, context):
    text = str(evidence or "").lower()
    if "ticket open" in text:
        return {"should_have_been": None}          # still unresolved
    if "processing mistake" in text:
        return {"should_have_been": "reject", "estimated_loss": 700.0
                if "confirmed" in text else 300.0, "confidence": 0.8}
    return {"should_have_been": "approve", "estimated_loss": 0.0, "confidence": 0.8}
