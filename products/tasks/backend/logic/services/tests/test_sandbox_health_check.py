import os
import time
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.sandbox import build_health_check_command, health_check_budget_seconds


def _path_with_fake_curl(tmp_path: Path, body: str, delay_seconds: float) -> dict[str, str]:
    curl = tmp_path / "curl"
    curl.write_text(f"#!/bin/bash\nsleep {delay_seconds}\nprintf '%s' '{body}'\n")
    curl.chmod(0o755)
    return {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}


@pytest.mark.parametrize(
    ("body", "expected_exit_code", "expected_stdout"),
    [
        ('{"status":"ok","hasSession":true}', 0, "ok:1"),
        ('{"status":"ok","hasSession":false}', 1, ""),
    ],
)
def test_health_check_loop_stops_at_wall_clock_budget(tmp_path, body, expected_exit_code, expected_stdout) -> None:
    max_attempts, poll_interval, poll_delay = 100, 0.01, 0.2
    env = _path_with_fake_curl(tmp_path, body, poll_delay)
    budget = health_check_budget_seconds(max_attempts, poll_interval)

    started = time.monotonic()
    completed = subprocess.run(
        ["bash", "-c", build_health_check_command(port=1, max_attempts=max_attempts, poll_interval=poll_interval)],
        env=env,
        capture_output=True,
        text=True,
        timeout=max_attempts * poll_delay,
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == expected_exit_code
    assert completed.stdout.strip() == expected_stdout
    assert elapsed < budget + poll_delay + poll_interval + 2
