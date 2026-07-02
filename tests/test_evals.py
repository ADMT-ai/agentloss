"""Run every offline example/eval as a subprocess — each is an oracle: known inputs,
expected outputs, nonzero exit on any failure. This is the repo's regression net."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVALS = [
    "examples/stripe_detector_eval.py",
    "examples/erp_detector_eval.py",
    "examples/reasoning_detector_eval.py",
    "examples/calibration_eval.py",
    "examples/gateway_eval.py",
    "examples/gateway_init_eval.py",
    "examples/gateway_http_eval.py",
    "examples/gateway_init_http_eval.py",
    "examples/sor_ladder_eval.py",
    "examples/underwriting_eval.py",
    "examples/backfill_eval.py",
    "examples/import_eval.py",
    "examples/webhook_eval.py",
    "examples/verifier_offline_test.py",
    "examples/connectors_offline_test.py",
    "examples/phoenix_offline_test.py",
    "examples/stripe_pack_test.py",
    "examples/tools_pack_test.py",
    "examples/payment_pack.py",
    "examples/from_spans.py",
]


@pytest.mark.parametrize("script", EVALS, ids=[os.path.basename(e) for e in EVALS])
def test_eval(script):
    proc = subprocess.run([sys.executable, os.path.join(ROOT, script)], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"


def test_dogfood_oracle_harness():
    proc = subprocess.run([sys.executable, "-m", "dogfood.run"], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"dogfood failed:\n{proc.stdout}\n{proc.stderr}"
    assert "PASS" in proc.stdout
