#!/usr/bin/env bash
# One-command setup for the Job Resume Matcher (Muse-native edition).
# Usage: bash setup.sh
# Creates .venv, installs the package, and leaves you ready to run
# `jobmatch` or `bash scripts/demo.sh`. Requires Python 3.11+.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.11 or newer, then re-run." >&2
  exit 1
fi
PY_OK=$(python3 -c "import sys; print(sys.version_info >= (3, 11))")
if [ "$PY_OK" != "True" ]; then
  echo "error: Python 3.11+ is required (found $(python3 --version))." >&2
  exit 1
fi

python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e '.[dev]'
echo
echo "Setup done."
echo "  Activate:  source .venv/bin/activate"
echo "  Demo:      bash scripts/demo.sh"
echo "  Tests:     ./.venv/bin/python -m pytest -q"
