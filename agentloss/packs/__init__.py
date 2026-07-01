"""Packs — capture consequential decisions off an existing distribution system.

Instead of hand-instrumenting, hook a known money-mover / state-committer (a payment SDK, an
ERP client, an agent tool) so each call auto-records a Decision, and read that same system's
reversals (disputes / chargebacks / refunds / credit-memos) as gold ground truth. This collapses
the two hardest integration judgments — *which action?* and *how do I get ground truth?* — to zero
for anything on a known rail.

    import agentloss
    from agentloss.packs import capture, outcomes_from_reversals

    # 1) hook the money-mover: every refund now records a decision (amount = value-at-risk)
    psp.refund = capture(psp.refund,
        amount_of=lambda customer_id, amount_usd: amount_usd,
        key_of=lambda charge_id, customer_id, amount_usd: charge_id,
        use_case="refunds")

    # ... your agent runs and issues refunds ...

    # 2) ground truth straight from the rail's disputes
    outcomes_from_reversals(disputed_charge_ids, amount_by_charge_id, source="chargeback")
    agentloss.print_report()          # error rate + dollar loss
"""
import functools

from ..core import STORE, Decision, report_outcome

__all__ = ["capture", "outcomes_from_reversals"]


def capture(fn, *, amount_of, key_of, action="approve", use_case="pack"):
    """Wrap a money-moving / state-committing callable so each call records a Decision.

    amount_of(*a, **k) -> value_at_risk_usd (the exposure of this action)
    key_of(result, *a, **k) -> business_key (stable id outcomes can be joined on)

    Instrumentation never raises into the business call.
    """
    @functools.wraps(fn)
    def wrapped(*a, **k):
        result = fn(*a, **k)
        try:
            STORE.record(Decision(
                action=action,
                value_at_risk_usd=float(amount_of(*a, **k)),
                business_key=str(key_of(result, *a, **k)),
                use_case=use_case))
        except Exception:
            pass
        return result
    return wrapped


def outcomes_from_reversals(reversed_keys, amount_by_key=None, *, source="dispute", census=True):
    """Record ground truth from a distribution system's reversals.

    A reversal (dispute / chargeback / refund / credit-memo) is gold ground truth that the
    original decision was wrong — recorded with its dollar loss.

    census=True (default) ALSO marks every *other* captured decision as correct, so the error
    rate has the right denominator when the reversals are the complete set of errors. If some
    errors are not yet caught, pass census=False and use `agentloss.sample_and_verify()` to
    estimate the uncaught tail. Returns {"errors": n, "correct": n}.
    """
    reversed_set = {str(k) for k in reversed_keys}
    amounts = {str(k): v for k, v in (amount_by_key or {}).items()}
    n_err = n_ok = 0
    keys = list(STORE.decisions) if census else list(reversed_set)
    for key in keys:
        if key in reversed_set:
            loss = float(amounts.get(key, 0) or 0)
            report_outcome(key, ground_truth="reject", source=source, fidelity="gold",
                           realized_loss_usd=loss, estimated_loss_usd=loss)
            n_err += 1
        elif census:
            report_outcome(key, ground_truth="approve", source=source, fidelity="gold",
                           realized_loss_usd=0.0, estimated_loss_usd=0.0)
            n_ok += 1
    return {"errors": n_err, "correct": n_ok}
