#!/usr/bin/env bash
# Rebuild the Studies pages from the latest askamerica runs and push whatever changed.
# The catalog workflow deploys on push to main. Safe to run after every askamerica run.
set -euo pipefail
cd "$(dirname "$0")"
EVAL_CORPUS="${EVAL_CORPUS:-/Volumes/main/Users/kennethstott/IdeaProjects/calcite/.claude/skills/askamerica-comparative-eval}" \
  python3 build_studies.py >/dev/null
cd ..
git add web/studies web/studies.html web/build_studies.py web/publish_studies.sh
if git diff --cached --quiet; then echo "studies: nothing changed"; exit 0; fi
changed=$(git diff --cached --name-only | grep -c '^web/studies/.*/index.html$' || true)
git commit -q -m "chore(studies): publish ${changed} updated askamerica stud$([ "$changed" = 1 ] && echo y || echo ies)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GDnaeYypxZeQfrWWHd1DaC"
git pull -q --rebase origin main && git push -q origin main
echo "studies: published ${changed} page(s) — $(git log --oneline -1)"
