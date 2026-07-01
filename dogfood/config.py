from dataclasses import dataclass, field
import os


@dataclass
class Config:
    seed: int = 7

    # --- population ---
    n_vendors: int = 40
    # keep small for real-API runs (agent makes one call PER invoice). Override with AGENTAUDIT_N_INVOICES.
    n_invoices: int = field(default_factory=lambda: int(os.environ.get("AGENTAUDIT_N_INVOICES", "4000")))

    # --- injected error rates (fraction of the raw stream) ---
    # calibrated so residual escapes land near the ~0.1-0.3% recovery-audit prior
    rate_duplicate: float = 0.015   # half exact (agent catches), half variant (escapes)
    rate_overpay: float = 0.008     # collusive PO price; only contract check catches
    rate_qty: float = 0.005         # no receipt; only PO-ordered check catches
    rate_fraud: float = 0.002       # on-master but bank-changed; only risk check catches
    rate_false_trap: float = 0.010  # valid-but-unusual → agent may false-block
    rate_ambiguous: float = 0.003   # partial duplicate → verifier low-confidence

    # --- agent limitations (what makes it realistically imperfect) ---
    agent_dup_window_days: int = 90
    price_tolerance: float = 0.02

    # --- sampling (target-n probability-proportional-to-size) ---
    # verifier BUDGET: expected # of adjudications (the dial). Override with AGENTAUDIT_TARGET_N.
    sample_target_n: int = field(default_factory=lambda: int(os.environ.get("AGENTAUDIT_TARGET_N", "600")))
    sample_floor: float = 0.02   # min inclusion prob so small items still cover the rate

    # --- outcome simulation ---
    audit_catch_rate: float = 0.6       # fraction of true escapes a recovery audit catches
    recovery_fraction: float = 0.4      # fraction of caught loss clawed back

    # --- verifier fallibility (simulate a real, imperfect verifier; 0 = perfect mock) ---
    verifier_fp_rate: float = field(default_factory=lambda: float(os.environ.get("AGENTAUDIT_VFP", "0.0")))
    verifier_fn_rate: float = field(default_factory=lambda: float(os.environ.get("AGENTAUDIT_VFN", "0.0")))

    # --- calibration (two-phase gold: confirm every flag + spot-check q of approvals) ---
    cal_negative_sample_rate: float = field(default_factory=lambda: float(os.environ.get("AGENTAUDIT_CAL_Q", "0.15")))

    # --- llm (agent and verifier can differ; verifier is what calibration measures) ---
    llm_mode: str = field(default_factory=lambda: os.environ.get("AGENTAUDIT_LLM", "mock"))
    agent_llm_mode: str = field(default_factory=lambda: os.environ.get(
        "AGENTAUDIT_AGENT_LLM", os.environ.get("AGENTAUDIT_LLM", "mock")))
    verifier_llm_mode: str = field(default_factory=lambda: os.environ.get(
        "AGENTAUDIT_VERIFIER_LLM", os.environ.get("AGENTAUDIT_LLM", "mock")))


AMOUNT_BANDS = ((0, 5000), (5000, 25000), (25000, 10**12))


def band(amount: float) -> str:
    for lo, hi in AMOUNT_BANDS:
        if lo <= amount < hi:
            return f"{lo}-{hi}"
    return "other"
