#!/bin/bash
# ─────────────────────────────────────────────
# Projectos Taag — Local dev launcher
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

# Activate venv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Install dependencies if needed
pip install -q -r requirements.txt 2>/dev/null

echo ""
echo "Starting Projectos Taag server on port 8084..."
echo "  Local:  http://localhost:8084"
echo ""
echo "Press Ctrl+C to stop."
echo ""

python server.py
