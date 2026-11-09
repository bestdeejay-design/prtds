#!/usr/bin/env bash
# Local development entrypoint.
#
# Serves the API and the vanilla-ES-module frontend from ONE process on
# 0.0.0.0, so the browser only ever uses relative URLs (works behind the sandbox
# preview proxy, nginx or a Cloudflare Worker without changes).
#
# Usage:  ./scripts/dev.sh [port]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-${PORT:-8000}}"
VENV_PY="${VENV_PY:-$ROOT/.venv/bin/python}"

if [ ! -x "$VENV_PY" ]; then
  echo "No virtualenv found at $ROOT/.venv — creating it" >&2
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install --quiet -r "$ROOT/backend/requirements.txt"
fi

export PYTHONPATH="$ROOT/backend"
export PRTDS_DATABASE_URL="${PRTDS_DATABASE_URL:-sqlite:///$ROOT/backend/data/prtds_dev.db}"
mkdir -p "$ROOT/backend/data"

echo "PRTDS dev server → http://0.0.0.0:$PORT"
echo "  búsqueda   /"
echo "  ficha      /empresa/{slug}"
echo "  solicitud  /solicitud/{ref}"
echo "  socios     /socio        (token: prtds-demo-partner-token)"
echo "  admin      /admin        (token: prtds-demo-admin-token)"
echo "  estado     /salud"
echo "  API docs   /docs"

cd "$ROOT/backend"
exec "$VENV_PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload --reload-dir app
