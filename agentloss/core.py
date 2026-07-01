"""Core: decision capture + outcome store. Mirrors the `agentloss.*` decision/outcome
shapes from docs/SDK-SPEC.md (here as plain objects instead of OTel spans)."""
import itertools
from dataclasses import dataclass, field

_counter = itertools.count(1)


@dataclass
class Decision:
    action: str                 # approve | hold | reject
    value_at_risk_usd: float
    business_key: str           # invoice_no — the join key for delayed outcomes
    use_case: str = "ap_3way_match"
    model: str = "mock"
    in_envelope: bool = True
    decision_id: str = ""
    context: str = ""           # optional evidence for the verifier (agent input/output); local-only


@dataclass
class Outcome:
    ground_truth: str
    source: str                 # human_queue | verification_agent | recovery_audit
    fidelity: str               # gold | silver
    confidence: float = 1.0
    realized_loss_usd: float = None
    recovery_usd: float = None
    estimated_loss_usd: float = None
    sampled: bool = False       # included in the random rate-estimation sample?
    pi: float = None            # inclusion probability (for Horvitz-Thompson reweighting)


class Store:
    def __init__(self):
        self.decisions = {}     # business_key -> Decision
        self.outcomes = {}      # business_key -> Outcome

    def record(self, d: Decision) -> Decision:
        d.decision_id = f"d_{next(_counter)}"
        self.decisions[d.business_key] = d
        return d

    def add_outcome(self, business_key, **kw):
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
                   estimated_loss_usd=None, sampled=False, pi=None):
    STORE.add_outcome(business_key, ground_truth=ground_truth, source=source,
                      fidelity=fidelity, confidence=confidence,
                      realized_loss_usd=realized_loss_usd, recovery_usd=recovery_usd,
                      estimated_loss_usd=estimated_loss_usd, sampled=sampled, pi=pi)
