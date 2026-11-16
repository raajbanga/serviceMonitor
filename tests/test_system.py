"""End-to-end system tests for serviceMonitor: boot, concurrency, detection
latency, log format, multi-fault resilience, and log persistence. Run with:

    docker compose down -v
    pytest tests/test_system.py -v -s
"""

import hashlib
import re
import time
from datetime import datetime

import pytest

from conftest import LOG_PATH, compose, read_log, reset_stack, wait_for_log

EXPECTED_SERVICES = {"agent1", "agent2", "agent3", "monitor"}


@pytest.fixture(scope="module")
def stack():
    """Bring up the full stack once per module, tear it down at the end."""
    reset_stack()
    compose("up", "-d", "--build")
    time.sleep(15)
    yield
    compose("down", "-v", check=False)


def test_single_command_boot(stack):
    """All four services running after a single `docker compose up -d`."""
    result = compose("ps", "--services", "--status", "running")
    running = {line for line in result.stdout.split() if line}
    assert running == EXPECTED_SERVICES, f"expected {EXPECTED_SERVICES}, got {running}"


def test_multi_agent_concurrency(stack):
    """Three agents heartbeat concurrently and interleave in the log."""
    time.sleep(30)
    text = read_log()
    for agent_id in ("agent1", "agent2", "agent3"):
        assert text.count(f"Heartbeat from {agent_id}") >= 5, (
            f"{agent_id} heartbeats missing"
        )
    ids = re.findall(r"Heartbeat from (\S+)", text)
    interleaved = any(
        set(ids[i:i + 9]) == {"agent1", "agent2", "agent3"}
        for i in range(max(0, len(ids) - 8))
    )
    assert interleaved, "no 9-line window contained all three agents"


def test_detection_latency(stack):
    """Stopping an agent yields a DOWN entry within ~10s of its last heartbeat."""
    compose("up", "-d", "agent2")
    time.sleep(8)
    last_hb_line = next(
        line for line in reversed(read_log().splitlines())
        if "Heartbeat from agent2" in line
    )
    last_hb_ts = last_hb_line.split()[0]
    compose("stop", "agent2")
    assert wait_for_log("Agent agent2 DOWN", timeout=20), "DOWN entry never appeared"
    down_line = next(
        line for line in reversed(read_log().splitlines())
        if "Agent agent2 DOWN" in line
    )
    down_ts = down_line.split()[0]
    latency = (
        datetime.fromisoformat(down_ts) - datetime.fromisoformat(last_hb_ts)
    ).total_seconds()
    assert latency <= 12.0, f"detection latency {latency:.1f}s exceeded 12s bound"


def test_audit_log_format(stack):
    """Every audit line is plain text: ISO timestamp + [LEVEL] + message."""
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 \[(INFO|DEBUG|WARN|ERROR|CRITICAL)\] "
    )
    lines = [l for l in read_log().splitlines() if l.strip()]
    assert lines, "audit log is empty"
    bad = [l for l in lines if not pattern.match(l)]
    assert not bad, f"{len(bad)} malformed lines, first: {bad[0]!r}"


def test_multi_fault_resilience(stack):
    """With two agents stopped, the third keeps heartbeating and DOWNs are recorded."""
    compose("stop", "agent1")
    time.sleep(12)
    text = read_log()
    assert "Agent agent1 DOWN" in text
    assert "Agent agent2 DOWN" in text  # already DOWN from the latency test
    before = text.count("Heartbeat from agent3")
    time.sleep(10)
    after = read_log().count("Heartbeat from agent3")
    assert after > before, "agent3 stopped heartbeating after the other two were DOWN"


def test_log_persistence_across_compose_cycle(stack):
    """The audit log survives `docker compose down` and is appended on re-up."""
    # Stop the monitor first: `down` stops agents before the monitor, and the
    # monitor would otherwise log their last heartbeats while tearing down.
    compose("stop", "monitor")
    bytes_before = LOG_PATH.stat().st_size
    sha_before = hashlib.sha256(LOG_PATH.read_bytes()).hexdigest()
    compose("down")
    assert LOG_PATH.exists(), "log lost after compose down"
    sha_after = hashlib.sha256(LOG_PATH.read_bytes()).hexdigest()
    assert sha_before == sha_after, "log mutated during compose down"
    compose("up", "-d")
    time.sleep(10)
    assert LOG_PATH.stat().st_size > bytes_before, "log not appended after re-up"
