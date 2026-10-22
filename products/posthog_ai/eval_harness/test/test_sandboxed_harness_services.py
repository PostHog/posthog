from __future__ import annotations

import os
import json
import asyncio
import zipfile
import itertools
import subprocess
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError

import requests_mock
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from products.posthog_ai.eval_harness import long_lived_subprocess
from products.posthog_ai.eval_harness.harness import services
from products.posthog_ai.eval_harness.harness.services import (
    ensure_ai_gateway_binary,
    maintain_ai_gateway_mint_key,
    package_local_skills_archive,
    provision_ai_gateway_mint_key,
    start_mcp_server,
)
from products.posthog_ai.eval_harness.long_lived_subprocess import (
    LongLivedSubprocessManager,
    SubprocessReadinessTimeout,
    SubprocessStartupError,
)


def test_package_local_skills_archive_is_deterministic_and_excludes_cache_markers(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample\n")
    (skills_dir / ".build-hash").write_text("cache")
    hidden_dir = skills_dir / ".cache"
    hidden_dir.mkdir()
    (hidden_dir / "state").write_text("cache")

    first = package_local_skills_archive(skills_dir, tmp_path / "first.zip")
    second = package_local_skills_archive(skills_dir, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["sample/SKILL.md"]


@pytest.mark.parametrize(
    "exec_skills_enabled,skill_archive_url,expected_flag_value",
    [
        (True, "http://localhost:18788/skills.zip?v=abc", True),
        (False, None, False),
    ],
)
def test_start_mcp_server_isolates_the_selected_skill_delivery(
    tmp_path: Path,
    exec_skills_enabled: bool,
    skill_archive_url: str | None,
    expected_flag_value: bool,
) -> None:
    mcp_dir = tmp_path / "services" / "mcp"
    (mcp_dir / "node_modules").mkdir(parents=True)
    stop = MagicMock()

    with (
        patch.dict(os.environ, {"POSTHOG_MCP_SKILLS_URL": "https://stale.example/skills.zip"}),
        patch("products.posthog_ai.eval_harness.harness.services.settings.BASE_DIR", tmp_path),
        patch(
            "products.posthog_ai.eval_harness.harness.services.LONG_LIVED_SUBPROCESSES.start",
            return_value=(MagicMock(), stop),
        ) as start,
    ):
        result = start_mcp_server(
            "http://localhost:18000",
            skill_archive_url,
            exec_skills_enabled=exec_skills_enabled,
        )

    env = start.call_args.kwargs["env"]
    overrides = json.loads(env["FEATURE_FLAG_OVERRIDES"])
    assert overrides["mcp-exec-skills"] is expected_flag_value
    assert start.call_args.kwargs.get("readiness_timeout", 30) == (120 if exec_skills_enabled else 30)
    # The skill delivery switch must not displace the overrides every eval run relies on.
    assert overrides["revamped-py-notebooks"] is True
    assert overrides["dashboard-widgets"] is True
    if skill_archive_url is None:
        assert "POSTHOG_MCP_SKILLS_URL" not in env
    else:
        assert env["POSTHOG_MCP_SKILLS_URL"] == skill_archive_url
    assert result is stop


@pytest.mark.parametrize("failures,retries,recovers", [(1, 2, True), (3, 2, False), (1, 0, False)])
def test_service_readiness_retries_stop_each_failed_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failures: int,
    retries: int,
    recovers: bool,
) -> None:
    manager = LongLivedSubprocessManager()
    manager.startup_retries = retries
    processes: list[MagicMock] = []
    stopped: list[MagicMock] = []

    def spawn(*_args: object, **_kwargs: object) -> MagicMock:
        assert stopped == processes
        process = MagicMock(pid=len(processes) + 1)
        process.poll.return_value = None
        processes.append(process)
        return process

    monkeypatch.setattr(long_lived_subprocess.subprocess, "Popen", spawn)
    clock = itertools.count()
    monkeypatch.setattr(long_lived_subprocess.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(long_lived_subprocess.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(manager, "_stop_stale_managed_process", lambda **_kwargs: None)
    monkeypatch.setattr(manager, "_fail_if_port_bound", lambda *_args: None)
    monkeypatch.setattr(manager, "_pipe_output", lambda *_args: None)
    monkeypatch.setattr(manager, "_write_pid_file", lambda **_kwargs: None)
    monkeypatch.setattr(manager, "_remove_pid_file", lambda _port: None)
    monkeypatch.setattr(manager, "_stop_process_group", stopped.append)
    socket = MagicMock()
    monkeypatch.setattr(
        long_lived_subprocess.socket,
        "create_connection",
        MagicMock(side_effect=[OSError("Not ready")] * failures + [socket]),
    )
    start = partial(
        manager.start,
        name="test service",
        port=12345,
        cmd=["fake-service"],
        cwd=tmp_path,
        env={},
        log_prefix="test",
        readiness_timeout=2,
    )
    if recovers:
        process, stop = start()
        assert process is processes[-1]
        assert len(processes) == failures + 1
        stop()
        socket.close.assert_called_once()
    else:
        with pytest.raises(SubprocessReadinessTimeout):
            start()
        assert len(processes) == retries + 1
    assert stopped == processes
    assert manager._stops == []


@pytest.mark.parametrize(
    "error", [SubprocessStartupError("Port in use"), FileNotFoundError("Missing executable"), KeyboardInterrupt()]
)
def test_service_startup_does_not_retry_permanent_errors_or_interrupts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: BaseException
) -> None:
    manager = LongLivedSubprocessManager()
    start = MagicMock(side_effect=error)
    monkeypatch.setattr(manager, "_start_once", start)
    with pytest.raises(type(error)):
        manager.start(name="test service", port=12345, cmd=["fake-service"], cwd=tmp_path, env={}, log_prefix="test")
    assert start.call_count == 1


@pytest.mark.parametrize("credit_status", [200, 503])
def test_gateway_provisioning_requires_test_credits(requests_mock: requests_mock.Mocker, credit_status: int) -> None:
    base_url = "http://localhost:18080"
    credits = requests_mock.post(f"{base_url}/internal/teams/42/credits", status_code=credit_status, json={})
    requests_mock.get(f"{base_url}/v1/models", json={"data": [{"id": "test-model"}]})
    requests_mock.post(f"{base_url}/v1/tokens", json={"token": "phe_test"})

    with patch("products.posthog_ai.eval_harness.harness.services.call_command"):
        if credit_status == 200:
            assert provision_ai_gateway_mint_key(42, agent_model="test-model").startswith("phs_")
        else:
            with pytest.raises(SubprocessStartupError, match="refused eval test credits: HTTP 503"):
                provision_ai_gateway_mint_key(42, agent_model="test-model")

    assert credits.last_request is not None
    assert credits.last_request.json() == {"amount_usd": "10000", "reason": "Local eval test credits"}
    assert credits.last_request.headers["Idempotency-Key"] != credits.last_request.headers["Authorization"]


@pytest.mark.parametrize("relative_path", ["gateway", "./gateway"])
def test_gateway_build_from_relative_clone_creates_the_binary_used_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: str
) -> None:
    repo = tmp_path / "gateway"
    (repo / "cmd" / "gateway").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_GATEWAY_REPO", relative_path)
    monkeypatch.setattr(services.shutil, "which", lambda _name: "/go")

    def build(cmd: list[str], *, cwd: Path, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output = cwd / cmd[cmd.index("-o") + 1]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("binary")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(services.subprocess, "run", build)
    ensure_ai_gateway_binary()

    assert (repo / ".run" / "eval-gateway").read_text() == "binary"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type", [None, InterfaceError, OperationalError, RedisConnectionError, RedisTimeoutError]
)
async def test_gateway_mint_credential_is_renewed_without_rotating_the_key(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception] | None
) -> None:
    loop = asyncio.get_running_loop()
    refreshed = asyncio.Event()
    parked = asyncio.Event()
    intervals: list[float] = []
    keys: list[str] = []
    attempts = 0

    async def tick(seconds: float) -> None:
        intervals.append(seconds)
        if len(intervals) > (2 if error_type else 1):
            await parked.wait()

    def command(name: str, *args: str, **_kwargs: object) -> None:
        nonlocal attempts
        if name == "setup_local_gateway_credential":
            attempts += 1
            if attempts == 1 and error_type:
                raise error_type("temporary connection failure")
            keys.append(args[args.index("--phs") + 1])
            loop.call_soon_threadsafe(refreshed.set)

    monkeypatch.setattr(services.asyncio, "sleep", tick)
    monkeypatch.setattr(services, "call_command", command)
    async with maintain_ai_gateway_mint_key(42, "phs_test"):
        await asyncio.wait_for(refreshed.wait(), timeout=5)

    assert keys == ["phs_test"]
    assert intervals[0] < services.GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL
    if error_type:
        assert intervals[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [OperationalError, RedisConnectionError, ValueError])
async def test_gateway_mint_credential_refresh_stops_at_expiry_or_permanent_failure(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    now = 0.0
    intervals: list[float] = []

    async def tick(seconds: float) -> None:
        nonlocal now
        intervals.append(seconds)
        now += seconds

    monkeypatch.setattr(services, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(services.asyncio, "sleep", tick)
    monkeypatch.setattr(services, "GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL", 10)
    monkeypatch.setattr(services, "AI_GATEWAY_CREDENTIAL_REFRESH_SECONDS", 3)
    monkeypatch.setattr(services, "refresh_ai_gateway_mint_key", MagicMock(side_effect=error_type("refresh failed")))

    with pytest.raises(ExceptionGroup) as failure:
        async with maintain_ai_gateway_mint_key(42, "phs_test"):
            await asyncio.wait_for(asyncio.Event().wait(), timeout=5)

    assert isinstance(failure.value.exceptions[0], error_type)
    assert intervals == ([3] if error_type is ValueError else [3, 1, 2, 4])
