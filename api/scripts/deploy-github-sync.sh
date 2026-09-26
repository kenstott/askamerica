#!/usr/bin/env bash
# Deploys the report_issue fix: persists the `type` column that was silently dropped, and
# adds the scheduled github-sync.ts job that files new /v1/issues rows into
# kenstott/govdata-ops. Touches the live askamerica-api Worker and its production D1
# database — run this yourself; nothing in this repo runs it automatically.
#
# Usage:
#   ./scripts/deploy-github-sync.sh            # full run, asks to confirm before each
#                                               # production-touching step
#   ./scripts/deploy-github-sync.sh --yes      # same, but skip the confirmation prompts
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

AUTO_YES=false
for arg in "$@"; do
  [[ "$arg" == "--yes" || "$arg" == "-y" ]] && AUTO_YES=true
done

confirm() {
  local prompt="$1"
  $AUTO_YES && return 0
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

echo "== 1/5: npm test =="
npm test

echo
echo "== 2/5: apply D1 migration 0003 (adds type + github_* columns to the LIVE issues table) =="
if confirm "Run 'wrangler d1 execute askamerica --remote --file migrations/0003_issue_type_and_github_sync.sql'?"; then
  npx wrangler d1 execute askamerica --remote --file migrations/0003_issue_type_and_github_sync.sql
else
  echo "Skipped migration. github-sync.ts will fail at runtime without these columns — do not deploy until this has run at least once."
  exit 1
fi

echo
echo "== 3/5: GITHUB_TOKEN secret =="
if npx wrangler secret list 2>/dev/null | grep -q '"GITHUB_TOKEN"'; then
  echo "GITHUB_TOKEN is already set on this Worker. Leaving it as-is."
  echo "(To rotate it, run: wrangler secret put GITHUB_TOKEN)"
else
  echo "GITHUB_TOKEN is not set yet. It needs a GitHub PAT (classic or fine-grained) with"
  echo "issue-write access to kenstott/govdata-ops. Until it's set, github-sync.ts's"
  echo "scheduled job is a safe no-op (it checks env.GITHUB_TOKEN and returns early)."
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "Found an authenticated 'gh' CLI session (repo scope confirmed to work against"
    echo "kenstott/govdata-ops already this session)."
    if confirm "Use 'gh auth token' as GITHUB_TOKEN? (No if you'd rather use a separate, narrower-scoped PAT.)"; then
      gh auth token | npx wrangler secret put GITHUB_TOKEN
    elif confirm "Set it manually instead (wrangler secret put GITHUB_TOKEN, typed interactively)?"; then
      npx wrangler secret put GITHUB_TOKEN
    else
      echo "Skipping. The Worker will deploy, but the sync job will do nothing until this is set."
    fi
  elif confirm "'gh' CLI not authenticated here — set GITHUB_TOKEN manually instead (typed interactively)?"; then
    npx wrangler secret put GITHUB_TOKEN
  else
    echo "Skipping. The Worker will deploy, but the sync job will do nothing until this is set."
  fi
fi

echo
echo "== 4/5: deploy =="
if confirm "Run 'wrangler deploy' now? This updates the LIVE askamerica-api Worker."; then
  npx wrangler deploy
else
  echo "Skipped deploy. Nothing else below will reflect reality until this runs."
  exit 1
fi

echo
echo "== 5/5: verify =="
echo "-- Cron schedule registered on the deployed Worker: --"
npx wrangler triggers 2>/dev/null || echo "(wrangler triggers not available in this wrangler version — check the dashboard instead: Workers & Pages > askamerica-api > Triggers)"
echo
echo "-- Tail logs for the next 30s to confirm no startup errors (Ctrl+C to stop early): --"
timeout 30 npx wrangler tail --format pretty || true

echo
echo "Done. The sync job runs every 15 minutes (see wrangler.toml [triggers]). To force one"
echo "run immediately for testing rather than waiting: trigger it via the Cloudflare dashboard"
echo "(Workers & Pages > askamerica-api > Triggers > Cron Triggers > Trigger event), or file a"
echo "throwaway test report against POST https://api.askamerica.ai/v1/issues and watch the next"
echo "scheduled run pick it up."
