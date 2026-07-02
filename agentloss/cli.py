"""`agentloss` CLI — the machine-readable self-check a coding agent can shell out to.

    agentloss doctor [--json] [--store path]    # self-check (a persisted store, or guidance)
    agentloss report [--json] [--store path]    # error rate + dollar loss from a persisted store
    agentloss gateway --manifest m.json -- cmd  # MCP gateway (docs/GATEWAY.md)

Without `--store`, a CLI process has an EMPTY in-process store (decisions/outcomes live in
the running app), so `doctor` runs the static/config checks + prints guidance and points you
at the agent-facing `agentloss.doctor()` / `validate_integration()`, which inspect the live
store. With `--store` (a JSONL file written by the gateway or `agentloss.persist`), both
commands replay it and give the real answer out-of-process.
"""
import argparse
import json
import sys

from . import __version__
from .doctor import doctor, format_findings


def _load_store_arg(args):
    if getattr(args, "store", None):
        from .persist import load_store
        load_store(args.store)
        return True
    return False


def _doctor_cmd(args):
    loaded = _load_store_arg(args)
    result = doctor()
    if loaded:
        result["store"] = args.store
    empty_store = not loaded and any(
        f["id"] == "decisions_present" and f["level"] == "fail" for f in result["findings"]
    )
    if empty_store:
        # A fresh CLI process has an empty store BY DESIGN — not a broken integration. Present it
        # as informational so an agent that shells out first doesn't misread a FAIL.
        for f in result["findings"]:
            if f["level"] == "fail":
                f["level"] = "info"
        result["ok"] = True
        result["level"] = "info"
        result["note"] = (
            "The CLI runs in a fresh process with an empty store — expected, not a broken "
            "integration. To self-check a real integration, call agentloss.doctor() (or "
            "validate_integration()) INSIDE your app after decisions and outcomes are recorded."
        )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_findings(result))
        if result.get("note"):
            print("\nnote: " + result["note"])
    return 0


def _report_cmd(args):
    if not _load_store_arg(args):
        print("agentloss report needs --store <path> (a JSONL store written by the gateway "
              "or agentloss.persist) — a fresh CLI process has no in-process decisions.",
              file=sys.stderr)
        return 2
    if args.json:
        from .report import report
        print(json.dumps(report(), indent=2, default=str))
    else:
        from .report import print_report
        print_report()
    return 0


def _underwrite_cmd(args):
    if not _load_store_arg(args):
        print("agentloss underwrite needs --store <path> (the audit record: a JSONL store "
              "written by the gateway or agentloss.persist).", file=sys.stderr)
        return 2
    from .underwriting import underwriting_report
    r = underwriting_report(agent=args.agent, baseline=args.baseline)
    if args.html:
        from .report_html import render_html
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(r, store_path=args.store or ""))
        print(f"wrote {args.html}", file=sys.stderr)
    if args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        e, fq, sv, ls, ev = (r["exposure"], r["frequency"], r["severity"],
                             r["loss"], r["evidence"])
        print("=" * 60)
        print(f"underwriting report — {r['profile']}")
        print("=" * 60)
        print(f"exposure  : {e['covered_in_envelope']} covered concession(s), "
              f"${e['total_usd']:,.0f} written, max single ${e['max_single_usd']:,.0f}")
        print(f"frequency : wrongful-grant rate {fq['wrongful_grant_rate']:.2%} "
              f"[{fq['rate_ci'][0]:.2%}, {fq['rate_ci'][1]:.2%}] "
              f"(n={fq['n_evidenced']}; reweighted {fq['rate_reweighted']:.2%})")
        print(f"severity  : {sv['errors']} wrongful grant(s), mean "
              f"${sv['mean_loss_usd']:,.0f}, max ${sv['max_loss_usd']:,.0f}")
        print(f"loss      : realized ${ls['realized_usd']:,.0f}, expected "
              f"${ls['expected_usd']:,.0f}, loss-to-exposure "
              f"{ls['loss_to_exposure']:.3%}")
        print(f"evidence  : {ev['outcome_coverage']:.0%} coverage, {ev['gold']} gold / "
              f"{ev['silver']} silver, sampling={ev['sampling']}")
        for name, s in (r.get("segments") or {}).items():
            print(f"  segment {name}: {s['decisions']} decision(s), rate "
                  f"{s['wrongful_grant_rate']:.2%}, LTX {s['loss_to_exposure']:.3%}")
        cmp = r.get("baseline_comparison")
        if cmp:
            print(f"vs baseline: rate {cmp['rate_delta']:+.2%}, loss-to-exposure "
                  f"{cmp['loss_to_exposure_delta']:+.3%} "
                  f"({'CHEAPER' if cmp['cheaper_to_insure'] else 'costlier'} to insure "
                  f"than {cmp['baseline']})")
        print("-" * 60)
        for f in r["qualification"]:
            if f["level"] != "ok":
                print(f"[{f['level'].upper()}] {f['id']}: {f['message']}")
        print(f"qualifies : {'YES' if r['qualifies'] else 'NO'} (level={r['level']})")
        b = r["binding"]
        print(f"binding   : capture={b['capture']} — "
              + ("BOUND-READY (live middleware capture present)" if b["bound_ready"]
                 else "assessment only; to bind, install the gateway middleware"))
    return 0 if r["qualifies"] else 1


def _backfill_cmd(args):
    from .backfill import backfill_csv, suggest_backfill_mapping
    if args.map:
        mapping = dict(part.split("=", 1) for part in args.map.split(",") if "=" in part)
    else:
        # zero-config: draft the mapping from the export's own header + sample rows
        import csv as _csv
        with open(args.csv, newline="", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            sample = [row for _, row in zip(range(50), reader)]
        mapping, notes = suggest_backfill_mapping(fieldnames, sample)
        todos = {k: v for k, v in mapping.items() if str(v).startswith("_todo")}
        drafted = ",".join(f"{k}={v}" for k, v in mapping.items() if k not in todos)
        print(f"no --map given; drafted from the header: \"{drafted}\"", file=sys.stderr)
        for note in notes:
            print(f"  note: {note}", file=sys.stderr)
        if todos:
            for k, v in todos.items():
                print(f"  {k}: {v}", file=sys.stderr)
            print("resolve the _todo field(s) and re-run with --map.", file=sys.stderr)
            return 2
        mapping = {k: v for k, v in mapping.items() if k not in todos}
    try:
        counts = backfill_csv(
            args.csv, mapping, use_case=args.use_case,
            error_statuses=[s for s in (args.error_statuses or "").split(",") if s],
            correct_statuses=[s for s in (args.correct_statuses or "").split(",") if s],
            store_path=args.store)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(counts))
    else:
        print(f"backfilled: {counts['decisions']} decision(s) — {counts['errors']} "
              f"wrongful, {counts['correct']} correct, {counts['nonfinal']} non-final, "
              f"{counts['skipped']} skipped")
        print(f"next: agentloss underwrite --store {args.store} "
              "[--agent <decider> --baseline <decider>]")
    return 0


def _export_cmd(args):
    if not _load_store_arg(args):
        print("agentloss export needs --store <path> (the audit record).",
              file=sys.stderr)
        return 2
    from .submission import DEFAULT_COLUMNS, load_template, write_submission_csv
    try:
        columns = load_template(args.template) if args.template else DEFAULT_COLUMNS
    except (OSError, ValueError, KeyError) as e:
        print(f"bad template: {e}", file=sys.stderr)
        return 2
    n = write_submission_csv(args.out, columns)
    from .core import STORE
    missing_ts = sum(1 for d in STORE.decisions.values()
                     if d.business_key in STORE.outcomes and not d.ts)
    print(f"wrote {args.out}: {n} evidenced decision(s) in submission format",
          file=sys.stderr)
    if missing_ts:
        print(f"note: {missing_ts} row(s) have no timestamp — backfill with a ts= "
              "column mapping (or capture live) before submitting.", file=sys.stderr)
    return 0


def _import_cmd(args):
    from .importer import import_csv, suggest_mapping
    import csv as _csv

    if not args.map:
        # draft the mapping from the file itself (the `gateway init` move, for a file)
        with open(args.csv, newline="", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            sample = [row for _, row in zip(range(50), reader)]
        mapping, observed = suggest_mapping(fieldnames, sample)
        print("no --map given; drafted from the file header:\n")
        print("  --map \"" + ",".join(f"{k}={v}" for k, v in mapping.items()
                                      if not v.startswith("_todo")) + "\"")
        for k, v in mapping.items():
            if v.startswith("_todo"):
                print(f"  {k}: {v}")
        if observed:
            print(f"\nobserved statuses: {', '.join(observed)}\n"
                  "  -> pass --error-statuses / --correct-statuses from these "
                  "(anything in neither list is treated as non-final and skipped)")
        return 0

    mapping = dict(part.split("=", 1) for part in args.map.split(",") if "=" in part)
    if "business_key" not in mapping:
        print("--map must include business_key=<column>", file=sys.stderr)
        return 2
    _load_store_arg(args)
    counts = import_csv(
        args.csv, mapping,
        error_statuses=[s for s in (args.error_statuses or "").split(",") if s],
        correct_statuses=[s for s in (args.correct_statuses or "").split(",") if s],
        source=args.source, amount_divisor=args.divisor,
        all_errors=args.all_errors, census=args.census, store_path=args.store)
    if args.json:
        print(json.dumps(counts))
    else:
        print(f"imported: {counts['errors']} error(s), {counts['correct']} correct, "
              f"{counts['census_correct']} census-correct; skipped {counts['skipped']}")
        print(f"next: agentloss report --store {args.store}")
    return 0


def main(argv=None):
    # `gateway` relays raw JSON-RPC and owns its own argv shape (a `--` split), so it
    # bypasses argparse: agentloss gateway --manifest m.json [--store p] -- <command...>
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["gateway"]:
        from .gateway import main as gateway_main
        return gateway_main(argv[1:])

    parser = argparse.ArgumentParser(prog="agentloss", description="agentloss self-check CLI")
    parser.add_argument("--version", action="version", version=f"agentloss {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_doctor = sub.add_parser("doctor", help="self-check the integration")
    p_doctor.add_argument("--json", action="store_true", help="machine-readable output")
    p_doctor.add_argument("--store", help="JSONL store file to replay (gateway/persist)")
    p_doctor.set_defaults(func=_doctor_cmd)

    p_report = sub.add_parser("report", help="error rate + dollar loss from a persisted store")
    p_report.add_argument("--json", action="store_true", help="machine-readable output")
    p_report.add_argument("--store", help="JSONL store file to replay (gateway/persist)")
    p_report.set_defaults(func=_report_cmd)

    p_uw = sub.add_parser("underwrite",
                          help="render the audit record for an underwriter: exposure, "
                               "frequency, severity, loss ratio, qualification "
                               "(docs/SUPPORT-CONCESSION.md); exits 1 if the record "
                               "does not qualify")
    p_uw.add_argument("--json", action="store_true", help="machine-readable output")
    p_uw.add_argument("--store", help="JSONL store file to replay (gateway/persist)")
    p_uw.add_argument("--agent", help="decider segment to price (a Decision.model value)")
    p_uw.add_argument("--baseline", help="decider segment to compare against "
                                         "(e.g. the human team's backfilled history)")
    p_uw.add_argument("--html", metavar="PATH",
                      help="also render the report as a self-contained HTML one-pager "
                           "(the artifact you hand to an underwriter)")
    p_uw.set_defaults(func=_underwrite_cmd)

    p_bf = sub.add_parser("backfill",
                          help="build the audit record RETROACTIVELY from a historical "
                               "export — day-one actuarial history; the decider column "
                               "becomes the segment (docs/SUPPORT-CONCESSION.md)")
    p_bf.add_argument("--csv", required=True, help="the historical export")
    p_bf.add_argument("--map",
                      help='"business_key=<col>,amount=<col>[,decider=<col>]'
                           '[,action=<col>][,evidence=<col>][,status=<col>]"; omit to '
                           'draft it from the export\'s own header (Zendesk/Intercom/'
                           'Front conventions recognized)')
    p_bf.add_argument("--error-statuses", help="status values meaning the decision was "
                                               "wrong (with a status column)")
    p_bf.add_argument("--correct-statuses", help="status values meaning it was right")
    p_bf.add_argument("--use-case", default="support_concession")
    p_bf.add_argument("--store", required=True, help="JSONL store to write the record to")
    p_bf.add_argument("--json", action="store_true", help="machine-readable output")
    p_bf.set_defaults(func=_backfill_cmd)

    p_ex = sub.add_parser("export",
                          help="render the audit record as an insurer's tabular data "
                               "submission (decisions joined to ground truth + loss)")
    p_ex.add_argument("--template", metavar="PATH",
                      help="JSON column template mapping record fields onto a specific "
                           "insurer's headers/order (see agentloss/submission.py)")
    p_ex.add_argument("--store", help="JSONL store file to replay (gateway/persist)")
    p_ex.add_argument("--out", required=True, help="output CSV path")
    p_ex.set_defaults(func=_export_cmd)

    p_imp = sub.add_parser("import", help="batch outcomes from a CSV export (the warehouse "
                                          "channel); omit --map to draft one from the header")
    p_imp.add_argument("--csv", required=True, help="the export file")
    p_imp.add_argument("--map", help='"business_key=<col>[,status=<col>][,loss=<col>]"')
    p_imp.add_argument("--error-statuses", help="comma-separated statuses meaning the "
                                                "decision was wrong")
    p_imp.add_argument("--correct-statuses", help="comma-separated statuses meaning it "
                                                  "was right")
    p_imp.add_argument("--all-errors", action="store_true",
                       help="every row is an error (a pure reversals export)")
    p_imp.add_argument("--census", action="store_true",
                       help="mark stored decisions absent from the file as correct "
                            "(only if the file is the complete catch of errors)")
    p_imp.add_argument("--source", default="recovery_audit",
                       help="recovery_audit|dispute|chargeback|refund|human_queue")
    p_imp.add_argument("--divisor", type=float, default=1.0,
                       help="divide loss amounts (e.g. 100 for minor units)")
    p_imp.add_argument("--store", required=True, help="JSONL store (joins + persists)")
    p_imp.add_argument("--json", action="store_true", help="machine-readable output")
    p_imp.set_defaults(func=_import_cmd)

    p_listen = sub.add_parser("listen", help="webhook listener: outcomes pushed by the "
                                             "system of record, mapped in real time")
    p_listen.add_argument("--map", required=True, help="event-map JSON (see agentloss/webhook.py)")
    p_listen.add_argument("--store", required=True, help="JSONL store (joins + persists)")
    p_listen.add_argument("--port", type=int, default=8787)
    p_listen.add_argument("--host", default="127.0.0.1")
    p_listen.add_argument("--secret", help="require X-Agentloss-Secret on every POST")
    p_listen.set_defaults(func=lambda a: __import__(
        "agentloss.webhook", fromlist=["main"]).main(a))

    sub.add_parser("gateway", help="MCP gateway: agentloss gateway --manifest m.json -- <cmd>")

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
