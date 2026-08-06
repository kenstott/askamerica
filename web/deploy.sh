#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is not set}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is not set}"
: "${CLOUDFLARE_PROJECT_NAME:?CLOUDFLARE_PROJECT_NAME is not set}"

if ! command -v wrangler &>/dev/null; then
  echo "wrangler not found — installing..."
  npm install -g wrangler
fi

# Stage a clean copy so secrets and tooling never reach the CDN.
# (2026-08-06: a whole-directory deploy published .env — see incident notes.)
DIST="$(mktemp -d)"
trap 'rm -rf "$DIST"' EXIT
rsync -a \
  --exclude='.env*' \
  --exclude='deploy.sh' \
  --exclude='.wrangler' \
  --exclude='node_modules' \
  --exclude='.DS_Store' \
  "$SCRIPT_DIR/" "$DIST/"

if [ -e "$DIST/.env" ]; then
  echo "refusing to deploy: .env present in staging dir" >&2
  exit 1
fi

echo "Deploying to Cloudflare Pages project: $CLOUDFLARE_PROJECT_NAME"
CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" \
CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
wrangler pages deploy "$DIST" \
  --project-name "$CLOUDFLARE_PROJECT_NAME" \
  --commit-dirty=true
