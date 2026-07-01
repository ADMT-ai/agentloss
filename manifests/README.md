# Gateway manifests for real MCP servers

A manifest is a [pack](../docs/PACKS.md), as data: which of a server's tools are consequential
(and where the exposure + join key live), and which tool exposes the reversals that become gold
ground truth. Format: [docs/GATEWAY.md](../docs/GATEWAY.md).

Use one:

```bash
agentloss gateway --manifest manifests/stripe-mcp.manifest.json -- npx -y @stripe/mcp --api-key $STRIPE_SECRET_KEY
```

## Don't see your server? Draft it in one command

```bash
agentloss gateway init --out my.manifest.json -- <your server command>          # local
agentloss gateway init --out my.manifest.json \
    --url https://<hosted-server> --header "Authorization: Bearer ..."          # hosted
```

`init` reads the server's own `tools/list`, classifies the money-movers and reversal reads with
transparent heuristics, and — because reads are safe — probes zero-argument reversal tools to
derive the row paths from the server's real response shape. Anything it can't establish is an
explicit `_todo` marker; a coding agent can resolve those in one pass (call the tool once, read
the shape). Then confirm with traffic + `agentloss_doctor`.

Proven by `examples/gateway_init_eval.py`: against the mock SoR, `init` drafts a manifest that
recovers the oracle's error rate and dollar loss with no edits.

## Shipped manifests

| file | server | status |
|---|---|---|
| `stripe-mcp.manifest.json` | official Stripe MCP (`@stripe/mcp` / mcp.stripe.com) | **draft** — written against the published tool names; verify against your server version (tool sets vary by `--tools` flags): re-run `gateway init` and diff, then `agentloss_doctor` |

## Contributing a manifest

1. `agentloss gateway init --out <server>.manifest.json -- <server command>` against your server.
2. Resolve the `_todo` markers (one call per tool to see the result shape).
3. Run traffic through the gateway; check `agentloss_doctor` comes back `ok`.
4. PR the manifest with a note on the server version you verified against.
