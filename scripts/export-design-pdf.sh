#!/usr/bin/env bash
# Export docs/design.md to docs/design.pdf.
# Requires pandoc and Google Chrome / Chromium (headless print-to-PDF; handles CJK fonts without LaTeX).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/docs/design.md"
out="${1:-$root/docs/design.pdf}"

chrome="${CHROME:-}"
if [[ -z "$chrome" ]]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Chromium.app/Contents/MacOS/Chromium" \
           google-chrome chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then chrome="$c"; break; fi
  done
fi
command -v pandoc >/dev/null || { echo "pandoc not found (brew install pandoc)" >&2; exit 1; }
[[ -n "$chrome" ]] || { echo "Chrome/Chromium not found; set CHROME=/path/to/chrome" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
css="$tmp/style.css"
cat >"$css" <<'CSS'
body { font-family: "PingFang TC", "Noto Sans TC", "Heiti TC", sans-serif; font-size: 10.5pt; line-height: 1.6; max-width: none; margin: 0; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th, td { border: 1px solid #999; padding: 3px 6px; vertical-align: top; }
code { font-size: 9pt; }
@page { size: A4; margin: 18mm 16mm; }
CSS

pandoc "$src" --standalone --embed-resources --css "$css" \
  -o "$tmp/design.html"
"$chrome" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$out" "file://$tmp/design.html" 2>/dev/null
echo "wrote $out"
