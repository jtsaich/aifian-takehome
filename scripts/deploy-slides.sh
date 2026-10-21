#!/usr/bin/env bash
# Publish docs/slides (the design presentation) as a static-assets Cloudflare Worker.
#   scripts/deploy-slides.sh            # Worker bakery-orders-design → https://bakery-orders-design.<account>.workers.dev
# Requires `npx wrangler login` once. The page loads the charts as ../workflow-*.svg: that is
# docs/ when opened from the repo, and the site root once deployed (../ stops at the root).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
name="${WORKER_NAME:-bakery-orders-design}"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

cp "$root/docs/slides/index.html" "$out/"
cp "$root/docs/workflow-now.svg" "$root/docs/workflow-after.svg" "$out/"

npx -y wrangler deploy --name "$name" --assets "$out" --compatibility-date 2026-10-01
