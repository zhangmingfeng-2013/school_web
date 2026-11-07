#!/bin/zsh
# bore - expose http://127.0.0.1:4444 to the public internet via bore.pub
# Usage: ~/bore-4444.sh [stop|status|url]
# Note: bore.pub assigns a random remote port on each restart.

LOG="$HOME/bore-4444.log"
PIDFILE="$HOME/.bore-4444.pid"

case "$1" in
  stop)
    [ -f "$PIDFILE" ] && kill "$(cat $PIDFILE)" 2>/dev/null && rm -f "$PIDFILE" && echo "bore stopped"
    pkill -f "bore local 4444" 2>/dev/null
    ;;
  status)
    if pgrep -f "bore local 4444" > /dev/null; then
      echo "running (pid $(pgrep -f 'bore local 4444' | head -1))"
      grep -o 'bore.pub:[0-9]*' "$LOG" | tail -1
    else
      echo "not running"
    fi
    ;;
  url)
    grep -o 'bore.pub:[0-9]*' "$LOG" | tail -1
    ;;
  *)
    pkill -f "bore local 4444" 2>/dev/null; sleep 1
    nohup bore local 4444 --to bore.pub > "$LOG" 2>&1 &
    disown
    echo $! > "$PIDFILE"
    sleep 4
    echo "public url: http://$(grep -o 'bore.pub:[0-9]*' "$LOG" | tail -1)"
    ;;
esac
