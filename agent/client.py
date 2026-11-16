"""serviceMonitor Agent.

Registers with the Monitor over TCP on startup, then emits a UDP heartbeat
on a fixed interval until it receives SIGTERM/SIGINT.
"""

import os
import signal
import socket
import sys
import time

AGENT_ID = os.environ["AGENT_ID"]
MONITOR_HOST = os.environ["MONITOR_HOST"]
TCP_PORT = int(os.environ.get("MONITOR_TCP_PORT", "8001"))
UDP_PORT = int(os.environ.get("MONITOR_UDP_PORT", "8002"))
HB_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL_SEC", "3"))
REGISTER_RETRIES = int(os.environ.get("REGISTER_RETRIES", "10"))
REGISTER_BACKOFF_SEC = float(os.environ.get("REGISTER_BACKOFF_SEC", "2"))

_running = True


def _stop(*_):
    """Signal handler: clear the running flag so the heartbeat loop exits cleanly."""
    global _running
    _running = False


def register():
    """Open a TCP connection to the monitor and send REGISTER {AGENT_ID}, retrying with backoff."""
    for attempt in range(1, REGISTER_RETRIES + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((MONITOR_HOST, TCP_PORT))
                s.sendall(f"REGISTER {AGENT_ID}\n".encode())
                ack = s.makefile("rb").readline().strip().decode()
                print(f"{AGENT_ID} registered (ack={ack})", flush=True)
                return
        except (ConnectionRefusedError, socket.gaierror, socket.timeout, OSError) as e:
            print(
                f"{AGENT_ID} registration attempt {attempt} failed: {e}",
                flush=True,
            )
            time.sleep(REGISTER_BACKOFF_SEC)
    print(f"{AGENT_ID} could not reach monitor; exiting", flush=True)
    sys.exit(1)


def heartbeat_loop():
    """Send a UDP HB datagram to the monitor every HB_INTERVAL seconds until _running is False."""
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while _running:
            udp.sendto(f"HB {AGENT_ID}".encode(), (MONITOR_HOST, UDP_PORT))
            print(f"{AGENT_ID} heartbeat", flush=True)
            slept = 0.0
            while _running and slept < HB_INTERVAL:
                time.sleep(0.1)
                slept += 0.1
    finally:
        udp.close()


def main():
    """Entry point: install signal handlers, register over TCP, then run the heartbeat loop."""
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    register()
    heartbeat_loop()


if __name__ == "__main__":
    main()
