"""Offline test of the tools pack — instrument only the consequential tools in a toolset.

    python examples/tools_pack_test.py
"""
import agentloss
from agentloss.packs.tools import instrument


def test_dict_toolset():
    agentloss.STORE.decisions.clear(); agentloss.STORE.outcomes.clear()
    tools = {
        "issue_refund": lambda amount, customer: {"id": f"re_{customer}", "amount": amount},
        "place_order": lambda total, order_id: {"order_id": order_id, "total": total},
        "search_docs": lambda q: ["doc1", "doc2"],            # NOT consequential -> untouched
    }
    restore = instrument(tools, consequential={
        "issue_refund": {"amount_of": lambda amount, customer: amount,
                         "key_of": lambda res, amount, customer: res["id"]},
        "place_order": {"amount_of": lambda total, order_id: total,
                        "key_of": lambda res, total, order_id: res["order_id"]},
    })
    tools["issue_refund"](amount=120.0, customer="c1")
    tools["place_order"](total=500.0, order_id="o1")
    tools["search_docs"](q="hello")                           # must NOT capture

    d = agentloss.STORE.decisions
    assert len(d) == 2, len(d)
    assert d["re_c1"].value_at_risk_usd == 120.0 and d["re_c1"].use_case == "issue_refund"
    assert d["o1"].value_at_risk_usd == 500.0

    restore()
    tools["issue_refund"](amount=1.0, customer="c2")          # restored -> no capture
    assert len(agentloss.STORE.decisions) == 2


def test_object_toolset():
    agentloss.STORE.decisions.clear(); agentloss.STORE.outcomes.clear()

    class Tool:                                               # LangChain-ish: .name + .func
        def __init__(self, name, func):
            self.name, self.func = name, func

    tools = [
        Tool("charge", lambda amount, cust: {"id": f"ch_{cust}", "amount": amount}),
        Tool("noop", lambda: None),
    ]
    instrument(tools, consequential={
        "charge": {"amount_of": lambda amount, cust: amount,
                   "key_of": lambda res, amount, cust: res["id"]},
    })
    tools[0].func(amount=99.0, cust="x")
    assert agentloss.STORE.decisions["ch_x"].value_at_risk_usd == 99.0


if __name__ == "__main__":
    test_dict_toolset()
    test_object_toolset()
    print("tools pack offline logic: OK")
