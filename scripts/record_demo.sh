#!/usr/bin/env bash
# Records a short scripted run for the dashboard: three agents boot, agent1
# fails and comes back, then agent2 fails for good. Writes docs/sample-run.log and docs/sample-run.js.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose down -v >/dev/null 2>&1 || true
mkdir -p logs
rm -f logs/audit_log.txt

docker compose up -d --build
sleep 20
docker compose stop agent1   # fault: agent1 goes silent
sleep 15
docker compose start agent1  # recovery: heartbeats resume
sleep 12
docker compose stop agent2   # second fault, left down
sleep 15
docker compose stop monitor  # stop the monitor first so teardown raises no alerts
docker compose down

cp logs/audit_log.txt docs/sample-run.log
# the dashboard loads the run from a script tag so it also works when opened from disk
python3 -c 'import json,sys; print("const SAMPLE_LOG = " + json.dumps(open(sys.argv[1]).read()) + ";")' docs/sample-run.log > docs/sample-run.js
echo "Saved $(wc -l < docs/sample-run.log | tr -d ' ') log lines to docs/sample-run.log"
