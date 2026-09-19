import os
import time
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.sandbox import (
    AGENT_SERVER_FATAL_LOG_MARKER,
    build_health_check_command,
    health_check_budget_seconds,
)

CURL_CALL_LOG = "curl-calls"


def _path_with_fake_curl(tmp_path: Path, body: str, delay_seconds: float) -> dict[str, str]:
    curl = tmp_path / "curl"
    curl.write_text(
        f"#!/bin/bash\necho poll >> {tmp_path / CURL_CALL_LOG}\nsleep {delay_seconds}\nprintf '%s' '{body}'\n"
    )
    curl.chmod(0o755)
    return {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}


def _poll_count(tmp_path: Path) -> int:
    call_log = tmp_path / CURL_CALL_LOG
    return len(call_log.read_text().splitlines()) if call_log.exists() else 0


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


@pytest.mark.parametrize(
    ("log_contents", "stops_on_first_poll"),
    [
        (
            f"[AgentServer] [error] {AGENT_SERVER_FATAL_LOG_MARKER}; marking run failed {{\n"
            '  "message": "Session initialization timed out after 30000ms"\n}\n',
            True,
        ),
        ('[AgentServer] [debug] HTTP server listening on port 8080 {\n  "bootMs": 1396\n}\n', False),
    ],
    ids=["agent_server_named_a_fatal_error", "agent_server_still_booting"],
)
def test_health_check_loop_stops_once_the_agent_server_names_a_fatal_error(
    tmp_path, log_contents: str, stops_on_first_poll: bool
) -> None:
    max_attempts, poll_interval, poll_delay = 100, 0.01, 0.02
    env = _path_with_fake_curl(tmp_path, '{"status":"ok","hasSession":false}', poll_delay)
    agent_server_log = tmp_path / "agent-server.log"
    agent_server_log.write_text(log_contents)

    completed = subprocess.run(
        [
            "bash",
            "-c",
            build_health_check_command(
                port=1,
                max_attempts=max_attempts,
                poll_interval=poll_interval,
                fatal_log_file=str(agent_server_log),
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=max_attempts * poll_delay + 10,
    )

    assert completed.returncode == 1
    if stops_on_first_poll:
        assert _poll_count(tmp_path) == 1
    else:
        assert _poll_count(tmp_path) > 1
