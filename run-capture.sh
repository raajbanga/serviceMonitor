#!/usr/bin/env bash
# Start the full stack with the tshark capture sidecar enabled, run through a
# fault-injection scenario, then tear down. Produces captures/heartbeats.pcapng
# for inspection in Wireshark.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p captures logs
rm -f captures/heartbeats.pcapng

docker compose --profile capture up -d --build
sleep 20
docker compose stop agent1
sleep 12
docker compose stop capture
docker compose --profile capture down

echo "Capture saved to ./captures/heartbeats.pcapng. Open it in Wireshark."
