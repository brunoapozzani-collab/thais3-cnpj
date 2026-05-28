#!/bin/bash
# deploy.sh — one command to publish app.html to Supabase + GitHub Pages
# Usage: bash deploy.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_HTML="$PROJECT_DIR/supabase/functions/debora/app.html"
HTML_TS="$PROJECT_DIR/supabase/functions/debora/html.ts"

# Load deploy-tooling environment (Supabase access token) from .env.deploy.
# Runtime API config (CNPJá etc.) lives in .env — kept separate to avoid mixing
# deploy-only creds with the app's runtime config (Stage 5 R5 / R4 incident).
if [ -f "$PROJECT_DIR/.env.deploy" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env.deploy"
  set +a
fi

if [ -z "$SUPABASE_ACCESS_TOKEN" ]; then
  echo "ERROR: SUPABASE_ACCESS_TOKEN not set. Add it to $PROJECT_DIR/.env.deploy (or export it) and re-run." >&2
  exit 1
fi

PROJECT_REF=antgruwugsizmtcfjglo

echo "=== Step 1: Re-encode html.ts from app.html ==="
base64 -i "$APP_HTML" | tr -d '\n' | \
  awk '{print "export const APP_HTML_B64 = \""$0"\";"}' > "$HTML_TS"
echo "html.ts updated ($(wc -c < "$HTML_TS" | tr -d ' ') bytes)"

echo ""
echo "=== Step 2: Deploy Supabase Edge Function ==="
cd "$PROJECT_DIR"
SUPABASE_ACCESS_TOKEN=$SUPABASE_ACCESS_TOKEN \
  supabase functions deploy debora --project-ref $PROJECT_REF

echo ""
echo "=== Step 3: Push to gh-pages ==="
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git checkout gh-pages
cp "$APP_HTML" ./index.html
git add index.html
git diff --cached --quiet && echo "No changes to index.html" || \
  git commit -m "deploy: sync index.html from app.html"
git push origin gh-pages
git checkout "$CURRENT_BRANCH"

echo ""
echo "=== Done ==="
echo "Live URL: https://brunoapozzani-collab.github.io/thais3-cnpj/"
echo "Note: GitHub Pages CDN may take 1-5 minutes to propagate."
