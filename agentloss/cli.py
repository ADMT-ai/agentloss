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

    sub.add_parser("gateway", help="MCP gateway: agentloss gateway --manifest m.json -- <cmd>")

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
