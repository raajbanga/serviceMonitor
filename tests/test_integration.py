"""Integration tests for the full serviceMonitor stack.

Brings up monitor + all three agents via docker compose and validates the
happy path, fault-injection detection, and audit-log persistence across a
compose down cycle. Run with:

    docker compose down -v
    pytest tests/test_integration.py -v -s
"""

import time

import pytest

from conftest import LOG_PATH, compose, read_log, reset_stack, wait_for_log


@pytest.fixture(scope="module")
def stack():
    """Bring up the full stack once per module and tear it down at the end."""
    reset_stack()
    compose("up", "-d", "--build")
    time.sleep(15)
    yield
    compose("down", "-v", check=False)


def test_happy_path_all_agents_register_and_heartbeat(stack):
    """All three agents register and emit heartbeats end-to-end."""
    text = read_log()
    for agent_id in ("agent1", "agent2", "agent3"):
        assert f"Agent {agent_id} registered" in text, f"{agent_id} never registered"
        assert f"Heartbeat from {agent_id}" in text, f"{agent_id} never sent heartbeat"


def test_fault_injection_down_alert_and_continued_operation(stack):
    """Stopping agent1 triggers a DOWN alert while agent2 keeps heartbeating."""
    compose("stop", "agent1")
    assert wait_for_log("Agent agent1 DOWN", timeout=15), (
        "Monitor did not flag agent1 as DOWN within 15 seconds"
    )
    before = read_log().count("Heartbeat from agent2")
    time.sleep(5)
    after = read_log().count("Heartbeat from agent2")
    assert after > before, "agent2 stopped heartbeating after agent1 was flagged DOWN"


def test_log_persists_across_compose_down(stack):
    """After `docker compose down`, the host log is still present, non-empty, and retains the prior DOWN entry."""
    compose("down")
    assert LOG_PATH.exists(), (
        f"audit log {LOG_PATH} missing on host after docker compose down"
    )
    text = LOG_PATH.read_text(encoding="utf-8")
    assert text, "audit log present but empty after docker compose down"
    assert "Agent agent1 DOWN" in text, "prior DOWN event not retained on host"
