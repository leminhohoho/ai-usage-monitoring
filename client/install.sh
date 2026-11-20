#!/usr/bin/env bash
# install.sh - set up AI-usage reporting in ONE repository.
#
#   Local (from a checkout):
#     ./client/install.sh                     # installs into the current directory
#     ./client/install.sh --repo ../my-repo   # or into another repo
#
#   Remote (no checkout needed):
#     curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/client/install.sh | bash
#     curl -fsSL .../install.sh | bash -s -- --endpoint http://monitor:9001
#
# What it does (idempotent; safe to re-run):
#   1. copies ai_usage_client.py + send-usage.sh into the target repo
#   2. writes .env.ai-usage from your --endpoint/--key, or leaves a template to fill in
#   3. adds .claude/settings.json hooks (merged, never clobbering existing hooks)
#   4. adds the local artifacts to .gitignore so nothing secret is ever committed
#   5. prints the one command the engineer needs: ./send-usage.sh
set -euo pipefail

REPO="."
ENDPOINT=""
KEY=""
FORCE=0
RAW="https://raw.githubusercontent.com/leminhohoho/ai-usage-monitoring/main/client"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)      REPO="$2"; shift 2 ;;
    --endpoint)  ENDPOINT="$2"; shift 2 ;;
    --key)       KEY="$2"; shift 2 ;;
    --raw)       RAW="$2"; shift 2 ;;
    --force)     FORCE=1; shift ;;
    -h|--help)   sed -n '2,20p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- where are we? -----------------------------------------------------------
# When piped from curl, BASH_SOURCE is not a real file, so fall back to downloading.
SRC_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
  SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

fetch() {  # fetch <remote-name> <dest>
  if [[ -n "$SRC_DIR" ]] && [[ -f "$SRC_DIR/$1" ]]; then
    cp "$SRC_DIR/$1" "$2"; return 0
  fi
  local url="$RAW/$1"
  command -v curl >/dev/null || die "need curl to download $1"
  curl -fsSL "$url" -o "$2" || die "could not download $url"
}

[[ -d "$REPO" ]] || die "no such directory: $REPO"
cd "$REPO"
[[ -d .git ]] || warn "this is not a git repository (continuing anyway)"

say "installing AI-usage reporting into $(pwd)"

# --- 1. the files ------------------------------------------------------------
fetch ai_usage_client.py ai_usage_client.py
ok "ai_usage_client.py"
fetch send-usage.sh send-usage.sh
chmod +x send-usage.sh
ok "send-usage.sh (executable)"

# --- 2. config ---------------------------------------------------------------
if [[ -f .env.ai-usage ]] && [[ $FORCE -eq 0 ]]; then
  ok ".env.ai-usage already exists (left untouched; --force to overwrite)"
else
  {
    echo "# AI-usage reporting - DO NOT COMMIT THIS FILE"
    echo "AUM_ENDPOINT=${ENDPOINT:-http://monitor.internal:9001}"
    echo "AUM_API_KEY=${KEY:-REPLACE_ME}"
  } > .env.ai-usage
  chmod 600 .env.ai-usage
  ok ".env.ai-usage written"
  [[ "${KEY:-}" == "" ]] && warn "put your real API key in .env.ai-usage (get it from the monitor admin)"
fi
if [[ -f .env.ai-usage ]] && grep -q '^AUM_API_KEY=REPLACE_ME' .env.ai-usage; then
  warn "AUM_API_KEY is still a placeholder - reporting will fail until you set it"
fi

# --- 3. hooks ----------------------------------------------------------------
mkdir -p .claude
HOOK_CMD="python ai_usage_client.py hook"
python3 - "$HOOK_CMD" <<'PY'
import json, pathlib, sys
cmd = sys.argv[1]
p = pathlib.Path(".claude/settings.json")
cfg = {}
if p.exists():
    try:
        cfg = json.loads(p.read_text() or "{}")
    except Exception:
        sys.exit("  ! .claude/settings.json is not valid JSON - not touching it")
hooks = cfg.setdefault("hooks", {})
added = []
for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "SessionEnd"):
    entries = hooks.setdefault(event, [])
    already = any(
        h.get("command") == cmd
        for e in entries for h in (e.get("hooks") or [])
    )
    if not already:
        entries.append({"hooks": [{"type": "command", "command": cmd}]})
        added.append(event)
p.write_text(json.dumps(cfg, indent=2) + "\n")
print("  \033[32m✓\033[0m .claude/settings.json: " + (", ".join(added) if added else "hooks already present"))
PY

# --- 4. gitignore ------------------------------------------------------------
touch .gitignore
added=0
for pat in ".env.ai-usage" ".ai-usage/"; do
  if ! grep -qxF "$pat" .gitignore 2>/dev/null; then
    echo "$pat" >> .gitignore; added=1
  fi
done
[[ $added -eq 1 ]] && ok ".gitignore: secrets and local spool excluded" || ok ".gitignore already correct"

# --- 5. next step ------------------------------------------------------------
cat <<EOF

$(say "done")
The agent now records locally. To send it to the monitor:

    ./send-usage.sh              # push what is spooled
    ./send-usage.sh --status     # how many events are waiting
    ./send-usage.sh --dry-run    # show what would be sent

Nothing leaves this machine until an engineer runs that command.
EOF
