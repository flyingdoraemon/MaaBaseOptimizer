#!/bin/zsh
set -e
cd "${0:A:h}"
PYTHON=".venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv .venv
fi
exec "$PYTHON" app.py

