"""Offline test of the Stripe pack — with a MOCK stripe module, so no account/keys needed.

    python examples/stripe_pack_test.py
"""
import random

import agentloss
from agentloss.packs import stripe as sp


def make_fake_stripe():
    class Res:
        def __init__(self, prefix):
            self.prefix, self.n = prefix, 0

        def create(self, **k):
            self.n += 1
            return {"id": f"{self.prefix}_{self.n:05d}", "amount": k.get("amount", 0), "currency": "usd"}

    class S:
        Charge = Res("ch")
        PaymentIntent = Res("pi")
        Refund = Res("re")

        class Dispute:
            data = []

            @classmethod
            def list(cls, limit=100):
                return {"data": cls.data[:limit]}

    return S


def test_pure():
    assert sp._amount_usd({"amount": 2500}) == 25.0
    assert sp._obj_id({"id": "ch_1"}) == "ch_1"
    assert sp._dispute_target({"charge": "ch_9", "amount": 1200}) == ("ch_9", 12.0)


def test_capture_and_disputes():
    agentloss.STORE.decisions.clear(); agentloss.STORE.outcomes.clear()
    S = make_fake_stripe()
    restore = sp.instrument(S)                       # wrap Charge/PaymentIntent/Refund .create

    rng = random.Random(7)
    disputed_loss = 0.0
    for i in range(300):
        cents = rng.randint(1000, 200000)            # $10–$2000
        ch = S.Charge.create(amount=cents, currency="usd", customer=f"cus_{i}")   # decision captured for free
        if rng.random() < 0.06:                      # 6% later disputed
            S.Dispute.data.append({"id": f"dp_{i}", "charge": ch["id"], "amount": cents,
                                   "status": "lost", "currency": "usd", "reason": "fraudulent"})
            disputed_loss += cents / 100.0

    assert len(agentloss.STORE.decisions) == 300
    counts = sp.outcomes_from_disputes(S, census=True)     # disputes are the complete error set here
    r = agentloss.report()
    assert counts["errors"] == len(S.Dispute.data)
    assert abs(r["realized_loss_usd"] - disputed_loss) < 0.01
    assert 0.03 < r["error_rate"] < 0.10                   # ~6%
    restore()

    # real-time webhook path records the same kind of gold outcome
    agentloss.STORE.outcomes.clear()
    ok = sp.handle_webhook_event({"type": "charge.dispute.created",
                                  "data": {"object": {"id": "dp_x", "charge": "ch_00001", "amount": 5000}}})
    assert ok and agentloss.STORE.outcomes["ch_00001"].realized_loss_usd == 50.0


if __name__ == "__main__":
    test_pure()
    test_capture_and_disputes()
    print("stripe pack offline logic: OK")
