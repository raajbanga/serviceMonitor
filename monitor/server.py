"""serviceMonitor Monitor.

Listens on TCP/8001 for agent registrations and UDP/8002 for heartbeats.
Runs a watcher thread per registered agent; flags an agent DOWN if no
heartbeat arrives within HEARTBEAT_TIMEOUT_SEC. All events are appended to
a persistent audit log that is bind-mounted to the host.
"""

import os
import socket
import threading
import time
from datetime import datetime, timezone

TCP_PORT = int(os.environ.get("MONITOR_TCP_PORT", "8001"))
UDP_PORT = int(os.environ.get("MONITOR_UDP_PORT", "8002"))
HEARTBEAT_TIMEOUT_SEC = float(os.environ.get("HEARTBEAT_TIMEOUT_SEC", "9"))
LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/var/log/service-monitor/audit_log.txt")

_agents = {}
_agents_lock = threading.Lock()
_log_lock = threading.Lock()


def log_event(level, message):
    """Append one timestamped, level-tagged line to the audit log and stdout."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{ts} [{level}] {message}\n"
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    print(line, end="", flush=True)


def _watch_agent(agent_id):
    """Watcher loop: flag the given agent DOWN if its heartbeat goes idle past HEARTBEAT_TIMEOUT_SEC."""
    while True:
        time.sleep(1)
        with _agents_lock:
            record = _agents.get(agent_id)
            if record is None or record["state"] == "DOWN":
                return
            idle = time.monotonic() - record["last_seen"]
            if idle > HEARTBEAT_TIMEOUT_SEC:
                record["state"] = "DOWN"
                idle_reported = idle
            else:
                idle_reported = None
        if idle_reported is not None:
            log_event(
                "CRITICAL",
                f"Agent {agent_id} DOWN (no heartbeat for {idle_reported:.1f}s)",
            )
            return


def _handle_tcp_registration(conn, addr):
    """Parse a REGISTER line from the TCP socket, register the agent, and ACK or NACK."""
    try:
        line = conn.makefile("rb").readline().decode(errors="replace").strip()
        parts = line.split()
        if len(parts) == 2 and parts[0] == "REGISTER":
            agent_id = parts[1]
            with _agents_lock:
                existing = _agents.get(agent_id)
                _agents[agent_id] = {
                    "state": "ACTIVE",
                    "last_seen": time.monotonic(),
                    "source": addr[0],
                }
                new_watcher_needed = existing is None or existing["state"] == "DOWN"
            log_event("INFO", f"Agent {agent_id} registered from {addr[0]}")
            conn.sendall(b"ACK\n")
            if new_watcher_needed:
                threading.Thread(
                    target=_watch_agent, args=(agent_id,), daemon=True
                ).start()
        else:
            log_event("WARN", f"Rejected TCP message from {addr[0]}: {line!r}")
            conn.sendall(b"NACK\n")
    except Exception as exc:
        log_event("ERROR", f"TCP handler error from {addr[0]}: {exc}")
    finally:
        conn.close()


def _start_tcp_listener():
    """Bind TCP/TCP_PORT and dispatch each accepted connection to a registration handler thread."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", TCP_PORT))
    s.listen(8)
    log_event("INFO", f"TCP listener ready on 0.0.0.0:{TCP_PORT}")
    while True:
        conn, addr = s.accept()
        threading.Thread(
            target=_handle_tcp_registration, args=(conn, addr), daemon=True
        ).start()


def _start_udp_listener():
    """Bind UDP/UDP_PORT, receive HB datagrams, and update agent state (recovering DOWN agents)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", UDP_PORT))
    log_event("INFO", f"UDP listener ready on 0.0.0.0:{UDP_PORT}")
    while True:
        data, addr = s.recvfrom(2048)
        parts = data.decode(errors="replace").strip().split()
        if len(parts) == 2 and parts[0] == "HB":
            agent_id = parts[1]
            recovered = False
            with _agents_lock:
                record = _agents.get(agent_id)
                if record is None:
                    _agents[agent_id] = {
                        "state": "ACTIVE",
                        "last_seen": time.monotonic(),
                        "source": addr[0],
                    }
                    recovered = True
                else:
                    if record["state"] == "DOWN":
                        recovered = True
                    record["state"] = "ACTIVE"
                    record["last_seen"] = time.monotonic()
                    record["source"] = addr[0]
            if recovered:
                log_event(
                    "INFO",
                    f"Agent {agent_id} heartbeat resumed from {addr[0]} "
                    "(restarting watcher)",
                )
                threading.Thread(
                    target=_watch_agent, args=(agent_id,), daemon=True
                ).start()
            log_event("DEBUG", f"Heartbeat from {agent_id}")
        else:
            log_event("WARN", f"Malformed UDP datagram from {addr[0]}: {data!r}")


def main():
    """Entry point: ensure the log directory exists and start the TCP and UDP listener threads."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log_event("INFO", "Monitor starting")
    threading.Thread(target=_start_tcp_listener, daemon=True).start()
    threading.Thread(target=_start_udp_listener, daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
