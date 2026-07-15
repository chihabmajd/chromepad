#!/usr/bin/env bash
# Create the venv on first run, install deps, then start the server.
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"
STAMP="$VENV/.deps-ok"

# venv creates $PY before pip runs, so a failed install would otherwise look
# complete on the next run. The stamp is written only once deps are in.
if [[ ! -x "$PY" || ! -f "$STAMP" ]]; then
  echo "[run] setting up venv (--system-site-packages for gi/Atspi)…"
  [[ -x "$PY" ]] || python3 -m venv --system-site-packages "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

exec "$PY" -m server.app "$@"
