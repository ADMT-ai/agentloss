#!/usr/bin/env bash
#
# build.sh — assemble the agentloss.com static site into ./public
#
# Key job: copy llms.txt FRESH from the repo root at build time, so the deployed
# site always serves the current llms.txt. We never commit a static copy of it
# (its content is edited concurrently in the package repo).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/public"

# Locate the repo root (where llms.txt lives). Prefer git; fall back to ../.
if REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  :
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

echo "site build: SCRIPT_DIR=$SCRIPT_DIR"
echo "site build: REPO_ROOT=$REPO_ROOT"

# Clean + recreate output.
rm -rf "$OUT"
mkdir -p "$OUT"

# Static assets that make up the site.
# The fd55...txt file is the IndexNow key (Bing/Yandex/DuckDuckGo instant indexing);
# it must be served verbatim at the domain root — see build note below.
for f in index.html styles.css copy.js favicon.svg og.svg robots.txt sitemap.xml fd55bf3236d6a56a011cc9041602c1c8.txt; do
  cp "$SCRIPT_DIR/$f" "$OUT/$f"
done

# Copy llms.txt into the published root. This is the canonical
# agentloss.com/llms.txt served to coding agents. Prefer the repo-root copy (the
# source of truth, edited concurrently in the package repo). Fall back to a
# co-located site/llms.txt only if a CI step synced one here (e.g. a CLI deploy
# that uploads just this folder without the repo root).
LLMS_SRC=""
if [ -f "$REPO_ROOT/llms.txt" ]; then
  LLMS_SRC="$REPO_ROOT/llms.txt"
elif [ -f "$SCRIPT_DIR/llms.txt" ]; then
  LLMS_SRC="$SCRIPT_DIR/llms.txt"
fi

if [ -n "$LLMS_SRC" ]; then
  cp "$LLMS_SRC" "$OUT/llms.txt"
  echo "site build: copied llms.txt from $LLMS_SRC ($(wc -c < "$OUT/llms.txt" | tr -d ' ') bytes)"
else
  echo "site build: ERROR — llms.txt not found at $REPO_ROOT/llms.txt or $SCRIPT_DIR/llms.txt" >&2
  exit 1
fi

echo "site build: output ->"
ls -1 "$OUT"
echo "site build: done."
