#!/usr/bin/env bash
#
# deploy.sh — deploy agentloss.com from a CLI (not the git integration).
#
# Why this exists: `vercel --prod` from this folder uploads ONLY site/, so the
# build.sh that runs on Vercel can't see the repo-root llms.txt (the source of
# truth). We stage a transient co-located copy first; build.sh's fallback picks
# it up. The staged copy is gitignored and removed afterward so it never goes
# stale. .vercelignore (committed) ensures the staged llms.txt is uploaded while
# public/ and .vercel are not.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cp "$REPO_ROOT/llms.txt" ./llms.txt
trap 'rm -f "$SCRIPT_DIR/llms.txt"' EXIT

echo "deploy: staged llms.txt ($(wc -c < ./llms.txt | tr -d ' ') bytes); deploying to prod…"
npx --yes vercel --prod --yes "$@"
