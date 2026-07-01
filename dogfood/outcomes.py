"""Simulated outcome feeds (Tier A + delayed Tier B/C).

  * human_queue    — every hold/reject the agent routed to a human gets adjudicated by
                     the oracle (gold). Represents the exception review queue.
  * recovery_audit — after a delay, a fraction of TRUE escaped errors (agent approved but
                     the oracle says otherwise) are caught → gold + realized dollars.
"""
import agentaudit


def human_queue(stream_by_no, oracle):
    """Holds/rejects → human adjudication (gold)."""
    for key, d in agentaudit.STORE.decisions.items():
        if d.action in ("hold", "reject"):
            truth = oracle[key]["correct_action"]
            agentaudit.report_outcome(key, ground_truth=truth, source="human_queue", fidelity="gold")


def recovery_audit(oracle, cfg, rng):
    """Delayed catch of a fraction of true escapes → gold + realized loss."""
    for key, d in list(agentaudit.STORE.decisions.items()):
        if d.action != "approve":
            continue
        truth = oracle[key]
        if truth["correct_action"] == "approve":
            continue                      # not an error, nothing to catch
        if rng.random() >= cfg.audit_catch_rate:
            continue                      # missed by the audit (stays silent)
        loss = truth["true_loss_usd"]
        agentaudit.report_outcome(
            key,
            ground_truth=truth["correct_action"],
            source="recovery_audit",
            fidelity="gold",
            realized_loss_usd=loss,
            recovery_usd=round(loss * cfg.recovery_fraction, 2),
        )
