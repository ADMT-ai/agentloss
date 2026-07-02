"""Render the underwriting report as a self-contained HTML one-pager — the assessment
as an artifact you hand to an underwriter or a board, not a JSON blob.

Design notes (kept deliberately boring): stat tiles for the headline figures, one
single-hue comparison bar for agent-vs-baseline loss-to-exposure (identity is carried
by the row labels, values labeled at the bar tip), status colors only for status
(qualification/binding, always icon + label, never color alone), text in ink tokens
(never the data color). No JS, no external assets; prints clean.
"""
import html as _html

from . import __version__

__all__ = ["render_html"]

_CSS = """
:root {
  --surface: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --hairline: #e1e0d9; --border: rgba(11,11,11,0.10);
  --bar: #2a78d6; --bar-track: #cde2fb;
  --good: #0ca30c; --good-text: #006300; --warn: #fab219; --crit: #d03b3b;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
.page { max-width: 760px; margin: 24px auto; background: var(--surface);
        border: 1px solid var(--border); border-radius: 8px; padding: 32px 36px; }
header { display: flex; justify-content: space-between; align-items: baseline;
         gap: 12px; flex-wrap: wrap; }
h1 { font-size: 20px; margin: 0; }
h2 { font-size: 13px; margin: 28px 0 10px; color: var(--ink-2);
     text-transform: uppercase; letter-spacing: 0.04em; }
.sub { color: var(--ink-2); margin-top: 2px; }
.badges { display: flex; gap: 8px; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
         border-radius: 999px; font-weight: 600; font-size: 12px;
         border: 1px solid var(--border); color: var(--ink); }
.badge .dot { width: 9px; height: 9px; border-radius: 50%; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
         margin-top: 20px; }
.tile { border: 1px solid var(--hairline); border-radius: 8px; padding: 12px 14px; }
.tile .label { color: var(--ink-2); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 600; margin-top: 2px; }
.tile .note { color: var(--muted); font-size: 12px; margin-top: 2px; }
.facts { color: var(--ink-2); font-size: 12px; margin-top: 10px; }
.cmp .row { display: grid; grid-template-columns: 130px 1fr 64px; gap: 10px;
            align-items: center; margin: 8px 0; }
.cmp .name { font-size: 13px; color: var(--ink-2); }
.cmp .track { background: var(--bar-track); border-radius: 0 4px 4px 0;
              height: 18px; position: relative; }
.cmp .fill { background: var(--bar); height: 100%; border-radius: 0 4px 4px 0; }
.cmp .val { font-weight: 600; font-variant-numeric: tabular-nums; }
.cmp .delta { margin-top: 6px; font-size: 13px; color: var(--ink-2); }
ul.findings { list-style: none; padding: 0; margin: 0; }
ul.findings li { display: flex; gap: 8px; padding: 6px 0;
                 border-bottom: 1px solid var(--hairline); }
ul.findings li:last-child { border-bottom: 0; }
.icon { font-weight: 700; width: 44px; flex: none; font-size: 12px; }
.icon.ok { color: var(--good-text); } .icon.warn { color: #8a5b00; }
.icon.fail { color: var(--crit); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; color: var(--ink-2); font-weight: 600;
     border-bottom: 1px solid var(--hairline); padding: 6px 8px 6px 0; }
td { border-bottom: 1px solid var(--hairline); padding: 6px 8px 6px 0;
     font-variant-numeric: tabular-nums; }
footer { margin-top: 28px; color: var(--muted); font-size: 12px; }
@media print { body { background: #fff; } .page { border: 0; margin: 0; } }
"""


def _e(v):
    return _html.escape(str(v))


def _money(v):
    v = float(v or 0)
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cut:
            return f"${v / cut:,.1f}{suffix}"
    return f"${v:,.0f}"


def _pct(v, digits=1):
    return f"{100 * float(v or 0):.{digits}f}%"


def _badge(label, color):
    return (f'<span class="badge"><span class="dot" style="background:{color}">'
            f'</span>{_e(label)}</span>')


def _tile(label, value, note=""):
    note_html = f'<div class="note">{_e(note)}</div>' if note else ""
    return (f'<div class="tile"><div class="label">{_e(label)}</div>'
            f'<div class="value">{_e(value)}</div>{note_html}</div>')


def render_html(report, store_path=""):
    """The underwriting report dict (agentloss.underwriting.underwriting_report)
    rendered as a self-contained one-page HTML document. Returns the HTML string."""
    e, fq, sv, ls, ev, b = (report["exposure"], report["frequency"],
                            report["severity"], report["loss"], report["evidence"],
                            report["binding"])
    qual_badge = _badge("QUALIFIES", "var(--good)") if report["qualifies"] else \
        _badge("DOES NOT QUALIFY", "var(--crit)")
    bind_badge = _badge("BOUND-READY", "var(--good)") if b["bound_ready"] else \
        _badge("ASSESSMENT", "var(--warn)")

    lo, hi = fq["rate_ci"]
    tiles = "".join((
        _tile("Exposure written", _money(e["total_usd"]),
              f"{e['covered_in_envelope']} covered concessions · max single "
              f"{_money(e['max_single_usd'])}"),
        _tile("Wrongful-grant rate", _pct(fq["wrongful_grant_rate"]),
              f"CI {_pct(lo)}–{_pct(hi)} · n={fq['n_evidenced']} · reweighted "
              f"{_pct(fq['rate_reweighted'])}"),
        _tile("Expected loss", _money(ls["expected_usd"]),
              f"realized (gold) {_money(ls['realized_usd'])}"),
        _tile("Loss-to-exposure", _pct(ls["loss_to_exposure"], 2),
              f"severity mean {_money(sv['mean_loss_usd'])} · max "
              f"{_money(sv['max_loss_usd'])}"),
    ))

    segments = report.get("segments") or {}
    cmp_html = ""
    if len(segments) >= 2:
        peak = max(s["loss_to_exposure"] for s in segments.values()) or 1.0
        rows = "".join(
            f'<div class="row"><div class="name">{_e(name)}</div>'
            f'<div class="track"><div class="fill" '
            f'style="width:{max(2.0, 100 * s["loss_to_exposure"] / peak):.1f}%">'
            f'</div></div><div class="val">{_pct(s["loss_to_exposure"], 1)}</div></div>'
            for name, s in sorted(segments.items(),
                                  key=lambda kv: kv[1]["loss_to_exposure"]))
        cmp = report.get("baseline_comparison")
        delta = ""
        if cmp:
            verdict = ("cheaper to insure than" if cmp["cheaper_to_insure"]
                       else "costlier to insure than")
            delta = (f'<div class="delta"><strong>{_e(cmp["agent"])}</strong> is '
                     f'{verdict} <strong>{_e(cmp["baseline"])}</strong>: '
                     f'loss-to-exposure {cmp["loss_to_exposure_delta"] * 100:+.2f} pts, '
                     f'wrongful-grant rate {cmp["rate_delta"] * 100:+.1f} pts.</div>')
        seg_rows = "".join(
            f"<tr><td>{_e(name)}</td><td>{s['decisions']}</td>"
            f"<td>{_money(s['exposure_usd'])}</td>"
            f"<td>{_pct(s['wrongful_grant_rate'])}</td>"
            f"<td>{_money(s['expected_loss_usd'])}</td>"
            f"<td>{_pct(s['loss_to_exposure'], 2)}</td></tr>"
            for name, s in sorted(segments.items()))
        cmp_html = (
            '<h2>Loss-to-exposure by decider</h2><div class="cmp">' + rows + delta
            + '</div><h2>Segments</h2><table><tr><th>Decider</th><th>Decisions</th>'
              '<th>Exposure</th><th>Rate</th><th>Expected loss</th><th>LTX</th></tr>'
            + seg_rows + "</table>")

    icons = {"ok": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO"}
    findings = "".join(
        f'<li><span class="icon {f["level"]}">{icons.get(f["level"], "·")}</span>'
        f'<span><strong>{_e(f["id"])}</strong> — {_e(f["message"])}</span></li>'
        for f in report["qualification"] if f["level"] != "ok")
    findings = findings or ('<li><span class="icon ok">PASS</span>'
                            '<span>All qualification checks pass.</span></li>')

    binding_note = (_e(b["requirement"]) if b["requirement"] else
                    "Live middleware capture present — the record is kept in force by "
                    "the gateway.")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Insurability report — {_e(report["profile"])}</title>
<style>{_CSS}</style></head>
<body><div class="page">
<header>
  <div><h1>Insurability report</h1>
  <div class="sub">profile {_e(report["profile"])} · evidence coverage
  {_pct(ev["outcome_coverage"], 0)} · {ev["gold"]} gold / {ev["silver"]} silver ·
  sampling {_e(ev["sampling"])}</div></div>
  <div class="badges">{qual_badge}{bind_badge}</div>
</header>
<div class="tiles">{tiles}</div>
<div class="facts">{e["decisions"]} decisions recorded · {e["granting"]} granting ·
sources: {_e(", ".join(f"{k} ({v})" for k, v in sorted(ev["sources"].items())))}</div>
{cmp_html}
<h2>Qualification</h2>
<ul class="findings">{findings}</ul>
<h2>Binding</h2>
<p>Capture grade: <strong>{_e(b["capture"])}</strong> ·
{b["live_decisions"]} live-captured decision(s). {binding_note}</p>
<footer>Generated by agentloss {__version__}{" · store " + _e(store_path)
    if store_path else ""} · assess (this report) → bind (install the gateway
middleware; coverage is kept in force by the live record). Methodology and oracle
evals: github.com/ADMT-ai/agentloss</footer>
</div></body></html>
"""
