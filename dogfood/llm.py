"""LLM interface with a deterministic Mock and a real Claude path.

Both receive the SAME evidence dict, gathered by the agent (limited) or the verifier
(thorough). The realism comes from the evidence asymmetry, not the model — so swapping
in Claude changes fidelity without changing the loop.
"""
import json
import os


class MockLLM:
    """Deterministic reasoning over provided evidence."""

    def decide(self, ev):
        if ev["vendor_off_master"]:
            return "reject", "vendor not on master"
        if ev["exact_dup"]:
            return "reject", "exact duplicate in 90d"
        if ev["po_overbill"]:
            return "hold", "billed above PO price"
        if ev["qty_over"]:
            return "hold", "billed qty exceeds receipt"
        if ev["false_trap_heuristic"]:
            return "hold", "new vendor, round amount"
        return "approve", "3-way match ok"

    def verify(self, ev):
        vr = ev["vr"]
        if not vr["on_master"]:
            return _v("reject", 0.95, "vendor_risk", ev["amount"])
        if ev["bank_changed"]:
            return _v("reject", 0.88, "vendor_risk", ev["amount"])
        if ev["fuzzy_full"]:
            return _v("reject", 0.95, "duplicate", ev["amount"])
        if ev["contract_overbill"]:
            return _v("hold", 0.9, "overpay", ev["overbill_amt"])
        if ev["qty_over"]:
            return _v("hold", 0.9, "qty", ev["qty_amt"])
        if ev["fuzzy_partial"]:
            return _v("hold", 0.4, "ambiguous_duplicate", ev["amount"] * 0.5)  # low conf → escalate
        return _v("approve", 0.92, None, 0.0)


def _v(should, conf, failed, loss):
    return {"should_have_been": should, "confidence": conf,
            "failed_check": failed, "estimated_loss": round(float(loss), 2)}


_DECIDE_PROMPT = """You are an accounts-payable approval agent. Given the evidence, decide
one of: approve, hold, reject. Respond ONLY with JSON: {"action": "approve|hold|reject", "reason": "..."}.
Evidence:
"""

_VERIFY_PROMPT = """You are an accounts-payable verification auditor. Automated checks were
already run against full invoice history and contract data; their RESULTS are the boolean/number
fields in the evidence below. Adjudicate based ONLY on those results.

DEFAULT TO APPROVE. Flag an invoice only when one of these specific triggers is set. First match wins:
- vr.on_master == false      -> reject, failed_check "vendor_risk",         estimated_loss = amount
- bank_changed == true       -> reject, failed_check "vendor_risk",         estimated_loss = amount
- fuzzy_full == true         -> reject, failed_check "duplicate",           estimated_loss = amount
- contract_overbill == true  -> hold,   failed_check "overpay",             estimated_loss = overbill_amt
- qty_over == true           -> hold,   failed_check "qty",                 estimated_loss = qty_amt
- fuzzy_partial == true      -> hold (confidence ~0.4), failed_check "ambiguous_duplicate", estimated_loss = amount/2
- none of the above set      -> approve, failed_check null, estimated_loss 0, confidence ~0.9

Do NOT invent problems. A large amount, a vendor name, or recently_added being true are NOT reasons
to flag. If every trigger field above is false, you MUST approve.

Respond ONLY with JSON:
{"should_have_been": "approve|hold|reject", "confidence": 0.0, "failed_check": "reason or null", "estimated_loss": 0}.
Evidence:
"""


class ClaudeLLM:
    def __init__(self, model=None):
        import anthropic  # requires `pip install anthropic` and ANTHROPIC_API_KEY
        self.client = anthropic.Anthropic()
        # same model for agent + verifier: the asymmetry we're testing is EVIDENCE, not capability.
        self.model = model or os.environ.get("AILOSS_MODEL", "claude-sonnet-4-6")

    def _ask(self, prompt):
        msg = self.client.messages.create(
            model=self.model, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        return json.loads(text[text.find("{"): text.rfind("}") + 1])

    def decide(self, ev):
        r = self._ask(_DECIDE_PROMPT + json.dumps(ev, indent=2))
        return r["action"], r.get("reason", "")

    def verify(self, ev):
        r = self._ask(_VERIFY_PROMPT + json.dumps(ev, indent=2))
        return {"should_have_been": r["should_have_been"], "confidence": float(r["confidence"]),
                "failed_check": r.get("failed_check"), "estimated_loss": float(r.get("estimated_loss", 0))}


def get_llm(mode):
    if mode == "claude":
        return ClaudeLLM()
    return MockLLM()
