#!/usr/bin/env bash
# Publish the reviewer-facing files as a static-assets Cloudflare Worker:
#   /            docs/slides/index.html (design presentation; charts as ../*.svg resolve to the root)
#   /one-pager.pdf  exported from docs/boss-one-pager.md at deploy time
#   /demo.mp4    docs/media/demo.mp4 if present (gitignored; recorded walkthrough of the live site)
#   scripts/deploy-slides.sh            # Worker bakery-orders-design → https://bakery-orders-design.<account>.workers.dev
# Requires `npx wrangler login` once.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
name="${WORKER_NAME:-bakery-orders-design}"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

cp "$root/docs/slides/index.html" "$out/"
cp "$root"/docs/*.svg "$out/"
SRC="$root/docs/boss-one-pager.md" "$root/scripts/export-design-pdf.sh" "$out/one-pager.pdf" >/dev/null
[[ -f "$root/docs/media/demo.mp4" ]] && cp "$root/docs/media/demo.mp4" "$out/"

npx -y wrangler deploy --name "$name" --assets "$out" --compatibility-date 2026-10-01
