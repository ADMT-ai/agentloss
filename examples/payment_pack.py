"""Payment pack demo: capture consequential decisions off a payment SDK (toy Stripe), with
disputes as gold ground truth — one line of instrumentation, no hand-wiring.

    python examples/payment_pack.py
"""
import random

import agentloss
from agentloss.packs import capture, outcomes_from_reversals


class ToyPSP:
    """Stands in for a payment SDK (Stripe / PayPal / an AP2 client)."""
    def refund(self, customer_id, amount_usd):
        return f"re_{customer_id}_{int(round(amount_usd * 100))}"


def main():
    agentloss.STORE.decisions.clear()
    agentloss.STORE.outcomes.clear()
    psp = ToyPSP()

    # ONE line applies the pack: every refund auto-records a decision (amount = exposure).
    psp.refund = capture(
        psp.refund,
        amount_of=lambda customer_id, amount_usd: amount_usd,
        key_of=lambda charge_id, customer_id, amount_usd: charge_id,
        action="approve", use_case="refunds")

    rng = random.Random(7)
    amount_by_key, disputed = {}, set()
    for i in range(500):
        amt = round(rng.uniform(20, 2000), 2)
        charge_id = psp.refund(f"c{i % 300:04d}", amt)      # <- business call; decision captured for free
        amount_by_key[charge_id] = amt
        if rng.random() < 0.06:                             # 6% later disputed (chargeback)
            disputed.add(charge_id)

    counts = outcomes_from_reversals(disputed, amount_by_key, source="chargeback")   # ground truth from the rail
    print(f"captured {len(agentloss.STORE.decisions)} decisions with zero hand-instrumentation; "
          f"{counts['errors']} disputed / {counts['correct']} clean")
    agentloss.print_report()


if __name__ == "__main__":
    main()
