"""Shared test helpers for serviceMonitor.

All tests exercise the live Docker stack. No mocking.
"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "audit_log.txt"


def compose(*args, check=True):
    """Run `docker compose <args>` from the project root and return the CompletedProcess."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def reset_stack():
    """Tear the stack down with volumes and remove the host audit log so each test starts clean."""
    compose("down", "-v", check=False)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists():
        LOG_PATH.unlink()


def read_log():
    """Return the host-side audit log contents, or empty string if the file doesn't exist."""
    return LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""


def wait_for_log(substring, timeout):
    """Poll the audit log up to `timeout` seconds; return True once `substring` appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if substring in read_log():
            return True
        time.sleep(0.5)
    return False
