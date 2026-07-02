"""Core: decision capture + outcome store. Mirrors the `agentloss.*` decision/outcome
shapes from docs/SDK-SPEC.md (here as plain objects instead of OTel spans)."""
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

_counter = itertools.count(1)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Decision:
    action: str                 # the action taken (any string); an error = outcome.ground_truth != action
    value_at_risk_usd: float    # per-decision exposure (amount; `_usd` is a legacy label — set `currency`)
    business_key: str           # the join key that late / cross-system outcomes are matched back on
    use_case: str = "ap_3way_match"
    model: str = "mock"
    in_envelope: bool = True
    decision_id: str = ""
    context: str = ""           # optional evidence for the verifier (agent input/output); local-only
    currency: str = "USD"       # display currency for the amounts (the amounts are in this currency)
    customer: str = ""          # the customer the decision concerned (underwriting submissions
                                # segment by customer; backfill maps it from the export)
    ts: str = ""                # when the decision was made (UTC ISO-8601). Set explicitly for
                                # backfilled history; stamped at record time otherwise.


@dataclass
class Outcome:
    ground_truth: str
    source: str                 # recovery_audit | dispute | chargeback | refund | human_queue | verification_agent | inferred
    fidelity: str               # gold | silver
    confidence: float = 1.0
    realized_loss_usd: float = None
    recovery_usd: float = None
    estimated_loss_usd: float = None
    sampled: bool = False       # included in the random rate-estimation sample?
    pi: float = None            # inclusion probability (for Horvitz-Thompson reweighting)
    ts: str = ""                # when the outcome resolved/was recorded (UTC ISO-8601)


class Store:
    def __init__(self):
        self.decisions = {}     # business_key -> Decision
        self.outcomes = {}      # business_key -> Outcome

    def record(self, d: Decision, stamp: bool = True) -> Decision:
        """stamp=True (live capture): a missing ts is stamped now. stamp=False
        (backfill): a historical row with no date stays timestampless — an absent
        time is reported absent, never fabricated as today."""
        d.decision_id = f"d_{next(_counter)}"
        if stamp and not d.ts:
            d.ts = _now()
        self.decisions[d.business_key] = d
        return d

    def add_outcome(self, business_key, **kw):
        kw.setdefault("ts", _now())
        self.outcomes[business_key] = Outcome(**kw)

    def has_gold(self, business_key):
        o = self.outcomes.get(business_key)
        return o is not None and o.fidelity == "gold"


STORE = Store()


def decision(fn):
    """Wrap a function that returns a Decision; record it. The SDK's `@decision`."""
    def wrap(*a, **k):
        return STORE.record(fn(*a, **k))
    return wrap


def report_outcome(business_key, ground_truth, source, fidelity="gold",
                   confidence=1.0, realized_loss_usd=None, recovery_usd=None,
                   estimated_loss_usd=None, sampled=True, pi=1.0):
    """Record a resolved outcome for a captured decision.

    Defaults assume you ALREADY HAVE the ground truth for this decision — the common
    case — so it counts toward the error rate and dollar loss with no extra flags
    (`sampled=True, pi=1.0` = a census observation). The active sampler overrides both
    explicitly when it draws a random rate-estimation sample, so its Horvitz-Thompson
    reweighting stays correct. Pass `sampled=False` only if this outcome is a biased,
    partial catch (e.g. an audit that surfaces errors but not correct decisions) that
    must NOT be treated as a random sample of the population."""
    STORE.add_outcome(business_key, ground_truth=ground_truth, source=source,
                      fidelity=fidelity, confidence=confidence,
                      realized_loss_usd=realized_loss_usd, recovery_usd=recovery_usd,
                      estimated_loss_usd=estimated_loss_usd, sampled=sampled, pi=pi)


def record_outcomes(rows):
    """Batch-record outcomes you already have — e.g. a join against a disputes/chargebacks
    table — as a one-liner. `rows` is an iterable of dicts (or (business_key, dict) pairs)
    with the same keys as `report_outcome`. Each row is a census observation by default
    (counts toward the number). Returns the count recorded.

        agentloss.record_outcomes([
            {"business_key": "R-1", "ground_truth": "reject",
             "source": "chargeback", "realized_loss_usd": 80.0},
            {"business_key": "R-2", "ground_truth": "approve", "source": "dispute"},
        ])
    """
    n = 0
    for row in rows:
        if isinstance(row, (tuple, list)) and len(row) == 2 and isinstance(row[1], dict):
            key, kw = row[0], dict(row[1])
            kw.setdefault("business_key", key)
        else:
            kw = dict(row)
        report_outcome(**kw)
        n += 1
    return n
