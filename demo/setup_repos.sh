#!/usr/bin/env bash
# setup_repos.sh - (re)create the three demo repos from scratch.
#
#   ./demo/setup_repos.sh [--endpoint URL]
#
# Each repo gets the same three-file footprint a real team would add:
#   ai_usage_client.py   the client (copied from client/)
#   send-usage.sh        the explicit "send now" script
#   .claude/settings.json  hooks that call the client on session events
#   .env.ai-usage        endpoint + per-engineer API key (NOT committed)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
endpoint="${2:-${AUM_ENDPOINT:-http://127.0.0.1:9001}}"

make_repo() {  # name dev branch
  local name=$1 dev=$2 branch=$3 dir="$here/repos/$1"
  rm -rf "$dir"; mkdir -p "$dir/.claude"
  cp "$root/client/ai_usage_client.py" "$root/client/send-usage.sh" "$dir/"
  chmod +x "$dir/send-usage.sh"
  printf '# %s\n\nDemo repo for ai-usage-monitor. The only additions are the two scripts,\n`.claude/settings.json` and `.env.ai-usage`.\n' "$name" > "$dir/README.md"
  cat > "$dir/.claude/settings.json" <<'JSON'
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "python ai_usage_client.py hook" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python ai_usage_client.py hook" }] }],
    "PostToolUse":      [{ "hooks": [{ "type": "command", "command": "python ai_usage_client.py hook" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "python ai_usage_client.py hook" }] }]
  }
}
JSON
  printf 'AUM_ENDPOINT=%s\nAUM_API_KEY=aum_%s\n' "$endpoint" "$dev" > "$dir/.env.ai-usage"
  git -C "$dir" init -q 2>/dev/null || true
  git -C "$dir" symbolic-ref HEAD "refs/heads/$branch" 2>/dev/null || true
  echo "  $name ($dev, $branch)"
}

make_repo jobbob-frontend alice feature/ai-telemetry
make_repo jobbob-backend  bob   fix/ingest-retry
make_repo jobbot-ingest   carol main
echo "demo repos ready under demo/repos/"
