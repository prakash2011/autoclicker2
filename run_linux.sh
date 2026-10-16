#!/bin/bash
cd "$(dirname "$0")"

echo "========================================================"
echo "  Antigravity Auto-Submit Tool (Ubuntu / Linux)"
echo "========================================================"
echo ""

# Ensure pip packages exist
python3 -m pip install -r requirements.txt --quiet --break-system-packages 2>/dev/null || true

echo "Starting universal monitor..."
python3 auto_submit_universal.py run
