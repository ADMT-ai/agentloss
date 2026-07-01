"""Persistent store — decisions/outcomes as append-only JSONL, so capture and readout can live
in different processes.

The in-process STORE is right for the SDK path (capture and report in one app). The gateway is a
separate process from whoever wants the number, so it appends every decision/outcome here, and
`agentloss doctor --store` / `agentloss report --store` (or `load_store()` in code) replay the
file into a store to compute the same checks and metrics.

Rows are one JSON object per line: {"type": "decision", ...fields} or
{"type": "outcome", "business_key": ..., ...fields}. Append-only; the last row for a
business_key wins on replay (same semantics as the dict-backed Store).
"""
import dataclasses
import json
import os

from .core import STORE, Decision, Outcome

__all__ = ["append_decision", "append_outcome", "load_store", "DEFAULT_STORE_PATH"]

DEFAULT_STORE_PATH = os.path.join(".agentloss", "store.jsonl")


def _append(path, row):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def append_decision(decision, path):
    _append(path, {"type": "decision", **dataclasses.asdict(decision)})


def append_outcome(business_key, outcome, path):
    _append(path, {"type": "outcome", "business_key": business_key,
                   **dataclasses.asdict(outcome)})


def _fields(cls):
    return {f.name for f in dataclasses.fields(cls)}


def load_store(path, store=None):
    """Replay a JSONL store file into `store` (default: the in-process STORE).

    Unknown keys are dropped (forward-compatible); malformed lines are skipped.
    Returns {"decisions": n, "outcomes": n} loaded."""
    store = store if store is not None else STORE
    dec_fields, out_fields = _fields(Decision), _fields(Outcome)
    n_d = n_o = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = row.pop("type", None)
            if kind == "decision":
                d = Decision(**{k: v for k, v in row.items() if k in dec_fields})
                store.decisions[d.business_key] = d
                n_d += 1
            elif kind == "outcome":
                key = row.pop("business_key", None)
                if key is None:
                    continue
                store.outcomes[key] = Outcome(
                    **{k: v for k, v in row.items() if k in out_fields})
                n_o += 1
    return {"decisions": n_d, "outcomes": n_o}
