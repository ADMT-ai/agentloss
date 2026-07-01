"""End-to-end dogfood loop:

  seed → run agent → outcome feeds (human queue + delayed audit) → sample+verify → score

    python -m dogfood.run
    AGENTAUDIT_LLM=claude ANTHROPIC_API_KEY=sk-... python -m dogfood.run
"""
import os
from random import Random

import agentaudit
from .config import Config
from .seeder import build
from .llm import get_llm
from . import agent, outcomes, eval as evalmod
from agentaudit import verifier as vmod


def _load_dotenv():
    """Populate os.environ from a .env (repo root or dogfood/) so real-API runs work
    without relying on shell export. Only sets keys that aren't already in the env."""
    for path in (".env", "dogfood/.env", os.path.join(os.path.dirname(__file__), ".env")):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("export "):
                        k = k[len("export "):].strip()
                    os.environ.setdefault(k, v.strip().strip('"').strip("'"))
        except FileNotFoundError:
            pass


def main():
    _load_dotenv()
    cfg = Config()
    agentaudit.STORE.decisions.clear()
    agentaudit.STORE.outcomes.clear()

    erp, stream, oracle = build(cfg)
    invoices_by_no = {inv["invoice_no"]: inv for inv in stream}
    agent_llm = get_llm(cfg.agent_llm_mode)
    verify_llm = get_llm(cfg.verifier_llm_mode)

    print(f"[dogfood] agent={cfg.agent_llm_mode} verifier={cfg.verifier_llm_mode}  "
          f"invoices={len(stream)}  vendors={cfg.n_vendors}")

    # 1) production agent decides + pays
    agent.run(stream, erp, cfg, agent_llm)

    # 2) outcome feeds
    rng = Random(cfg.seed + 1)
    outcomes.human_queue(invoices_by_no, oracle)     # gold for holds/rejects
    outcomes.recovery_audit(oracle, cfg, rng)        # delayed gold + realized $ for a subset

    # 3) active sampling + verification (Tier A silver on the rest)
    verify_fn = vmod.make_fallible(vmod.make_verifier(verify_llm), cfg)   # simulate verifier errors if knobs>0
    from agentaudit import sampler, calibration
    n_sampled = sampler.run(invoices_by_no, erp, cfg, Random(cfg.seed + 2), verify_fn)
    print(f"[dogfood] sampled+verified {n_sampled} decisions")

    # 4) calibration: correct the (fallible) verifier's bias with a small gold budget
    calib = calibration.calibrate(
        lambda k: oracle[k]["correct_action"],
        lambda k: oracle[k]["true_loss_usd"],
        cfg, Random(cfg.seed + 3),
    )

    # 5) scorecard vs oracle
    text, _summary = evalmod.scorecard(oracle, cfg, calib)
    print(text)


if __name__ == "__main__":
    main()
