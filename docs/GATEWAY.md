# The agentloss gateway — measure any agent at the MCP boundary

**Status: shipped — `agentloss gateway` (0.0.12), the `gateway init` manifest scaffolder
(0.0.13), and soft outcomes / the synthetic SoR ladder (0.0.18), each proven end-to-end by
an oracle eval (`examples/gateway_eval.py`, `examples/gateway_init_eval.py`,
`examples/sor_ladder_eval.py`).**

## Why a gateway

agentloss's job is a join: capture the **consequential action** where the agent commits it, detect
the **reversal** in the system of record, and match the two on `business_key`. Until now both halves
required Python code inside the agent's process (`@decision`, packs, detectors).

But the decision path and the system of record are converging on one interface: **MCP**. Businesses
connect agents to Stripe, ERPs, CRMs, and ticketing through MCP servers — which means the
consequential tool call already crosses a protocol boundary we can stand on, in every language, in
every agent runtime.

The gateway is agentloss **as MCP middleware**: a transparent stdio proxy you put in front of the
SoR's MCP server. One config change — no agent code change — yields all three pieces:

1. **Decision capture for free.** Every consequential `tools/call` through the proxy records a
   `Decision`; `value_at_risk` and `business_key` are extracted from the call's arguments/result by
   a per-server **manifest** (the pack contract, lifted one layer up).
2. **Ground truth from the same connection.** The same MCP server that executed the payment exposes
   the disputes/credit-memos. The manifest declares the *reversal tool*; the gateway calls it and
   turns its rows into gold outcomes (`agentloss_sync_outcomes`).
3. **Language independence.** A TypeScript LangGraph agent, an n8n flow, or Claude Code itself —
   anything that speaks MCP is now measurable. The SDK stops being Python-only at the boundary that
   matters.

It also makes the *measurement itself* agent-native: the gateway injects `agentloss_*` tools into
the downstream server's `tools/list`, so the agent (or the operator's agent) can ask for the error
rate, dollar loss, and doctor findings **through the same connection it acts through**.

```
┌─────────────┐   MCP (stdio JSON-RPC)   ┌────────────────────┐   MCP    ┌──────────────────┐
│  any agent   │ ───────────────────────▶ │  agentloss gateway  │ ───────▶ │  SoR MCP server   │
│ (any runtime)│ ◀─────────────────────── │  manifest + store   │ ◀─────── │ (Stripe, ERP, …)  │
└─────────────┘   + agentloss_* tools     └────────────────────┘          └──────────────────┘
                                            │  decisions + outcomes → JSONL store
                                            ▼
                                agentloss report/doctor --store  (CLI, MCP stub, CI)
```

## Usage

```bash
# instead of:                stripe-mcp --api-key ...
# run:
agentloss gateway --manifest stripe.manifest.json --store .agentloss/store.jsonl -- stripe-mcp --api-key ...

# or, for a REMOTE (hosted) MCP server — Streamable HTTP, auth via headers:
agentloss gateway --manifest stripe.manifest.json \
    --url https://mcp.stripe.com --header "Authorization: Bearer $STRIPE_KEY"
```

Or in an MCP client config (Claude Code / Claude Desktop / any MCP host):

```json
{
  "mcpServers": {
    "stripe": {
      "command": "agentloss",
      "args": ["gateway", "--manifest", "stripe.manifest.json", "--", "stripe-mcp", "--api-key", "..."]
    }
  }
}
```

The agent sees the same server it always saw — same tools, same results — plus four new tools:

| injected tool | what it does |
|---|---|
| `agentloss_report` | error rate (with CI), expected + realized dollar loss, from the gateway's store |
| `agentloss_doctor` | the self-check — catches the silent failures (0% rate, only-errors, uncounted loss) |
| `agentloss_sync_outcomes` | calls the manifest's reversal tool downstream, maps rows → gold outcomes |
| `agentloss_record_outcome` | report one resolved outcome by hand (ground truth from outside the rail) |

## The manifest — a pack as data

A manifest is what a pack is in code, expressed as JSON so it works for servers we've never seen
and can be written by a coding agent from the SoR server's own `tools/list`. Two sections mirror
the two pack halves:

```json
{
  "version": 1,
  "use_case": "payments",
  "tools": {
    "create_payment": {
      "amount": "arguments.amount",
      "currency": "arguments.currency",
      "business_key": "result.id",
      "action": "approve"
    }
  },
  "outcomes": {
    "list_disputes": {
      "items": "result.disputes",
      "business_key": "item.payment_id",
      "status": "item.status",
      "loss": "item.amount",
      "error_statuses": ["lost"],
      "correct_statuses": ["won"],
      "source": "chargeback",
      "census": true
    }
  }
}
```

- **`tools`** — which downstream tools are consequential (the money-movers), and where the
  exposure and join key live. Values are dotted paths rooted at `arguments` (the `tools/call`
  arguments) or `result` (the tool's structured result). Everything not listed passes through
  untouched — *instrument the consequential action, not the whole agent* holds at the protocol
  layer too.
- **`outcomes`** — the reversal tool(s) and how to read their rows: path to the row array
  (`items`), then per-row (`item.*`) paths for the join key, the status, and the dollar loss.
  `error_statuses` / `correct_statuses` map the SoR's vocabulary onto ground truth; rows in
  neither set are non-final and skipped (the detector contract). `census: true` marks every
  other captured decision correct, so the denominator is right.

Result paths prefer MCP `structuredContent`; if absent, the gateway JSON-parses the first
`text` content block — the two shapes real MCP servers return.

An outcome tool that pages its rows declares `"paginate": {"cursor":
"result.next_cursor", "arg": "cursor"}` — sync re-calls the tool with the previous
response's cursor until it comes back empty, so page one alone never under-counts. `init`
detects the cursor from the probed response shape and drafts this itself.

### Soft outcomes — infer the outcome, estimate the loss

Not every SoR writes `"status": "lost"`. Often the resolution lives in **free text** (a
case note, a complaint thread) and the dollar figure may be missing entirely. Declare the
outcome tool with `"mode": "infer"` and the gateway reads the rows instead of looking them
up (`agentloss.inference` — deterministic marker vocabulary, overridable per manifest):

```json
"list_case_notes": {
  "mode": "infer",
  "items": "result.cases",
  "business_key": "item.payment_id",
  "evidence": ["item.note"],
  "loss_fallback": "value_at_risk",
  "source": "inferred",
  "census": true
}
```

- **Outcome**: error markers ("chargeback lost", "clawed back", "refunded", ...) vs
  correct markers ("in merchant favor", "no merchant error", ...); neither matching means
  non-final (skipped, out of the census). When both sides match, the marker appearing
  last in the text wins — resolution language concludes the note. Override the vocabulary
  with `error_markers` / `correct_markers`.
- **Loss**, in order of fidelity: an explicit `loss` column if the rows have one; else
  the first dollar amount written in the evidence ("refunded $200.00" — partial losses
  read correctly); else the decision's own value-at-risk (`loss_fallback` — full
  exposure, the conservative bound). `loss_fallback: value_at_risk` also works in status
  mode, for enums whose rows carry no amount.
- **Honesty**: inferred verdicts are **silver** — recorded with `fidelity: "silver"`, a
  confidence below 1.0, and the dollars as *estimated* loss (they flow through
  `expected_loss_usd`, never `realized_loss_usd`), so an inferred number is never passed
  off as a looked-up one. Feed them through sampling + two-phase calibration
  (`agentloss.calibrate`) to bias-correct against a small gold budget, exactly as with a
  fallible verifier.

### Writing a manifest for a new server: `gateway init`

This is the judgment a coding agent (or you) makes once per SoR, and it's the same two questions
packs ask: *which tool moves money?* and *which tool exposes the reversals?* `init` scaffolds it:

```bash
agentloss gateway init --out my.manifest.json [--use-case slug] [--no-probe] -- <server command>
agentloss gateway init --out my.manifest.json --url https://<hosted-server> \
    --header "Authorization: Bearer ..."          # hosted servers: same probe, over HTTP
```

It calls the downstream `tools/list`, classifies money-movers (committing verb + money noun, or
an amount-like schema property; read-prefixed tools never qualify) and outcome reads (read
prefix + a reversal noun — dispute/chargeback/credit-memo/... — or a resolution noun —
note/case/ticket/...). Because reads are safe, it then **probes** each zero-argument candidate
and derives `items` / `item.*` paths and the status mapping from the server's real response
shape. Rows with no status field but free-text fields are drafted as `"mode": "infer"` (soft
outcomes), with `loss_fallback: value_at_risk` when no amount column exists either. A status
enum the default vocabulary doesn't know (MERCHANT_DEBIT, ...) gets **learned**: init infers
each probed row's verdict from its free-text fields and groups the statuses by verdict —
declared via `_learned_statuses` (an ambiguous status lands in neither set), so execution
still runs in gold status mode. The draft
also carries a **`business_context`** block — the domain it understood the server to be
(payments/billing/orders/...), the money-movers, and each outcome channel's mode — so the
onboarding judgment is reviewable, not implicit; without `--use-case`, the use case is the
understood domain. Anything unresolved is an explicit `_todo` a coding agent can finish in one
pass; minor-unit amounts get `amount_divisor: 100` with a note. Proven by
`examples/gateway_init_eval.py` and `examples/sor_ladder_eval.py`: against the mock SoRs, the
drafted manifests recover the oracle numbers with zero edits. Ready-made manifests live in
`manifests/`.

The manual recipe, when you'd rather look yourself:

1. `tools/list` the downstream server. Pick the money-movers; note the argument that carries the
   amount and the result field that carries the durable id.
2. Find the reversal read — disputes, credit memos, refunds, corrections. Note the row fields for
   target id, status, amount.
3. Write the manifest, start the gateway, run the agent, call `agentloss_doctor`.

For the Stripe MCP server the mapping is the shipped Stripe pack, as data: money-movers
`create_payment_intent` / `create_payment_link` (amount in `arguments.amount`, key in
`result.id`), reversal read `list_disputes` (`item.status` ∈ {lost} → error, {won} → correct,
`item.amount` minor units — set `"amount_divisor": 100`). Zero-decimal currencies and
reason-based attribution stay in `agentloss.detectors.stripe` for the SDK path; manifests keep
to the 90% case and hand the rest to a detector.

## Design decisions

- **Zero dependencies, raw JSON-RPC.** The stdio transport is newline-delimited JSON-RPC 2.0; the
  proxy relays bytes and inspects only three message shapes (`tools/list` responses, `tools/call`
  requests/responses). No `mcp` package required, nothing to version-chase, and the same code is
  testable with pipes.
- **Two downstream transports, one interception.** The agent side is always stdio; the downstream
  is either a spawned local server (`-- <command>`) or a remote Streamable-HTTP server (`--url`,
  stdlib urllib): POST per message, `application/json` and `text/event-stream` responses both
  parsed, `Mcp-Session-Id` captured from initialize and echoed thereafter, negotiated
  `MCP-Protocol-Version` sent once known, auth via repeatable `--header`. A transport failure
  surfaces to the agent as a JSON-RPC error response — never a fabricated business result. (The
  optional server-opened GET/SSE channel for server-initiated requests is not yet spoken.)
- **Fail open.** Instrumentation must never break the business call: malformed manifest paths,
  unparsable results, store write failures — the message is still relayed, the decision is just
  not captured (and `agentloss_doctor` will say so). Same rule as `packs.capture`.
- **A persistent store, at last.** The proxy is a separate process from whoever wants the number,
  so the gateway appends every decision/outcome to a JSONL store (`--store`, default
  `.agentloss/store.jsonl`). `agentloss doctor --store` and `agentloss report --store` read it —
  which also gives *SDK* users a way to check wiring from a shell, and gives the MCP stub's
  `validate_integration` a real store to inspect instead of a static checklist.
- **Internal downstream calls.** `agentloss_sync_outcomes` issues its own `tools/call` to the
  downstream server with a reserved id namespace (`agentloss-N`), so gateway-originated requests
  and agent requests never collide.
- **The join stays explicit.** Decisions and outcomes are separate rows joined on `business_key`,
  exactly as in the SDK — the gateway is new capture, not a new model.

## What this replaces / composes with

| layer | in-process (Python SDK) | at the boundary (gateway) |
|---|---|---|
| capture | `@decision`, `packs.capture`, `packs.tools` | manifest `tools` section |
| ground truth | `detectors.*`, `outcomes_from_reversals` | manifest `outcomes` + `agentloss_sync_outcomes` |
| self-check | `agentloss.doctor()` | `agentloss_doctor` tool / `agentloss doctor --store` |
| statistics | same core: census default, sampling, calibration | same — the store feeds the same metrics |

Use the SDK when you own the agent's Python code and want per-decision context for the verifier;
use the gateway when the agent is not Python, not yours to edit, or already talks to the SoR over
MCP. Both write the same shapes; both are honest about the denominator.

## Proven by

- `examples/gateway_eval.py` — an oracle eval in the house style: a mock SoR MCP server seeded
  with *known* disputes, a scripted agent driving payments through the gateway, then
  `agentloss_sync_outcomes` + `agentloss_report` through the same connection; asserts the
  recovered error rate and dollar loss match the oracle exactly, that non-consequential tools
  record nothing, and that the store round-trips into `agentloss report --store`.
- `examples/sor_ladder_eval.py` — the **synthetic SoR ladder**
  (`examples/gateway/sor_ladder_server.py`): one mock SoR, five rungs of outcome mess —
  level 0 explicit status enum; level 1 free-text note, amount column (outcome inferred);
  level 2 note only (loss estimated too); level 3 unknown status vocabulary (the mapping is
  learned from the rows' own text at onboarding, then execution runs gold status mode);
  level 4 paginated outcome read (cursor detected at onboarding, followed to the end at
  sync). Per rung it runs the whole agentic loop with zero
  hand-written config — onboard (`gateway init`), execute (scripted agent), deliver (sync +
  report + doctor through the same connection) — and asserts the SAME oracle rate and dollar
  loss come back: realized dollars at level 0, expected (silver) dollars above it. This is the
  dogfood-eval-fix-iterate harness: run the loop, find where a rung breaks the recovery, fix,
  then add a messier rung.
- `tests/test_gateway.py`, `tests/test_inference.py` — the same flows under pytest, run in CI
  on every push.

## Roadmap

- ~~**`agentloss gateway init`**~~ — ✅ shipped (0.0.13): heuristic classification + safe probing
  of reversal reads; proven by `examples/gateway_init_eval.py`.
- ~~**HTTP transport**~~ — ✅ shipped (0.0.14): `--url` + `--header` speak Streamable HTTP to
  remote/hosted servers; proven by `examples/gateway_http_eval.py` against a strict mock (session
  enforcement + SSE responses). `init --url` shipped in 0.0.15
  (`examples/gateway_init_http_eval.py`: URL in, dollar-loss numbers out, zero hand-written
  config). Still open: the server-opened GET/SSE channel.
- **Manifests for real servers** — Stripe MCP draft shipped (`manifests/`); next: ERPNext/NetSuite
  MCP, GitHub (a merge is a commitment; a revert is a reversal). Each is a JSON file + an eval
  fixture, not a new pack.
- ~~**Soft outcomes**~~ — ✅ shipped (0.0.18): `"mode": "infer"` — outcome inferred from
  free-text evidence, loss estimated (parsed from the text, else value-at-risk), recorded
  silver so it feeds the existing sampling + calibration for an honest number. Proven up the
  synthetic SoR ladder (`examples/sor_ladder_eval.py`). Still open: an LLM reasoner rung
  (`detectors.reasoning` behind the same manifest contract) for evidence that marker
  vocabulary can't judge.
- **Higher ladder rungs** — the next kinds of mess, one eval'd rung at a time:
  ~~unknown status vocabularies~~ (✅ 0.0.19: learned from the rows' own text at init),
  ~~paginated outcome reads~~ (✅ 0.0.20: `paginate` — cursor detected at init, followed at
  sync), outcomes split across tools (join two reads), delayed/duplicated resolutions, and a
  live-LLM reasoner rung measured against the same oracle.
