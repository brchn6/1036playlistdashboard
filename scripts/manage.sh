#!/usr/bin/env bash
# 1036 Playlist Dashboard — Multi-Station Service Manager
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

cmd="${1:-}"
case "$cmd" in
  start)
    echo "=== Starting 1036 Multi-Station Dashboard ==="

    # Start all 7 proxies
    echo "[1/2] Starting 7 ShazamIO proxies..."
    cd "$ROOT" && python scripts/proxy_manager.py start

    echo ""
    echo "[2/2] Starting multi-station updater..."
    cd "$ROOT"
    # No GIT_AUTO_PUSH: the updater no longer touches git. It writes to SQLite
    # and publishes to Supabase. See .planning/DEPLOY-ARCHITECTURE.md (v3).
    #
    # APPEND (>>), never truncate (>). On 2026-07-14 the collector died on its own
    # and a restart with `>` wiped the log, destroying the only record of why —
    # so a ~58 min collection gap could never be diagnosed. The crash output of
    # the run that died is the whole point of this file.
    echo "=== updater start $(date -Is) ===" >> "$LOG_DIR/updater.log"
    RETENTION_DAYS=45 nohup python scripts/updater.py \
      >> "$LOG_DIR/updater.log" 2>&1 &
    echo "[OK] Updater PID: $!"

    echo ""
    echo "=== All services started ==="
    python "$ROOT/scripts/proxy_manager.py" status
    ;;

  stop)
    echo "=== Stopping ==="
    echo "[1/2] Stopping updater..."
    pkill -f "scripts/updater.py" 2>/dev/null || true
    sleep 1

    echo "[2/2] Stopping proxies..."
    cd "$ROOT" && python scripts/proxy_manager.py stop
    echo "=== All stopped ==="
    ;;

  status)
    echo "=== 1036 Multi-Station Dashboard — Status ==="
    echo ""
    echo "--- Proxies ---"
    cd "$ROOT" && python scripts/proxy_manager.py status
    echo ""
    echo "--- Updater ---"
    if pgrep -f "scripts/updater.py" > /dev/null 2>&1; then
      echo "  ✅ Updater running (PID $(pgrep -f 'scripts/updater.py' | head -1))"
    else
      echo "  ❌ Updater not running"
    fi
    echo ""
    echo "--- Health ---"
    cd "$ROOT" && python scripts/proxy_manager.py health
    ;;

  restart)
    "$0" stop
    sleep 2
    "$0" start
    ;;

  generate)
    echo "=== Generating aggregates + publishing to Supabase ==="
    cd "$ROOT" && python scripts/publish.py
    ;;

  proxy)
    shift
    cd "$ROOT" && python scripts/proxy_manager.py "$@"
    ;;

  logs)
    echo "=== Logs ==="
    echo "  Updater:   tail -f $LOG_DIR/updater.log"
    echo "  Proxies:   ls $LOG_DIR/proxy-*.log"
    echo ""
    echo "--- Recent updater ---"
    tail -10 "$LOG_DIR/updater.log" 2>/dev/null || echo "(no log yet)"
    ;;

  *)
    echo "Usage: $0 {start|stop|status|restart|generate|proxy|logs}"
    echo ""
    echo "  start      Start all proxies + updater daemon"
    echo "  stop       Stop everything"
    echo "  status     Health check all services"
    echo "  restart    Stop + start"
    echo "  generate   Regenerate aggregates and publish to Supabase once"
    echo "  proxy      Proxy manager subcommand"
    echo "  logs       Show recent logs"
    exit 1
    ;;
esac
