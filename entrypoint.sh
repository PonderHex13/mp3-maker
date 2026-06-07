#!/bin/sh
set -e

# Simple entrypoint to run API and worker in a single container.
# MODE env var: 'api' => run only API, 'worker' => run only worker, default => run both.

pids=""

shutdown() {
  echo "Shutting down..."
  for pid in $pids; do
    if [ -n "$pid" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  exit 0
}

trap shutdown INT TERM

run_api() {
  uvicorn api:app --host 0.0.0.0 --port 8000 &
  pids="$pids $!"
  echo "Started API (pid=$!)"
}

run_worker() {
  python worker.py &
  pids="$pids $!"
  echo "Started worker (pid=$!)"
}

if [ "$MODE" = "api" ]; then
  run_api
  wait
elif [ "$MODE" = "worker" ]; then
  run_worker
  wait
else
  run_worker
  run_api

  # monitor children: if any exits, shut down the rest
  while true; do
    for pid in $pids; do
      # skip empty
      if [ -z "$pid" ]; then
        continue
      fi
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "Process $pid exited; shutting down others"
        shutdown
      fi
    done
    sleep 1
  done
fi
