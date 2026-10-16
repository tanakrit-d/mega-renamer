#!/bin/sh
set -eu
mega-cmd-server &
mega_pid=$!
python /app/backend/server.py &
api_pid=$!
trap 'kill "$api_pid" "$mega_pid" 2>/dev/null || true' TERM INT EXIT
wait "$api_pid"
