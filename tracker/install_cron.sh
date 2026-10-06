#!/bin/sh
# Linux/macOS: run the server-age tracker every 10 minutes from cron (append only, backs up, idempotent).
# Usage: sh install_cron.sh        (run it from anywhere; it uses this folder)
set -e
D=$(cd "$(dirname "$0")" && pwd)
PY=$(command -v python3)
BK="$HOME/crontab.bak-lt2tracker-$(date +%Y%m%d%H%M%S)"
crontab -l > "$BK" 2>/dev/null || true
echo "backup: $BK"
if crontab -l 2>/dev/null | grep -q lt2_tracker.py; then
  echo "already installed"
  exit 0
fi
LOCK=""
FL=$(command -v flock || true)
if [ -n "$FL" ]; then LOCK="$FL -n $D/tracker.lock "; fi
( crontab -l 2>/dev/null; echo "*/10 * * * * ${LOCK}$PY $D/lt2_tracker.py >> $D/tracker.log 2>&1" ) | crontab -
echo "installed:"
crontab -l
