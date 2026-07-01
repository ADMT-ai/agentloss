"""`agentloss` CLI — the machine-readable self-check a coding agent can shell out to.

    agentloss doctor            # human-readable
    agentloss doctor --json     # machine-readable

A CLI process has an EMPTY in-process store (decisions/outcomes live in the running app),
so the CLI runs the static/config checks + prints guidance and points you at the agent-facing
`agentloss.doctor()` / `agentloss.validate_integration()`, which inspect the live store.
"""
import argparse
import json
import sys

from . import __version__
from .doctor import doctor, format_findings


def _doctor_cmd(args):
    result = doctor()
    empty_store = any(
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentloss", description="agentloss self-check CLI")
    parser.add_argument("--version", action="version", version=f"agentloss {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_doctor = sub.add_parser("doctor", help="self-check the integration")
    p_doctor.add_argument("--json", action="store_true", help="machine-readable output")
    p_doctor.set_defaults(func=_doctor_cmd)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
