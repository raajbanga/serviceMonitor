"""Unit tests for the Monitor in isolation.

Brings up only the monitor container and exercises its TCP and UDP
interfaces directly from the host. Run with:

    docker compose down -v
    pytest tests/test_unit.py -v
"""

import socket
import time

import pytest

from conftest import compose, reset_stack, wait_for_log

HOST = "127.0.0.1"
TCP_PORT = 8001
UDP_PORT = 8002


@pytest.fixture(scope="module")
def monitor_only():
    """Spin up only the monitor service and wait until its TCP listener actually responds."""
    reset_stack()
    compose("up", "-d", "--build", "monitor")
    # macOS docker-proxy accepts TCP before the container's listener is bound, so we
    # have to wait for the protocol-level "TCP listener ready" log line.
    assert wait_for_log("TCP listener ready", timeout=20), (
        "monitor TCP listener did not come up within 20s"
    )
    yield
    compose("down", "-v", check=False)


def _tcp_register(agent_id):
    """Open a TCP connection to the monitor, send a REGISTER line, and return the ACK bytes."""
    with socket.create_connection((HOST, TCP_PORT), timeout=5) as s:
        s.sendall(f"REGISTER {agent_id}\n".encode())
        return s.recv(64).strip()


def _udp_heartbeat(agent_id):
    """Send a single UDP HB datagram to the monitor for the given agent id."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(f"HB {agent_id}".encode(), (HOST, UDP_PORT))


def test_tcp_registration_acks_and_logs(monitor_only):
    """TCP REGISTER triggers an ACK and a registered-agent log entry."""
    ack = _tcp_register("unit-a")
    assert ack == b"ACK"
    assert wait_for_log("Agent unit-a registered", timeout=5)


def test_udp_heartbeat_logged(monitor_only):
    """A UDP HB datagram from a registered agent is logged."""
    _tcp_register("unit-b")
    assert wait_for_log("Agent unit-b registered", timeout=5)
    _udp_heartbeat("unit-b")
    assert wait_for_log("Heartbeat from unit-b", timeout=5)


def test_timeout_marks_agent_down(monitor_only):
    """An agent with no heartbeats is flagged DOWN within the timeout window."""
    _tcp_register("unit-c")
    assert wait_for_log("Agent unit-c registered", timeout=5)
    # Send no heartbeats; watcher should flag DOWN within ~10s.
    assert wait_for_log("Agent unit-c DOWN", timeout=20)
