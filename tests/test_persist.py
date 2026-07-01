import json
import subprocess
import sys

from agentloss import Decision, load_store, report, report_outcome
from agentloss.core import STORE, Store
from agentloss.persist import append_decision, append_outcome


def _seed(path):
    for i, amt in enumerate([100.0, 200.0, 300.0]):
        d = STORE.record(Decision(action="approve", value_at_risk_usd=amt,
                                  business_key=f"K-{i}", use_case="test"))
        append_decision(d, path)
    report_outcome("K-0", ground_truth="reject", source="chargeback",
                   realized_loss_usd=100.0, estimated_loss_usd=100.0)
    report_outcome("K-1", ground_truth="approve", source="dispute",
                   realized_loss_usd=0.0)
    report_outcome("K-2", ground_truth="approve", source="dispute",
                   realized_loss_usd=0.0)
    for k in ("K-0", "K-1", "K-2"):
        append_outcome(k, STORE.outcomes[k], path)


def test_roundtrip_into_fresh_store(tmp_path):
    path = str(tmp_path / "store.jsonl")
    _seed(path)
    fresh = Store()
    loaded = load_store(path, store=fresh)
    assert loaded == {"decisions": 3, "outcomes": 3}
    assert fresh.decisions["K-0"].value_at_risk_usd == 100.0
    assert fresh.outcomes["K-0"].ground_truth == "reject"


def test_replay_gives_same_numbers(tmp_path):
    path = str(tmp_path / "store.jsonl")
    _seed(path)
    before = report()
    STORE.decisions.clear()
    STORE.outcomes.clear()
    load_store(path)
    after = report()
    assert after == before


def test_malformed_and_unknown_fields_skipped(tmp_path):
    path = tmp_path / "store.jsonl"
    path.write_text(
        "not json\n"
        + json.dumps({"type": "decision", "action": "approve", "value_at_risk_usd": 1.0,
                      "business_key": "K-1", "future_field": True}) + "\n"
        + json.dumps({"type": "outcome"}) + "\n")  # outcome without a key is skipped
    fresh = Store()
    assert load_store(str(path), store=fresh) == {"decisions": 1, "outcomes": 0}


def test_cli_doctor_and_report_read_the_store(tmp_path):
    path = str(tmp_path / "store.jsonl")
    _seed(path)
    out = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "doctor", "--json", "--store", path],
        capture_output=True, text=True, check=True)
    result = json.loads(out.stdout)
    assert result["ok"] and result["level"] == "ok" and result["store"] == path

    out = subprocess.run(
        [sys.executable, "-m", "agentloss.cli", "report", "--json", "--store", path],
        capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r["decisions"] == 3 and abs(r["realized_loss_usd"] - 100.0) < 1e-9


def test_cli_report_without_store_errors():
    out = subprocess.run([sys.executable, "-m", "agentloss.cli", "report"],
                         capture_output=True, text=True)
    assert out.returncode == 2 and "--store" in out.stderr
