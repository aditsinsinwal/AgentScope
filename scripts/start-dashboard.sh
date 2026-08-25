#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

SANDBOX_KIND="${AGENTSCOPE_SANDBOX:-local}"
HOST="${AGENTSCOPE_HOST:-127.0.0.1}"
PORT="${AGENTSCOPE_PORT:-8000}"

if [[ "$SANDBOX_KIND" == "local" ]]; then
  echo "Starting AgentScope in local development mode. Evaluated task code runs on this host."
fi
echo "Dashboard: http://${HOST}:${PORT}/"

if [[ -x "$PROJECT_DIR/.venv/bin/agentscope" ]]; then
  exec "$PROJECT_DIR/.venv/bin/agentscope" serve --host "$HOST" --port "$PORT" --sandbox "$SANDBOX_KIND"
fi

if command -v agentscope >/dev/null 2>&1; then
  exec agentscope serve --host "$HOST" --port "$PORT" --sandbox "$SANDBOX_KIND"
fi

exec python3 -m agentscope.cli serve --host "$HOST" --port "$PORT" --sandbox "$SANDBOX_KIND"
