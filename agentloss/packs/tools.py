"""Tools pack — capture consequential decisions off an agent's tool layer (LangChain / CrewAI /
OpenAI function-calling / MCP). Instrument only the money-moving / state-committing tools out of a
large toolset; every other tool stays untouched.

    from agentloss.packs.tools import instrument

    # tools as {name: callable} (the universal shape — adapt your framework's toolset to this):
    restore = instrument(tools, consequential={
        "issue_refund": {"amount_of": lambda **k: k["amount"], "key_of": lambda res, **k: res["id"]},
        "place_order":  {"amount_of": lambda **k: k["total"],  "key_of": lambda res, **k: res["order_id"]},
    })
    # ... the agent runs; only issue_refund / place_order record decisions ...

`tools` may also be a list of tool objects (LangChain `Tool`, etc.); the pack finds each by `.name`
and wraps its callable (`.func` / `.fn` / `_run`, or pass `func_attr=`). Ground truth still comes
from the relevant reversal (a downstream correction / refund / dispute) via `report_outcome` /
`outcomes_from_reversals` — see docs/PACKS.md.
"""
from . import capture


def _bound_callable(tool, func_attr):
    """Return (get_fn, set_fn) to read/replace a tool object's callable, or (None, None)."""
    attrs = [func_attr] if func_attr else ["func", "fn", "_run", "run"]
    for attr in attrs:
        if attr and callable(getattr(tool, attr, None)):
            return getattr(tool, attr), (lambda a: lambda fn: setattr(tool, a, fn))(attr)
    return None, None


def _spec_capture(fn, spec, name):
    return capture(fn, amount_of=spec["amount_of"], key_of=spec["key_of"],
                   action=spec.get("action", "approve"), use_case=spec.get("use_case", name))


def instrument(tools, consequential, func_attr=None):
    """Wrap only the consequential tools so each call records a Decision. Returns `restore()`.

    consequential: {tool_name: {"amount_of": fn(*a,**k), "key_of": fn(result,*a,**k),
                                "action"?: str, "use_case"?: str}}
    """
    restores = []
    if isinstance(tools, dict):
        for name, spec in consequential.items():
            if name not in tools:
                continue
            orig = tools[name]
            tools[name] = _spec_capture(orig, spec, name)
            restores.append(lambda n=name, o=orig: tools.__setitem__(n, o))
    else:
        by_name = {}
        for t in tools:
            nm = getattr(t, "name", None) or getattr(t, "__name__", None)
            if nm:
                by_name[nm] = t
        for name, spec in consequential.items():
            t = by_name.get(name)
            if t is None:
                continue
            get_fn, set_fn = _bound_callable(t, func_attr)
            if set_fn is None:
                continue
            set_fn(_spec_capture(get_fn, spec, name))
            restores.append(lambda sf=set_fn, o=get_fn: sf(o))

    def restore():
        for r in restores:
            r()
    return restore
