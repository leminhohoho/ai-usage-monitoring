#!/usr/bin/env bash
# send-usage.sh - push this machine's spooled AI usage to the monitor.
#
#   ./send-usage.sh              send everything spooled
#   ./send-usage.sh --dry-run    show what would be sent, send nothing
#   ./send-usage.sh --status     just report spool size
#
# Config comes from .env.ai-usage (or the environment):
#   AUM_ENDPOINT=https://monitor.internal:9001
#   AUM_API_KEY=aum_xxxxx
#
# Safe to run repeatedly: events carry an event_id and the server dedupes,
# so a double-send is a no-op. Offline runs leave the spool untouched.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

# --- config -----------------------------------------------------------------
if [[ -f .env.ai-usage ]]; then
  # shellcheck disable=SC1091
  set -a; source .env.ai-usage; set +a
fi
: "${AUM_ENDPOINT:?AUM_ENDPOINT is not set (put it in .env.ai-usage)}"
: "${AUM_API_KEY:?AUM_API_KEY is not set (put it in .env.ai-usage)}"

CLIENT="${AUM_CLIENT:-python ai_usage_client.py}"
SPOOL="${AUM_SPOOL:-$HOME/.ai-usage/spool.jsonl}"   # same default as the client

mode="send"
case "${1:-}" in
  --dry-run) mode="dry" ;;
  --status)  mode="status" ;;
  "" ) ;;
  *) echo "usage: $0 [--dry-run|--status]" >&2; exit 2 ;;
esac

lines=0
if [[ -f "$SPOOL" ]]; then
  lines=$(grep -c . "$SPOOL" 2>/dev/null || true)
  lines=${lines:-0}
fi

case "$mode" in
  status)
    printf 'spool: %s event(s) at %s\nendpoint: %s\n' "$lines" "$SPOOL" "$AUM_ENDPOINT"
    exit 0 ;;
  dry)
    printf 'would send %s event(s) to %s\n' "$lines" "$AUM_ENDPOINT"
    [[ "$lines" -gt 0 ]] && tail -n 1 "$SPOOL" | cut -c1-200
    exit 0 ;;
esac

if [[ "$lines" -eq 0 ]]; then
  echo "nothing to send (spool is empty)"
  exit 0
fi

echo "sending $lines event(s) to $AUM_ENDPOINT ..."
if $CLIENT sync; then
  left=0
  [[ -f "$SPOOL" ]] && left=$(grep -c . "$SPOOL" 2>/dev/null || true)
  left=${left:-0}
  echo "done · $((lines - left)) event(s) pushed · $left left in spool"
else
  echo "send failed · nothing was lost, the spool is intact. Retry when back online." >&2
  exit 1
fi
