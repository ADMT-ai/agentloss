"""Stripe pack — capture consequential decisions off the Stripe SDK, with disputes as gold
ground truth (a chargeback = "that charge was wrong").

Built to the Stripe Python SDK API; live-verify against a real account (like the Phoenix
connector). The pure mapping + `instrument()` + `handle_webhook_event()` are offline-tested with
a mock stripe module in `examples/stripe_pack_test.py`.

    import stripe, agentloss
    from agentloss.packs import stripe as sp

    restore = sp.instrument(stripe)                 # Charge/PaymentIntent/Refund .create -> capture decisions
    # ... your agent charges / refunds via stripe (decisions recorded automatically) ...

    # ground truth, either way:
    sp.outcomes_from_disputes(stripe)               # batch: pull disputes -> gold outcomes
    #   or, real-time in your webhook endpoint:
    #   sp.handle_webhook_event(event)              # on 'charge.dispute.created'
    agentloss.print_report()

Key your captured decisions on the CHARGE id (the default — the created object's id) so disputes,
which reference a charge, join cleanly. Stripe amounts are in the smallest currency unit (cents).
"""
import functools

from ..core import STORE, Decision, report_outcome

_MONEY_MOVERS = ("Charge", "PaymentIntent", "Refund")


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _amount_usd(obj):
    try:
        return float(_get(obj, "amount", 0) or 0) / 100.0      # cents -> currency units
    except (TypeError, ValueError):
        return 0.0


def _obj_id(obj):
    return str(_get(obj, "id", "") or "")


def instrument(stripe, action="approve", use_case="stripe"):
    """Wrap Stripe's money-moving `.create` methods so each successful call records a Decision
    (value-at-risk = amount, business_key = the created object's id). Returns a `restore()`."""
    originals = {}
    for name in _MONEY_MOVERS:
        resource = getattr(stripe, name, None)
        if resource is None or not hasattr(resource, "create"):
            continue
        orig = resource.create
        originals[name] = (resource, orig)

        def make(orig_fn, uc):
            @functools.wraps(orig_fn)
            def wrapped(*a, **k):
                obj = orig_fn(*a, **k)
                try:
                    STORE.record(Decision(action=action, value_at_risk_usd=_amount_usd(obj),
                                          business_key=_obj_id(obj), use_case=uc))
                except Exception:
                    pass
                return obj
            return wrapped

        resource.create = make(orig, use_case)

    def restore():
        for _name, (resource, orig) in originals.items():
            resource.create = orig
    return restore


def _dispute_target(dispute):
    """(charge_id, loss_usd) for a Stripe dispute — pure, offline-testable."""
    return str(_get(dispute, "charge", "") or ""), _amount_usd(dispute)


def outcomes_from_disputes(stripe, limit=100, source="dispute", census=False,
                           attributable_reasons=None, include_pending=False):
    """Pull Stripe disputes and record each as a gold outcome — hardened via the chargeback detector
    (`agentloss.detectors.stripe`): a WON dispute is NOT a loss, amounts are currency-correct (incl.
    zero-decimal currencies), `attributable_reasons` gates agent-error attribution, pending disputes
    are skipped (unless `include_pending`), and multiple records per charge are deduped.

    census=False (default): disputes are typically an INCOMPLETE catch (not every bad charge is
    disputed, and they lag), so this records only resolved disputes — pair with
    `agentloss.sample_and_verify()` for the rate. census=True marks every other captured decision
    correct (only when disputes are the complete error set)."""
    from ..detectors import stripe as detector
    rows = detector.detect(stripe, limit=limit, source=source,
                           attributable_reasons=attributable_reasons, include_pending=include_pending)
    return detector.record(rows, census=census, source=source)


def handle_webhook_event(event, source="dispute"):
    """Handle a Stripe webhook event in real time. On `charge.dispute.created`, record a gold
    wrong-decision outcome on the disputed charge. Returns True if it recorded one."""
    if _get(event, "type") != "charge.dispute.created":
        return False
    dispute = _get(_get(event, "data", {}) or {}, "object", {}) or {}
    charge, loss = _dispute_target(dispute)
    if not charge:
        return False
    report_outcome(charge, ground_truth="reject", source=source, fidelity="gold",
                   realized_loss_usd=loss, estimated_loss_usd=loss)
    return True
