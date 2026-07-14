#!/usr/bin/env bash
# DARTS launcher for Raspberry Pi 5 / Linux
# Sets up a Python virtual environment if not already present,
# installs dependencies, then starts darts.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "[DARTS] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install/upgrade dependencies
source "$VENV_DIR/bin/activate"
echo "[DARTS] Checking dependencies (skipped if already satisfied)..."
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

echo "[DARTS] Starting DART-B core..."
exec python "$SCRIPT_DIR/darts.py" "$@"
