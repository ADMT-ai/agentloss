# Packs — capture consequential decisions off an existing distribution system

Most integration friction is two judgments: *which action do I instrument?* and *how do I get
ground truth?* A **pack** answers both for a known system by hooking where value moves and reading
where the world rules on it. If your consequential action goes through a known rail — a payment
SDK, an ERP client, an agent-tool protocol — don't hand-instrument; apply a pack.

A pack does two things:

1. **Capture the decision** by wrapping the money-mover / state-committer, so `value_at_risk` and
   `business_key` come for free from the call.
2. **Read ground truth** from that same system's *reversals* — disputes, chargebacks, refunds,
   credit-memos, corrections — as gold outcomes with the dollar loss attached.

## The primitives (`agentloss.packs`)

```python
from agentloss.packs import capture, outcomes_from_reversals

# 1) hook the money-mover
psp.refund = capture(psp.refund,
    amount_of=lambda customer_id, amount_usd: amount_usd,   # -> value_at_risk_usd
    key_of=lambda charge_id, customer_id, amount_usd: charge_id,  # -> business_key
    use_case="refunds")

# 2) ground truth from the rail's reversals (census=True marks the rest correct -> right rate too)
outcomes_from_reversals(disputed_ids, amount_by_id, source="chargeback")
agentloss.print_report()
```

`outcomes_from_reversals(..., census=False)` when the reversals are an *incomplete* catch (some
errors not yet surfaced) — then pair with `agentloss.sample_and_verify()` to estimate the tail.

## Shipped packs

- **Payment (generic)** — `capture` + `outcomes_from_reversals`. `examples/payment_pack.py`.
- **Stripe** — `agentloss.packs.stripe`: `instrument(stripe)` wraps `Charge`/`PaymentIntent`/`Refund`;
  disputes → gold via `outcomes_from_disputes(stripe)` (batch) or `handle_webhook_event(event)`
  (real-time, on `charge.dispute.created`). `pip install "agentloss[stripe]"`. `examples/stripe_pack_test.py`.

## Write your own pack

1. **Find the money-mover** — the one call that moves money or commits state (`stripe.Charge.create`,
   `erp.post_invoice`, a tool handler). Wrap it: `amount_of` → the exposure, `key_of` → a stable id.
2. **Find the reversal signal** — the record that says "that was wrong": a chargeback, a credit-memo
   (ERP debit note), a refund, a reopened ticket, a human correction. Map its target id + amount to
   `outcomes_from_reversals` (or `report_outcome`).
3. Confirm with `agentloss.doctor()`.

## Roadmap — distribution systems worth packing

| Distribution system | Money-mover (decision) | Reversal (gold ground truth) | Status |
|---|---|---|---|
| **Payment rails** — Stripe, PayPal, Adyen, Braintrust, and agent-payment protocols (AP2, x402) | charge / payment-intent / refund / payout | dispute · chargeback · refund | Stripe ✅; others = same shape |
| **ERPs** — ERPNext, NetSuite, SAP, QuickBooks | purchase invoice / payment entry | credit-memo · debit-note · reversal | ERPNext proven (dogfood adapter) |
| **Agent-tool protocols** — MCP tool calls, LangChain / CrewAI / OpenAI function tools | the consequential tool invocation | downstream correction / retry / human override | pattern maps via `capture` |
| **Business context layers** — Glean, MS Graph/Copilot (via MCP) | (context-in, not a money-mover) | **soft/unstructured outcomes** — a complaint email, a "that was wrong" in Slack, a reopened ticket | future "soft-outcome" pack |

The context-layer row is the odd one out: it's not a money-mover, it's a place to *harvest ground
truth for decisions whose outcome isn't a clean structured event* (support/knowledge agents). It
pairs with, rather than replaces, direct system-of-record packs — prefer standard interfaces (MCP)
so a pack works with any context layer, not one vendor.
