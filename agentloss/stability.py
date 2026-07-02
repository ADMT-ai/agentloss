"""Accumulation and stability — the loss DYNAMICS an underwriter prices, not just the
totals.

Two questions the flat record doesn't answer by itself:

1. **Accumulation** — agentic failures are correlated: a bad model update or a viral
   exploit produces a burst of wrongful decisions, not independent ones. Policies are
   structured per LOSS EVENT, so the record must show its own clustering: wrongful
   decisions within `window_hours` of each other chain into one event, and the rolling
   24h/7d aggregates bound the tail ("the worst day this history contains").
2. **Stability** — a price assumes the assessed loss rate still holds. The record's own
   timeline says whether it does: the recent window's wrongful rate (with its CI)
   against the baseline period's, plus exposure-mix shift. This is the bind-side
   monitoring — the live record continuously re-proving the priced assumptions.

Everything derives from record timestamps (`Decision.ts`); rows without one are
excluded and counted, never guessed. Same honesty contract as the rest: these are
statistics about the insured's own history, so the method is public and auditable.
"""
from datetime import datetime, timedelta

from .core import STORE
from .metrics import wilson

__all__ = ["accumulation", "stability"]


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _evidenced(store):
    """(when, decision, outcome, loss) for decisions with an outcome + timestamp,
    plus the count of evidenced rows excluded for missing/bad timestamps."""
    rows, no_ts = [], 0
    for key, d in store.decisions.items():
        o = store.outcomes.get(key)
        if o is None:
            continue
        when = _parse_ts(d.ts)
        if when is None:
            no_ts += 1
            continue
        if o.ground_truth == d.action:
            loss = 0.0
        else:
            loss = (o.realized_loss_usd if o.realized_loss_usd is not None
                    else o.estimated_loss_usd) or 0.0
        rows.append((when, d, o, loss))
    rows.sort(key=lambda r: r[0])
    return rows, no_ts


def _rolling_max(errors, hours):
    """Max aggregate loss in any rolling window of `hours` (errors sorted by time)."""
    best, start = 0.0, 0
    total = 0.0
    span = timedelta(hours=hours)
    for i, (when, loss) in enumerate(errors):
        total += loss
        while errors[start][0] < when - span:
            total -= errors[start][1]
            start += 1
        best = max(best, total)
    return best


def accumulation(store=None, window_hours=24.0):
    """Cluster wrongful decisions into loss events; bound the correlated tail."""
    store = store if store is not None else STORE
    rows, no_ts = _evidenced(store)
    errors = [(when, loss) for when, d, o, loss in rows if o.ground_truth != d.action]
    events = []
    gap = timedelta(hours=window_hours)
    for when, loss in errors:
        if events and when - events[-1]["_last"] <= gap:
            e = events[-1]
            e["decisions"] += 1
            e["loss_usd"] += loss
            e["end"] = when.isoformat()
            e["_last"] = when
        else:
            events.append({"start": when.isoformat(), "end": when.isoformat(),
                           "decisions": 1, "loss_usd": loss, "_last": when})
    for e in events:
        e.pop("_last")
    total = sum(e["loss_usd"] for e in events)
    worst = max(events, key=lambda e: e["loss_usd"], default=None)
    return {
        "window_hours": window_hours,
        "events": events,
        "event_count": len(events),
        "max_event_loss_usd": worst["loss_usd"] if worst else 0.0,
        "max_event_decisions": max((e["decisions"] for e in events), default=0),
        "worst_event_share": (worst["loss_usd"] / total) if worst and total else 0.0,
        "max_24h_loss_usd": _rolling_max(errors, 24.0),
        "max_7d_loss_usd": _rolling_max(errors, 24.0 * 7),
        "rows_without_ts": no_ts,
    }


def stability(store=None, recent_days=30):
    """The record's own timeline: monthly rate/loss series and a recent-vs-baseline
    drift verdict. `drifting` is True when the recent window's rate and the baseline's
    are incompatible (each point estimate outside the other's CI) — a signal the priced
    assumptions no longer hold, not a proof; the CIs are the honest part."""
    store = store if store is not None else STORE
    rows, no_ts = _evidenced(store)
    if not rows:
        return {"months": [], "recent": None, "baseline": None, "drifting": False,
                "rows_without_ts": no_ts}

    months = {}
    for when, d, o, loss in rows:
        m = months.setdefault(when.strftime("%Y-%m"),
                              {"n": 0, "errors": 0, "loss_usd": 0.0,
                               "exposure_usd": 0.0})
        m["n"] += 1
        m["exposure_usd"] += d.value_at_risk_usd or 0.0
        if o.ground_truth != d.action:
            m["errors"] += 1
            m["loss_usd"] += loss
    series = [{"month": k, **v,
               "rate": v["errors"] / v["n"] if v["n"] else 0.0}
              for k, v in sorted(months.items())]

    cutoff = rows[-1][0] - timedelta(days=recent_days)
    recent = [(when, d, o, loss) for when, d, o, loss in rows if when >= cutoff]
    base = [(when, d, o, loss) for when, d, o, loss in rows if when < cutoff]

    def _window(chunk):
        if not chunk:
            return None
        errs = sum(1 for _, d, o, _ in chunk if o.ground_truth != d.action)
        rate, lo, hi = wilson(errs, len(chunk))
        exposure = sum(d.value_at_risk_usd or 0.0 for _, d, _, _ in chunk)
        return {"n": len(chunk), "errors": errs, "rate": rate, "rate_ci": [lo, hi],
                "mean_exposure_usd": exposure / len(chunk)}

    r, b = _window(recent), _window(base)
    drifting = False
    if r and b and r["n"] >= 5:            # too few recent rows proves nothing
        drifting = (r["rate"] > b["rate_ci"][1] or r["rate"] < b["rate_ci"][0]) and \
                   (b["rate"] > r["rate_ci"][1] or b["rate"] < r["rate_ci"][0])
    return {"months": series, "recent": r, "baseline": b, "recent_days": recent_days,
            "drifting": drifting, "rows_without_ts": no_ts}
