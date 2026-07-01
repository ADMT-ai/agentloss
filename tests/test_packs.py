from agentloss.core import STORE
from agentloss.packs import capture, outcomes_from_reversals
from agentloss.packs.tools import instrument


def test_capture_records_decision_and_fails_open():
    def refund(charge_id, amount):
        return {"ok": True}

    wrapped = capture(refund, amount_of=lambda charge_id, amount: amount,
                      key_of=lambda res, charge_id, amount: charge_id,
                      use_case="refunds")
    assert wrapped("ch_1", 42.0) == {"ok": True}
    d = STORE.decisions["ch_1"]
    assert d.value_at_risk_usd == 42.0 and d.use_case == "refunds"

    # a broken extractor must never raise into the business call
    broken = capture(refund, amount_of=lambda **k: 1 / 0, key_of=lambda r, **k: "x")
    assert broken("ch_2", 1.0) == {"ok": True}
    assert "x" not in STORE.decisions


def test_outcomes_from_reversals_census():
    wrapped = capture(lambda cid, amt: cid, amount_of=lambda cid, amt: amt,
                      key_of=lambda res, cid, amt: cid)
    for cid, amt in [("ch_1", 10.0), ("ch_2", 20.0), ("ch_3", 30.0)]:
        wrapped(cid, amt)
    counts = outcomes_from_reversals(["ch_2"], {"ch_2": 20.0}, source="chargeback")
    assert counts == {"errors": 1, "correct": 2}
    assert STORE.outcomes["ch_2"].ground_truth == "reject"
    assert STORE.outcomes["ch_2"].realized_loss_usd == 20.0
    assert STORE.outcomes["ch_1"].ground_truth == "approve"


def test_tools_pack_instruments_only_consequential():
    calls = []
    tools = {
        "issue_refund": lambda **k: (calls.append("refund"), {"id": "r_1"})[1],
        "read_docs": lambda **k: (calls.append("read"), "docs")[1],
    }
    restore = instrument(tools, consequential={
        "issue_refund": {"amount_of": lambda **k: k["amount"],
                         "key_of": lambda res, **k: res["id"]},
    })
    tools["issue_refund"](amount=99.0)
    tools["read_docs"]()
    assert list(STORE.decisions) == ["r_1"]
    assert STORE.decisions["r_1"].value_at_risk_usd == 99.0
    restore()
    tools["issue_refund"](amount=5.0)  # restored: no longer captured
    assert list(STORE.decisions) == ["r_1"]
