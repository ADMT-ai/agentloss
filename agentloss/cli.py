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

    sub.add_parser("gateway", help="MCP gateway: agentloss gateway --manifest m.json -- <cmd>")

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
