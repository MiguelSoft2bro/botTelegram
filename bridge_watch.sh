#!/bin/zsh

BRIDGE_BASE="/Users/miguelcano/Desktop/TRABAJOS/phyton/bot"
BRIDGE_SCRIPT="$BRIDGE_BASE/bridge.py"
BRIDGE_PATTERN="bridge.py"
LOG_FILE="/tmp/bridge-watch.log"

start_bridge() {
    echo "[$(date)] Watchdog: arrancando bridge" >> "$LOG_FILE"
    (
        cd "$BRIDGE_BASE" &&
        nohup python3 "$BRIDGE_SCRIPT" >> /tmp/bridge.log 2>&1 &
    )
}

stop_bridge() {
    echo "[$(date)] Watchdog: cerrando bridge" >> "$LOG_FILE"
    pkill -f "$BRIDGE_PATTERN"
}

while true; do
    if pgrep -f "opencode --port" >/dev/null; then
        if ! pgrep -f "$BRIDGE_PATTERN" >/dev/null; then
            start_bridge
        fi
    else
        if pgrep -f "$BRIDGE_PATTERN" >/dev/null; then
            stop_bridge
        fi
    fi
    sleep 5
done
