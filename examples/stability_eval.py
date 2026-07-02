"""Oracle eval for accumulation + stability (agentloss/stability.py) — the loss
DYNAMICS the underwriting standard prices: correlated loss events, rolling-window
aggregates, and whether the recent rate still matches the priced baseline.

Seeded truths, all hand-derived:
- a BURST of three wrongful grants within one day (a correlated event: one incident,
  not three) plus one isolated error weeks later -> exactly 2 loss events, worst
  event $300 across 3 decisions, max-24h $300;
- a STABLE history (same low rate throughout) -> drifting False;
- a DRIFTED history (baseline ~5% wrongful, recent 30 days ~50%) -> drifting True and
  a loss_rate_drift warning in the underwriting report;
- evidenced rows with no timestamp are excluded AND counted, never guessed.

    python examples/stability_eval.py   # -> PASS/FAIL per check; exits nonzero on fail
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentloss import Decision, report_outcome  # noqa: E402
from agentloss.core import STORE  # noqa: E402
from agentloss.stability import accumulation, stability  # noqa: E402
from agentloss.underwriting import underwriting_report  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def _reset():
    STORE.decisions.clear()
    STORE.outcomes.clear()


def _grant(key, ts, wrongful=False, loss=100.0, amount=100.0):
    # stamp=False mimics backfill: an empty ts stays empty (never fabricated)
    STORE.record(Decision(action="grant", value_at_risk_usd=amount, business_key=key,
                          use_case="support_concession", ts=ts), stamp=False)
    report_outcome(key, ground_truth="deny" if wrongful else "grant",
                   source="human_queue", realized_loss_usd=loss if wrongful else 0.0)


def main():
    # -- accumulation: a burst is ONE event; an isolated error is another
    _reset()
    for i, day in enumerate(("2025-01-05", "2025-01-20", "2025-02-02", "2025-03-14",
                             "2025-03-28", "2025-04-18", "2025-05-06", "2025-05-22")):
        _grant(f"OK{i}", f"{day}T10:00:00+00:00")
    _grant("B1", "2025-02-10T10:00:00+00:00", wrongful=True)
    _grant("B2", "2025-02-10T12:00:00+00:00", wrongful=True)
    _grant("B3", "2025-02-10T20:00:00+00:00", wrongful=True)
    _grant("ISO", "2025-04-01T09:00:00+00:00", wrongful=True, loss=50.0)
    _grant("NOTS", "", wrongful=True)          # evidenced but timestampless

    acc = accumulation()
    check("accumulation: burst chains into one event, isolated stands alone",
          acc["event_count"] == 2, str(acc["event_count"]))
    check("accumulation: worst event loss", abs(acc["max_event_loss_usd"] - 300.0) < 1e-9,
          str(acc["max_event_loss_usd"]))
    check("accumulation: worst event size", acc["max_event_decisions"] == 3, str(acc))
    check("accumulation: max 24h aggregate", abs(acc["max_24h_loss_usd"] - 300.0) < 1e-9,
          str(acc["max_24h_loss_usd"]))
    check("accumulation: max 7d aggregate", abs(acc["max_7d_loss_usd"] - 300.0) < 1e-9,
          str(acc["max_7d_loss_usd"]))
    check("accumulation: worst-event share of total loss",
          abs(acc["worst_event_share"] - 300.0 / 350.0) < 1e-9,
          str(acc["worst_event_share"]))
    check("accumulation: timestampless rows excluded and counted",
          acc["rows_without_ts"] == 1, str(acc["rows_without_ts"]))

    # -- stability: a steady rate is not drift
    _reset()
    n = 0
    for month in range(1, 7):
        for day in (3, 9, 15, 21, 27):
            n += 1
            _grant(f"S{n}", f"2025-{month:02d}-{day:02d}T10:00:00+00:00",
                   wrongful=(n % 15 == 0))     # sparse, uniform errors
    stab = stability()
    check("stability: uniform history reads stable", stab["drifting"] is False,
          str(stab["recent"]))
    check("stability: monthly series covers the span", len(stab["months"]) == 6,
          str([m['month'] for m in stab['months']]))

    # -- drift: baseline ~5%, the last 30 days ~50% -> incompatible CIs
    _reset()
    n = 0
    for month in range(1, 6):                  # baseline: Jan-May, 40 grants, 2 wrongful
        for day in (2, 6, 10, 14, 18, 22, 26, 30):
            n += 1
            _grant(f"D{n}", f"2025-{month:02d}-{day:02d}T10:00:00+00:00",
                   wrongful=(n in (7, 23)))
    for i, day in enumerate((5, 8, 11, 14, 17, 20, 23, 26, 28, 29)):  # June: 10, 5 wrong
        _grant(f"R{i}", f"2025-06-{day:02d}T10:00:00+00:00", wrongful=(i % 2 == 0))
    stab = stability()
    check("drift: detected", stab["drifting"] is True,
          f"recent {stab['recent']} vs baseline {stab['baseline']}")
    r = underwriting_report()
    check("drift: underwriting report warns loss_rate_drift",
          any(f["id"] == "loss_rate_drift" and f["level"] == "warn"
              for f in r["qualification"]), str(r["level"]))
    check("drift: report still qualifies (warn, not fail)", r["qualifies"] is True,
          str(r["level"]))
    check("report: accumulation summary carried (no raw event list)",
          "max_24h_loss_usd" in r["accumulation"] and "events" not in r["accumulation"],
          str(sorted(r["accumulation"])))

    n_fail = sum(1 for ok in _checks if not ok)
    print(f"\n{len(_checks) - n_fail}/{len(_checks)} checks pass")
    if n_fail:
        sys.exit(1)
    print("ALL PASS — the record's loss dynamics recover the seeded truths.")


if __name__ == "__main__":
    main()
