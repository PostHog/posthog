import os
import time
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.agent_server_launcher import (
    AGENT_SERVER_LAUNCH_CAPABILITIES,
    AGENT_SERVER_PREFLIGHT_CAPABILITY_PREFIX,
    AGENT_SERVER_PREFLIGHT_REUSE_MARKER,
    build_agent_server_preflight_script,
)
from products.tasks.backend.logic.services.sandbox import (
    AGENT_SERVER_CAPABILITY_TOKENS,
    build_health_check_command,
    health_check_budget_seconds,
)


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
        ('{"status":"error","code":"codex_credential_unavailable"}', 1, "codex_credential_unavailable"),
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


def _run_preflight(tmp_path: Path, health_body: str, capability_tokens: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {
        "curl": f"printf '%s' '{health_body}'",
        "grep": 'case " $FAKE_CAPABILITIES " in *" $2 "*) exit 0;; esac\nexit 1',
        "kill": f'echo "$@" >> {tmp_path}/kill.log',
        "pgrep": f"if [ -e {tmp_path}/pgrep.seen ]; then exit 1; fi; touch {tmp_path}/pgrep.seen; echo 424242",
    }
    for name, body in fakes.items():
        fake = bin_dir / name
        fake.write_text(f"#!/bin/bash\n{body}\n")
        fake.chmod(0o755)
    guard = tmp_path / "gh"
    guard.write_text("#!/bin/bash\n")
    script = build_agent_server_preflight_script(probe_health=True, executable_paths=(str(guard),))
    return subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CAPABILITIES": capability_tokens,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_preflight_reuses_a_healthy_agent_server_without_freeing_the_port(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path, '{"status":"ok","hasSession":true}', "")

    assert completed.returncode == 0
    assert AGENT_SERVER_PREFLIGHT_REUSE_MARKER in completed.stdout.splitlines()
    assert not (tmp_path / "kill.log").exists()
    assert os.access(tmp_path / "gh", os.X_OK)


def test_preflight_frees_the_port_when_no_healthy_agent_server_answers(tmp_path: Path) -> None:
    completed = _run_preflight(tmp_path, '{"status":"ok","hasSession":false}', "")

    assert completed.returncode == 0
    assert AGENT_SERVER_PREFLIGHT_REUSE_MARKER not in completed.stdout.splitlines()
    assert (tmp_path / "kill.log").read_text().splitlines() == ["-TERM 424242"]


def test_preflight_does_not_kill_its_own_shell_when_freeing_the_port(tmp_path: Path) -> None:
    env = _path_with_fake_curl(tmp_path, "", 0.0)
    kill = tmp_path / "kill"
    kill.write_text(f'#!/bin/bash\necho "$@" >> {tmp_path}/kill.log\n')
    kill.chmod(0o755)
    script = build_agent_server_preflight_script(probe_health=True, executable_paths=())

    completed = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "kill.log").exists()


@pytest.mark.parametrize("capabilities", [(), ("auto_publish",), AGENT_SERVER_LAUNCH_CAPABILITIES])
def test_preflight_reports_only_the_capabilities_the_binary_carries(
    tmp_path: Path, capabilities: tuple[str, ...]
) -> None:
    tokens = " ".join(AGENT_SERVER_CAPABILITY_TOKENS[capability] for capability in capabilities)

    completed = _run_preflight(tmp_path, '{"status":"ok","hasSession":false}', tokens)

    reported = [
        line.removeprefix(AGENT_SERVER_PREFLIGHT_CAPABILITY_PREFIX)
        for line in completed.stdout.splitlines()
        if line.startswith(AGENT_SERVER_PREFLIGHT_CAPABILITY_PREFIX)
    ]
    assert sorted(reported) == sorted(capabilities)
