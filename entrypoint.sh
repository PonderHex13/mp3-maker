#!/bin/sh
set -eu

case "${MODE:-both}" in
  api) exec uvicorn api:app --host 0.0.0.0 --port 8000 ;;
  worker) exec python worker.py ;;
  both) ;;
  *) echo "Invalid MODE: ${MODE}. Use api, worker, or both." >&2; exit 2 ;;
esac

python worker.py &
worker_pid=$!
uvicorn api:app --host 0.0.0.0 --port 8000 &
api_pid=$!

stop_children() {
  kill "$worker_pid" "$api_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
}
trap 'stop_children; exit 0' INT TERM

while kill -0 "$worker_pid" 2>/dev/null && kill -0 "$api_pid" 2>/dev/null; do
  sleep 1
done
echo "API or worker exited; stopping the other process." >&2
stop_children
exit 1
