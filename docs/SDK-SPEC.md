# ailoss SDK Spec — Agent-Adoptable Reliability Instrumentation

_Working name: **ailoss** (placeholder). OTel namespace: `ailoss.*`._
_Last updated 2026-06-30._

## What it is

An OpenTelemetry-native SDK that measures an AI agent's **real-world error rate and
dollar impact** by capturing consequential decisions in-process and joining them to
ground truth. Designed to be discovered, chosen, and correctly wired by an **AI
coding agent** with no human in the loop for the integration itself.

Scope: reliability measurement only. **Out of scope for this SDK:** risk transfer, cross-org
data pooling, and downstream commercial layers.

## Design principles (agent-first)

1. **Standard-aligned = discoverable.** Built on OpenTelemetry + OpenInference;
   `ailoss.*` semantic conventions (candidate for upstreaming). An agent reaching for
   "the standard way to instrument an agent" lands on us.
2. **Shortest correct path.** One import, one decorator, sane defaults. Correct usage
   is the _fewest tokens_, because agents minimize steps and error surface.
3. **Impossible to misconfigure + self-verifying.** Agents fail silently and
   confidently. Typed contracts, loud dev-time errors, and a machine-readable
   `doctor` command an agent can parse to confirm its own work.
4. **Agent-native delivery.** Not just a pip package — `llms.txt`, an MCP server, a
   coding-agent skill, a rules snippet, and framework plugins.
5. **Sovereignty by default.** In-process capture → local/VPC processing → export
   only derived metrics. No raw prompts/records leave the customer boundary.
6. **Local-first.** Full value with no account and no egress; data-sharing is a
   later, opt-in step (see [Data flow & activation](#data-flow--activation)).

## Architecture: core + packs + adapters

Ground truth, review queues, and loss semantics differ per business. We absorb that
variation in **pluggable layers** so the core stays universal (the difference between
a product and a consulting shop):

```
┌────────────────────────────────────────────────────────────┐
│ CORE (invariant, built once)                                │
│   OTel/OpenInference emission · ailoss.* schema · the join  │
│   sampling + reweighting · stats/CIs · calibration runtime  │
│   verifier runtime · doctor · in-VPC processing             │
├────────────────────────────────────────────────────────────┤
│ PACK (per vertical, built once, reused across all customers)│
│   loss taxonomy + cost matrix · verification procedure      │
│   ground-truth source types · ODD template · action space   │
├────────────────────────────────────────────────────────────┤
│ ADAPTER (per customer, thin config, agent-writable)         │
│   field mappings · which queue/table/file each GT source is │
│   tool bindings (often "reuse the agent's existing access") │
└────────────────────────────────────────────────────────────┘
```

Everything a pack or adapter produces normalizes **into `ailoss.*`** — which is what
makes heterogeneous verticals commensurable and lets downstream aggregation span verticals.
Discipline that keeps it a product, not services: **the verifier reads the customer's
policy, packs standardize the vertical, agents write the glue.** If you're hand-coding
bespoke verification per customer, pull it up into the pack or down into an adapter.

## Core API surface

Shortest-correct-path, illustrated on the AP beachhead:

```python
from ailoss import instrument, decision, Decision

# 1) One line. Auto-instruments the agent framework via OpenInference,
#    installs the OTel tracer + the ailoss span processor. Loads the pack + adapter.
instrument(service="ap-agent", pack="ap", adapter="adapters/acme.yaml")

# 2) Wrap the consequential action. The return value carries the moat attributes;
#    the SDK stamps ailoss.* onto the active span and records the join key.
@decision(use_case="ap_3way_match")
def approve_payment(invoice) -> Decision:
    result = run_matching(invoice)          # existing agent logic
    return Decision(
        action=result.action,               # "approve" | "hold" | "reject"
        value_at_risk_usd=invoice.total,     # per-decision exposure / sum insured
        business_key=invoice.number,         # join key for delayed outcomes
        # in_envelope auto-evaluated from the pack's ODD; override if needed
    )
```

**Outcome reporting** (async; wired by the adapter, or called directly):

```python
from ailoss import report_outcome

report_outcome(
    business_key="INV-88231",
    ground_truth="duplicate-should-block",
    realized_loss_usd=14200,
    recovery_usd=0,
    source="recovery_audit",          # erp | human_queue | recovery_audit | dispute | sample
)
```

## `ailoss.*` semantic conventions

Layered on OTel GenAI / OpenInference spans. Grouped; each is a candidate upstream
contribution.

| Attribute | Type | Example | Notes |
|---|---|---|---|
| **Correlation & integrity** | | | |
| `ailoss.decision_id` | string | `d_88231` | stable id |
| `ailoss.business_key` | string | `INV-88231` | natural join key for outcomes |
| `ailoss.use_case_id` | string | `ap_3way_match` | segmentation |
| `ailoss.attestation` | string | `sha256:…` | tamper-evident signed digest |
| **Action & envelope (ODD)** | | | |
| `ailoss.action` | string | `approve` | the decision |
| `ailoss.action.value_at_risk_usd` | double | `14200` | per-decision exposure |
| `ailoss.action.reversible` | bool | `false` | rollback possible? |
| `ailoss.autonomy.level` | string | `autonomous` | autonomous/approved/advisory |
| `ailoss.autonomy.human_override` | string | `none` | override + direction |
| `ailoss.odd.envelope_id` | string | `ap_v3` | declared operating envelope |
| `ailoss.odd.in_envelope` | bool | `true` | in-domain? out ⇒ excluded |
| `ailoss.expected_behavior` | string | `block if duplicate per AP-SOP-12` | the "ground rules"; verifier spec |
| `ailoss.guardrail.triggered` | bool | `false` | guardrail fired? |
| **Outcome (ground truth)** | | | |
| `ailoss.gt.value` | string | `duplicate-should-block` | resolved truth |
| `ailoss.gt.source` | string | `recovery_audit` | how determined |
| `ailoss.gt.fidelity` | string | `gold` | gold (human/realized) vs silver (verifier) |
| `ailoss.gt.confidence` | double | `0.92` | verifier confidence (silver) |
| `ailoss.gt.resolved_at` | int (ns) | | timestamp |
| **Loss** | | | |
| `ailoss.loss.type` | string | `duplicate_payment` | pack taxonomy |
| `ailoss.loss.amount_usd` | double | `14200` | realized |
| `ailoss.loss.recovery_usd` | double | `0` | clawback |
| `ailoss.loss.expected_usd` | double | | modeled (silver) pre-resolution |
| `ailoss.loss.counterfactual` | bool | `true` | attributable to the agent? |
| **Provenance (accumulation)** | | | |
| `ailoss.model.foundation` | string | `claude-opus-4-x` | base model |
| `ailoss.model.adaptation` | string | `finetune+rag` | none/prompt/rag/finetune |
| `ailoss.model.adaptation_id` | string | `v2026Q2` | tuned-system version |
| `ailoss.retrieval.corpus_id` | string | `vendor_master_2026Q2` | RAG source |
| **Baseline (benchmark)** | | | |
| `ailoss.baseline.value` | string | | shadow base-model output |
| `ailoss.baseline.correct` | bool | `false` | baseline right where tuned wrong? |

## Use-case packs

A pack is built once per vertical and reused across every customer in it. It declares
the domain-specific semantics — never the customer's plumbing.

```yaml
# packs/ap/pack.yaml
pack: ap
version: 1
decision:
  use_cases: [ap_3way_match]
  action_space: [approve, hold, reject]
ground_truth:
  # ordered by fidelity; the join uses the highest-fidelity source available per decision
  sources:
    - id: realized_correction    # tier C — credit memo / reversal / clawback
      kind: system_of_record
      fidelity: gold
    - id: human_queue            # tier A — exception adjudications
      kind: in_process
      fidelity: gold
    - id: recovery_audit         # tier B — audit-firm findings
      kind: batch_file
      fidelity: gold
    - id: verification_agent     # tier A — re-adjudication
      kind: verifier
      fidelity: silver
  expected_behavior_ref: policy  # verifier adjudicates against the CUSTOMER's policy doc
loss:
  taxonomy: [duplicate_payment, overpayment, fraud_paid, false_block]
  cost_matrix: cost_matrix.yaml  # (predicted, actual, value_at_risk) -> $
verification:
  procedure: ap_reverify         # checks: duplicate, po_receipt, price_terms, legitimacy
  tools_required: [invoice_history, po_lookup, contract_prices]
odd_template: envelope.yaml      # the in_envelope predicate (see below)
```

```yaml
# packs/ap/envelope.yaml  (the ODD template; customer fills the lists)
envelope_id: ap_v3
in_envelope:
  all:
    - value_at_risk_usd: { max: 25000 }
    - vendor: { on_list: approved_vendor_master }
    - checks_passed: { includes: [po_match, receipt_match] }
```

## Per-customer adapters

Thin mapping from the pack's abstract needs to this customer's systems. This is the
only per-customer artifact, and it's exactly the glue a coding agent can write.

```yaml
# adapters/acme.yaml
pack: ap
maps:
  business_key: invoice.number      # namespaced by vendor_id (unique-key fix)
  value_at_risk_usd: invoice.total
ground_truth_bindings:
  human_queue:         { source: in_process, workflow: exceptions }
  realized_correction: { source: snowflake, table: ap_events,
                         filter: "type in ('credit_memo','reversal')" }
  recovery_audit:      { source: sftp, glob: "prgx/*.csv" }
tool_bindings:
  invoice_history: { via: agent_erp_conn }   # reuse the agent's EXISTING access
  po_lookup:       { via: agent_erp_conn }
  contract_prices: { source: snowflake, table: price_list }
policy_ref: docs/AP-SOP-12.md                # the verifier's adjudication standard
```

## Getting outcomes: the three tiers

Decision data alone is hollow — you need ground truth. Tiers are ordered by access
cost; **Tier A needs no external systems**, so `gt_resolvable_rate > 0` on day one.

- **Tier A — self-contained (day one, zero external access):**
  - _Human-queue labels_ — exception decisions the agent already routes to humans;
    captured in-process. Gold.
  - _Active sampling + verification agent_ — re-adjudicates sampled decisions using
    the same data access the production agent already has, plus more compute. Silver.
- **Tier B — customer-pushed (low friction):** `report_outcome()` from the customer's
  own code/webhook when an outcome resolves, or a periodic recovery-audit CSV. Gold.
- **Tier C — system-of-record connector (highest fidelity, later):** scoped
  warehouse view / ERP hook for authoritative delayed truth and realized dollars.

Move A → C as trust deepens and dollar-accuracy/insurance justify the access.

## Active sampling + verification engine

The engine behind Tier A. Legitimate because **verification is easier than
generation**: the verifier gets advantages the production agent lacked (more time,
tools, data, hindsight; a stronger/different model; decomposed checks). Valid only
where that asymmetry holds — a pack-selection criterion.

**Sampling (active, not naive random):**
- _Uniform_ base layer for an honest population rate.
- _Stratified_ across segments (amount band, vendor, model version) for per-segment CIs.
- _Importance/uncertainty_ oversampling where error is likely or costly (low
  production confidence, high `value_at_risk`, monitor-flagged anomalies).
- _Reweight_ to stay unbiased: if decision _i_ was sampled with prob πᵢ,
  `p̂ = (1/N) · Σ_{i∈sample} errorᵢ / πᵢ`  (Horvitz–Thompson).
- _Sample size_: `n ≈ z²·p(1−p)/e²`; rare error rates (~0.1%) blow this up, so lean on
  (a) the verifier being automated/cheap enough to run broadly and (b) importance
  sampling toward likely-error regions. Split the cost: **verifier broad, humans narrow.**

**Verifier contract:**

```
verifier(decision, pack.verification, adapter.tool_bindings, policy) ->
  { should_have_been ∈ action_space,
    confidence ∈ [0,1],
    reason, failed_check,
    loss_type?, estimated_loss? }

error := should_have_been != decision.action
```

The verifier consumes the customer's **policy doc** as its adjudication standard, so
adjudication is not hand-coded per customer.

**Calibration (who verifies the verifier):**
- Fidelity hierarchy: **gold** (human expert / realized downstream truth) vs **silver**
  (verifier).
- A rolling gold subsample measures the verifier's own FP/FN rate; either correct its
  population estimate for that measured bias, or trust it only where it agrees with
  gold at high rate.
- **Confidence-gate:** high-confidence verdicts used directly; low-confidence escalate
  to the human queue — concentrating scarce human effort on ambiguous cases.

**Combining sources (no double-counting):**
- Partition decisions: those with a gold outcome use it directly and are **not**
  verified; the rest get silver.
- Realized dollars come **only** from realized losses; `loss.expected_usd` (silver) is
  never summed with a realized amount for the same decision.

## Self-validation contract

`ailoss doctor --json` — the machine-readable check a coding agent runs to confirm
integration:

```json
{
  "ok": false,
  "checks": [
    {"id": "tracer_installed",     "ok": true},
    {"id": "pack_adapter_loaded",  "ok": true,  "pack": "ap", "adapter": "acme"},
    {"id": "decisions_emitting",   "ok": true,  "count_1h": 412},
    {"id": "business_key_present", "ok": true,  "coverage": 1.0},
    {"id": "business_key_unique",  "ok": false, "dupe_rate": 0.03,
     "fix": "business_key reused across vendors — namespace by vendor_id"},
    {"id": "gt_source_reachable",  "ok": true,  "sources": ["human_queue","verification_agent"]},
    {"id": "gt_resolvable_rate",   "ok": true,  "value": 0.71},
    {"id": "verifier_calibrated",  "ok": false, "fix": "no gold labels yet; add human_queue or a recovery-audit CSV to calibrate"},
    {"id": "sample_job_scheduled", "ok": false, "fix": "schedule sampler.run()"}
  ]
}
```

- Typed `Decision` / `Outcome` dataclasses with runtime validation → loud dev errors,
  safe no-ops in prod (never break the host agent).
- `gt_resolvable_rate` — fraction of decisions with at least one reachable GT source;
  the early warning that the error rate will be unmeasurable.
- `verifier_calibrated` — flags a silver-only pipeline with no gold anchor.

## Data flow & activation

```
Invoice ─▶ [ agent + @decision ]──tool calls──▶ ERP, payment rail
                 │  in-process: stamp ailoss.* + business_key, emit signed span
                 ▼
        ailoss processor (in customer VPC)
          normalize → sign → redact → sample+verify → compute metrics
                 │                         │
   outcomes ─────┤                         ├─▶ LOCAL dashboard/JSON (no account)
   (human_queue / report_outcome /         └─▶ derived metrics only → hosted (if activated)
    CSV / warehouse / verifier)
```

Adoption funnel, honestly:

```
installed (agent writes code)      ← agent, near-zero friction
   ↓  local-first: full value, we receive NOTHING (correct)
locally valuable (dev sees metrics)
   ↓  ACTIVATION GATE — human-ratified
activated (AILOSS_KEY set)     ← one env var; agent scaffolds it, human authorizes
   ↓  derived metrics now flow to hosted backend
outcome-wired (error rate + $)     ← Tier A day one; B/C as trust deepens
   ↓
downstream aggregation (out of scope)
```

- **Activation is one env var**, agent-scaffoldable; only "paste the key" is the human's.
- **Once-per-org:** after the first human sets the org key in the environment,
  subsequent agent-installs inherit it and data flows with no new human step — agents
  then propagate instrumentation org-wide.
- **Only derived metrics egress** (never raw), keeping the activation security review small.

## Packaging for agent discovery

- **`llms.txt`** at the docs root: what it is + shortest correct usage + attribute
  list + pack/adapter recipe.
- **MCP server** (`ailoss-mcp`): `how_to_instrument(framework)`,
  `write_adapter(system)`, `validate_integration()`, `explain_attribute(name)`.
- **Coding-agent skill** (`instrument-agent-reliability`) with the canonical recipe.
- **Rules snippet** for `CLAUDE.md` / `AGENTS.md` / `.cursorrules`.
- **Framework plugins:** `ailoss-langgraph`, `ailoss-crewai` (auto-wrap tool nodes).
- High-signal README + clean registry metadata.

## What the SDK computes

- **Confusion matrix + error rate** by segment, Wilson CIs, inverse-prob weighted.
- **Realized loss** (hard, from gold outcomes) and **expected loss**
  (`Σ volume × error_rate × loss_given_error`).
- **Counterfactual vs. baseline** — the agent's incremental risk vs. the prior
  human/ERP process (the sellable ROI number).
