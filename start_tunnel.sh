#!/bin/bash
# ==============================================================================
# ChakkiMate (चक्कीमेट) - Instant Global Access via Cloudflare Tunnel
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "🌾 Starting ChakkiMate Server & Global Cloudflare Tunnel..."
echo "=========================================================="

# Check if Django server is already running on port 8000
if ! lsof -i :8000 > /dev/null 2>&1; then
    echo "Starting local Django server..."
    source venv/bin/activate
    python manage.py runserver 0.0.0.0:8000 > /dev/null 2>&1 &
    sleep 2
fi

echo "Connecting to Cloudflare global network..."
cloudflared tunnel --url http://127.0.0.1:8000
