"""Offline test of the default LLM verifier — with a mock LLM, so no API key needed.

    python examples/verifier_offline_test.py
"""
from agentloss import STORE, Decision, llm_verifier, sample_and_verify, report


def mock_complete(prompt):
    """Stand-in for the LLM: flag a decision whose context mentions a duplicate."""
    if "DUPLICATE" in prompt:
        return 'here is my verdict: {"should_have_been":"reject","confidence":0.9,"estimated_loss":2000}'
    return '{"should_have_been":"approve","confidence":0.92,"estimated_loss":0}'


def test_verifier_logic():
    v = llm_verifier(complete=mock_complete)
    good = Decision(action="approve", value_at_risk_usd=1000, business_key="INV1", context="normal invoice")
    dup = Decision(action="approve", value_at_risk_usd=2000, business_key="INV2", context="a DUPLICATE of INV1")
    assert v(good) == {"should_have_been": "approve", "confidence": 0.92, "estimated_loss": 0.0}
    assert v(dup) == {"should_have_been": "reject", "confidence": 0.9, "estimated_loss": 2000.0}

    # bad JSON -> safe fallback (never inflates the error rate)
    assert llm_verifier(complete=lambda p: "sorry, no idea")(good)["should_have_been"] == "approve"


def test_default_path_end_to_end():
    STORE.decisions.clear(); STORE.outcomes.clear()
    STORE.record(Decision(action="approve", value_at_risk_usd=1000, business_key="INV1", context="ok"))
    STORE.record(Decision(action="approve", value_at_risk_usd=2000, business_key="INV2", context="a DUPLICATE"))
    sample_and_verify(llm_verifier(complete=mock_complete), target_n=10)
    r = report()
    assert r["decisions"] == 2 and r["sampled"] == 2
    assert r["expected_loss_usd"] > 0     # the duplicate was caught


if __name__ == "__main__":
    test_verifier_logic()
    test_default_path_end_to_end()
    print("default LLM verifier offline logic: OK")
