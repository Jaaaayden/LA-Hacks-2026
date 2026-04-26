#!/usr/bin/env bash
# Run the Hobbyist agents locally. Each gets its own log under tmp/.
#
# Usage:   bash scripts/run_agents.sh
# Stop:    bash scripts/run_agents.sh stop
#
# Pass "stop" as an argument to kill any running coordinator/scout.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR="$PROJECT_ROOT/tmp/agent-logs"

stop_agents() {
    echo "stopping agents…"
    pkill -f "backend.agents.run_all" 2>/dev/null || true
    pkill -f "backend.agents.coordinator.agent" 2>/dev/null || true
    pkill -f "backend.agents.scout.agent" 2>/dev/null || true
    sleep 1
    echo "done."
}

if [[ "${1:-}" == "stop" ]]; then
    stop_agents
    exit 0
fi

stop_agents
mkdir -p "$LOG_DIR"

# Run both agents under a single Bureau so Coordinator → Scout dispatch
# resolves locally (no Almanac/Agentverse round-trip needed). Each agent
# keeps its own mailbox for inbound ASI:One chats.
echo "starting Hobbyist Bureau (coordinator + scout)…"
nohup "$PY" -m backend.agents.run_all > "$LOG_DIR/bureau.log" 2>&1 &
BUREAU_PID=$!

sleep 3
echo
echo "bureau pid: $BUREAU_PID  → $LOG_DIR/bureau.log"
echo
echo "tail -f $LOG_DIR/bureau.log"
