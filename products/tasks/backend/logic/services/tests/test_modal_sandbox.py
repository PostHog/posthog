import asyncio
import builtins
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from modal.exception import (
    ConnectionError as ModalConnectionError,
    ServiceError as ModalServiceError,
    TimeoutError as ModalTimeoutError,
)
from requests.exceptions import ConnectionError, Timeout

from products.tasks.backend.exceptions import (
    SandboxExecutionError,
    SandboxProvisionError,
    SnapshotCreationError,
    SnapshotTimeoutError,
)
from products.tasks.backend.logic.services.modal_provision_diagnostics import (
    MAX_PROVISION_LOG_EXCERPT_LINES,
    summarize_modal_output,
)
from products.tasks.backend.logic.services.modal_sandbox import (
    _GHCR_RESOLVE_MAX_ATTEMPTS,
    AGENT_SERVER_PORT,
    DEFAULT_MODAL_REGION,
    DIRECTORY_SNAPSHOT_TIMEOUT_SECONDS,
    SANDBOX_IMAGE,
    ModalSandbox,
    _get_modal_region,
    _get_sandbox_image_reference,
    _image_ref_cache,
    _resource_create_kwargs,
)
from products.tasks.backend.logic.services.sandbox import (
    AgentServerResult,
    ExecutionResult,
    SandboxConfig,
    SandboxTemplate,
)


def _agent_server_launch_command(mock_execute: Any) -> str:
    """Return the agent-server launch command among the execute calls.

    start_agent_server writes the BASH_ENV script (one execute call) before
    launching the server, so the launch is no longer the first execute call.
    """
    for call in mock_execute.call_args_list:
        command = call.args[0]
        if "./node_modules/.bin/agent-server" in command:
            return command
    raise AssertionError("agent-server launch command not found among execute calls")


def _mock_token_response(status_code: int = 200, token: str | None = "test-token"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"token": token} if token else {}
    return resp


def _mock_manifest_response(status_code: int = 200, digest: str | None = "sha256:abc123"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Docker-Content-Digest": digest} if digest else {}
    return resp


def _ghcr_side_effect(
    token_resp: Any = None,
    manifest_resp: Any = None,
    token_exc: Exception | None = None,
    manifest_exc: Exception | None = None,
):
    """Build a `requests.get` side effect that answers token vs manifest calls
    consistently no matter how many times it is called, so the test stays valid
    regardless of the (bounded) `_GHCR_RESOLVE_MAX_ATTEMPTS` retry cap.
    """

    def _side(url: str, *args: Any, **kwargs: Any) -> Any:
        if "/token" in url:
            if token_exc is not None:
                raise token_exc
            return token_resp
        if manifest_exc is not None:
            raise manifest_exc
        return manifest_resp

    return _side


class TestGetSandboxImageReference:
    def setup_method(self):
        _image_ref_cache.clear()

    @pytest.fixture(autouse=True)
    def _no_backoff_sleep(self):
        with patch("products.tasks.backend.logic.services.modal_sandbox.time.sleep"):
            yield

    def test_returns_digest_reference_on_success(self):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest="sha256:abc123")],
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}@sha256:abc123"

    @pytest.mark.parametrize("status_code", [401, 403, 404, 500, 502, 503])
    def test_fails_closed_on_token_request_failure(self, status_code: int):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            return_value=_mock_token_response(status_code=status_code),
        ) as mock_get:
            with pytest.raises(SandboxProvisionError, match="refusing to fall back to the mutable"):
                _get_sandbox_image_reference()

        assert mock_get.call_count == _GHCR_RESOLVE_MAX_ATTEMPTS

    def test_fails_closed_when_token_missing(self):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            return_value=_mock_token_response(token=None),
        ):
            with pytest.raises(SandboxProvisionError):
                _get_sandbox_image_reference()

    @pytest.mark.parametrize("status_code", [401, 403, 404, 500, 502, 503])
    def test_fails_closed_on_manifest_request_failure(self, status_code: int):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=_ghcr_side_effect(
                token_resp=_mock_token_response(),
                manifest_resp=_mock_manifest_response(status_code=status_code),
            ),
        ):
            with pytest.raises(SandboxProvisionError):
                _get_sandbox_image_reference()

    def test_fails_closed_when_digest_header_missing(self):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=_ghcr_side_effect(
                token_resp=_mock_token_response(),
                manifest_resp=_mock_manifest_response(digest=None),
            ),
        ):
            with pytest.raises(SandboxProvisionError):
                _get_sandbox_image_reference()

    @pytest.mark.parametrize(
        "exception",
        [
            ConnectionError("Connection refused"),
            Timeout("Request timed out"),
            Exception("Unknown error"),
        ],
    )
    def test_fails_closed_on_request_exception(self, exception: Exception):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=exception,
        ):
            with pytest.raises(SandboxProvisionError):
                _get_sandbox_image_reference()

    def test_retries_transient_failure_then_succeeds(self):
        attempts = {"token": 0}

        def _side(url: str, *args: Any, **kwargs: Any) -> Any:
            if "/token" in url:
                attempts["token"] += 1
                if attempts["token"] == 1:
                    return _mock_token_response(status_code=503)
                return _mock_token_response()
            return _mock_manifest_response(digest="sha256:recovered")

        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=_side,
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}@sha256:recovered"
        assert attempts["token"] == 2  # failed once, succeeded on retry

    def test_failure_is_not_cached(self):
        """A failed resolution must re-attempt on the next call (never cache the failure)."""
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            return_value=_mock_token_response(status_code=503),
        ):
            with pytest.raises(SandboxProvisionError):
                _get_sandbox_image_reference()

        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest="sha256:after")],
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}@sha256:after"

    def test_caches_result_across_calls(self):
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest="sha256:cached123")],
        ) as mock_get:
            result1 = _get_sandbox_image_reference()
            result2 = _get_sandbox_image_reference()
            result3 = _get_sandbox_image_reference()

        assert result1 == result2 == result3 == f"{SANDBOX_IMAGE}@sha256:cached123"
        assert mock_get.call_count == 2  # token + manifest, called only once due to cache

    def test_re_resolves_after_cache_expiry(self):
        """After TTL expiry (simulated via clear), a fresh GHCR query picks up the new digest."""
        with patch(
            "products.tasks.backend.logic.services.modal_sandbox.requests.get",
            side_effect=[
                _mock_token_response(),
                _mock_manifest_response(digest="sha256:old"),
                _mock_token_response(),
                _mock_manifest_response(digest="sha256:new"),
            ],
        ) as mock_get:
            result1 = _get_sandbox_image_reference()
            assert result1 == f"{SANDBOX_IMAGE}@sha256:old"
            assert mock_get.call_count == 2

            _image_ref_cache.clear()

            result2 = _get_sandbox_image_reference()
            assert result2 == f"{SANDBOX_IMAGE}@sha256:new"
            assert mock_get.call_count == 4


class TestGetSandboxImageReferenceIntegration:
    def setup_method(self):
        _image_ref_cache.clear()

    @pytest.mark.xfail(
        reason="Flaky: depends on GHCR availability. Remove this mark when we've figured out a less flaky approach"
    )
    def test_resolves_digest_from_ghcr(self):
        result = _get_sandbox_image_reference()

        assert result.startswith(f"{SANDBOX_IMAGE}@sha256:")
        digest_part = result.split("@")[1]
        assert digest_part.startswith("sha256:")
        assert len(digest_part) == 71  # "sha256:" + 64 hex chars


class TestGetModalRegion:
    @pytest.mark.parametrize(
        "cloud_deployment,expected_region",
        [
            ("EU", "eu-west"),
            ("US", "us-east"),
            ("DEV", DEFAULT_MODAL_REGION),
            (None, DEFAULT_MODAL_REGION),
            ("LOCAL", DEFAULT_MODAL_REGION),
        ],
    )
    def test_returns_correct_region(self, cloud_deployment, expected_region):
        with patch("products.tasks.backend.logic.services.modal_sandbox.CLOUD_DEPLOYMENT", cloud_deployment):
            assert _get_modal_region() == expected_region


class TestModalSandboxAgentServer:
    @pytest.fixture
    def mock_sandbox(self) -> Any:
        mock_modal_sandbox = MagicMock()
        mock_modal_sandbox.object_id = "test-sandbox-id"
        mock_modal_sandbox.poll.return_value = None

        mock_credentials = MagicMock()
        mock_credentials.url = "https://test-sandbox.modal.run"
        mock_credentials.token = "test-connect-token-abc123"
        mock_modal_sandbox.create_connect_token.return_value = mock_credentials

        config = SandboxConfig(name="test-sandbox")
        with patch.object(ModalSandbox, "_get_app_for_template", return_value=MagicMock()):
            return ModalSandbox(sandbox=mock_modal_sandbox, config=config)

    @pytest.fixture(autouse=True)
    def _bypass_start_guard(self):
        with (
            patch.object(ModalSandbox, "_agent_server_is_healthy", return_value=False),
            patch.object(ModalSandbox, "_free_agent_server_port"),
        ):
            yield

    def test_get_connect_credentials_success(self, mock_sandbox: Any):
        result = mock_sandbox.get_connect_credentials()

        assert isinstance(result, AgentServerResult)
        assert result.url == "https://test-sandbox.modal.run"
        assert result.token == "test-connect-token-abc123"
        assert mock_sandbox.sandbox_url == "https://test-sandbox.modal.run"

        mock_sandbox._sandbox.create_connect_token.assert_called_once_with()

    def test_get_connect_credentials_raises_when_not_running(self, mock_sandbox: Any):
        mock_sandbox._sandbox.poll.return_value = 0

        with pytest.raises(RuntimeError, match="Sandbox not in running state"):
            mock_sandbox.get_connect_credentials()

    @pytest.mark.parametrize("method_name", ["execute", "execute_stream"])
    def test_execution_redacts_event_ingest_token_from_error_context(self, mock_sandbox: Any, method_name: str):
        mock_sandbox._sandbox.exec.side_effect = RuntimeError("failed POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN=secret-token")

        with (
            patch("products.tasks.backend.logic.services.modal_sandbox.capture_exception") as capture_exception,
            pytest.raises(SandboxExecutionError) as exc,
        ):
            getattr(mock_sandbox, method_name)("env POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN=secret-token agent-server")

        assert exc.value.context["command"] == "env POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN=<redacted> agent-server"
        assert exc.value.context["error"] == "failed POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN=<redacted>"
        assert "secret-token" not in exc.value.context["command"]
        assert "secret-token" not in exc.value.context["error"]
        capture_exception.assert_not_called()

    def test_start_agent_server_success_without_domains_skips_agentsh(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        with patch.object(mock_sandbox, "_setup_agentsh") as mock_setup:
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
                mode="background",
            )

        mock_setup.assert_not_called()
        command = _agent_server_launch_command(mock_sandbox.execute)
        import shlex

        assert f"--port {AGENT_SERVER_PORT}" in command
        assert f"--repositoryPath {shlex.quote('/tmp/workspace/repos/posthog/posthog')}" in command
        assert f"--taskId {shlex.quote('task-123')}" in command
        assert f"--runId {shlex.quote('run-456')}" in command
        assert f"--mode {shlex.quote('background')}" in command
        assert "--createPr true" in command
        assert "agentsh exec" not in command
        assert "nohup" in command

    def test_start_agent_server_wraps_with_agentsh_when_domains_provided(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        with patch.object(mock_sandbox, "_setup_agentsh") as mock_setup_agentsh:
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
                mode="background",
                allowed_domains=["example.com"],
            )

        mock_setup_agentsh.assert_called_once_with(
            "/tmp/workspace",
            ["example.com"],
        )
        command = _agent_server_launch_command(mock_sandbox.execute)
        assert "--createPr true" in command
        assert "agentsh exec --client-timeout 2h --timeout 2h" in command
        assert "env -0 > /tmp/agent-env" in command
        assert "/tmp/agentsh-env-wrapper.sh" in command
        assert "./node_modules/.bin/agent-server" in command

    def test_start_agent_server_wraps_with_agentsh_when_domains_empty(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        with patch.object(mock_sandbox, "_setup_agentsh") as mock_setup_agentsh:
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
                mode="background",
                allowed_domains=[],
            )

        mock_setup_agentsh.assert_called_once_with("/tmp/workspace", [])
        command = _agent_server_launch_command(mock_sandbox.execute)
        assert "--allowedDomains" not in command
        assert "agentsh exec --client-timeout 2h --timeout 2h" in command
        assert "env -0 > /tmp/agent-env" in command

    @pytest.mark.parametrize(
        ("create_pr", "expected_flag"),
        [
            (True, "--createPr true"),
            (False, "--createPr false"),
        ],
    )
    def test_start_agent_server_passes_create_pr_flag(self, mock_sandbox: Any, create_pr: bool, expected_flag: str):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        with patch.object(mock_sandbox, "_setup_agentsh"):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
                mode="background",
                create_pr=create_pr,
            )

        command = _agent_server_launch_command(mock_sandbox.execute)
        assert expected_flag in command

    def test_start_agent_server_includes_runtime_environment_variables(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        mock_sandbox.start_agent_server(
            repository="posthog/posthog",
            task_id="task-123",
            run_id="run-456",
            mode="background",
            runtime_adapter="codex",
            provider="openai",
            model="gpt-5.3-codex",
            reasoning_effort="high",
            initial_permission_mode="plan",
            event_ingest_token="ingest-token",
            event_ingest_url="https://agent-proxy.example.com",
        )

        command = _agent_server_launch_command(mock_sandbox.execute)
        assert "POSTHOG_CODE_RUNTIME_ADAPTER=codex" in command
        assert "POSTHOG_CODE_PROVIDER=openai" in command
        assert "POSTHOG_CODE_MODEL=gpt-5.3-codex" in command
        assert "POSTHOG_CODE_REASONING_EFFORT=high" in command
        assert "POSTHOG_CODE_INITIAL_PERMISSION_MODE=plan" in command
        assert "POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN=ingest-token" in command
        # Modal sandboxes reach the proxy by its real URL, no Docker-host rewrite.
        assert "POSTHOG_TASK_RUN_EVENT_INGEST_URL=https://agent-proxy.example.com" in command

    @pytest.mark.parametrize(
        "keep_stream_open, expected_env_present",
        [
            (True, True),
            (False, False),
        ],
    )
    def test_start_agent_server_keep_stream_open_env(self, mock_sandbox: Any, keep_stream_open, expected_env_present):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
        )

        mock_sandbox.start_agent_server(
            repository="posthog/posthog",
            task_id="task-123",
            run_id="run-456",
            mode="background",
            event_ingest_keep_stream_open=keep_stream_open,
        )

        command = _agent_server_launch_command(mock_sandbox.execute)
        if expected_env_present:
            assert "POSTHOG_TASK_RUN_EVENT_INGEST_KEEP_STREAM_OPEN=true" in command
        else:
            assert "POSTHOG_TASK_RUN_EVENT_INGEST_KEEP_STREAM_OPEN" not in command

    def test_start_agent_server_raises_when_not_running(self, mock_sandbox: Any):
        mock_sandbox._sandbox.poll.return_value = 0

        with pytest.raises(RuntimeError, match="Sandbox not in running state"):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
            )

    def test_start_agent_server_raises_on_start_failure(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="", stderr="npx: command not found", exit_code=127, error=None)
        )

        with patch.object(mock_sandbox, "_setup_agentsh"):
            with pytest.raises(SandboxExecutionError, match="Agent-server failed to start"):
                mock_sandbox.start_agent_server(
                    repository="posthog/posthog",
                    task_id="task-123",
                    run_id="run-456",
                )

    def test_start_agent_server_raises_on_health_check_failure(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="", stderr="", exit_code=1, error=None),
                ExecutionResult(stdout="some log output", stderr="", exit_code=0, error=None),
            ]
        )

        with patch.object(mock_sandbox, "_setup_agentsh"):
            with pytest.raises(SandboxExecutionError, match="Agent-server failed to start"):
                mock_sandbox.start_agent_server(
                    repository="posthog/posthog",
                    task_id="task-123",
                    run_id="run-456",
                )

    def test_wait_for_health_check_passes(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:3", stderr="", exit_code=0, error=None),
        )

        result = mock_sandbox._wait_for_health_check()

        assert result is True
        assert mock_sandbox.execute.call_count == 1

    def test_wait_for_health_check_fails(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="", stderr="", exit_code=1, error=None),
        )

        result = mock_sandbox._wait_for_health_check()

        assert result is False
        assert mock_sandbox.execute.call_count == 1

    def test_start_agent_server_skips_relaunch_when_already_healthy(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock()

        with (
            patch.object(mock_sandbox, "_agent_server_is_healthy", return_value=True),
            patch.object(mock_sandbox, "_free_agent_server_port") as mock_free,
        ):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
                mode="background",
            )

        mock_free.assert_not_called()
        mock_sandbox.execute.assert_not_called()

    def test_start_agent_server_frees_port_before_relaunch(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="ok:1", stderr="", exit_code=0, error=None),
            ]
        )

        mock_sandbox.start_agent_server(
            repository="posthog/posthog",
            task_id="task-123",
            run_id="run-456",
            mode="background",
        )

        mock_sandbox._free_agent_server_port.assert_called_once_with()
        assert "nohup" in _agent_server_launch_command(mock_sandbox.execute)

    def test_create_snapshot_waits_for_container_before_snapshot(self, mock_sandbox: Any) -> None:
        events: list[str] = []
        exec_process = MagicMock()
        exec_process.wait.side_effect = lambda: events.append("wait")
        image = MagicMock()
        image.object_id = "snapshot-123"

        def snapshot_filesystem(ttl: Any = None) -> Any:
            events.append("snapshot")
            return image

        mock_sandbox._sandbox.exec.return_value = exec_process
        mock_sandbox._sandbox.snapshot_filesystem.side_effect = snapshot_filesystem

        result = mock_sandbox.create_snapshot()

        assert result == "snapshot-123"
        mock_sandbox._sandbox.exec.assert_called_once_with("true", timeout=30)
        exec_process.wait.assert_called_once_with()
        mock_sandbox._sandbox.snapshot_filesystem.assert_called_once_with(ttl=None)
        assert events == ["wait", "snapshot"]


class TestModalSandboxProvisionDiagnostics:
    @pytest.mark.parametrize(
        "output,expected_summary_lines,expected_excerpt,raw_excerpt_should_be_none",
        [
            (" \n\t ", [], None, True),
            (
                "\n".join(
                    [
                        "\x1b[32mApr 09 15:40:06 Building image im-123\x1b[0m",
                        "\x1b[34m=> Step 0: FROM ubuntu:24.04\x1b[0m",
                        "Copying config sha256:abc",
                        "Copied image in 1.60s",
                    ]
                ),
                [
                    "Apr 09 15:40:06 Building image im-123",
                    "=> Step 0: FROM ubuntu:24.04",
                    "Copied image in 1.60s",
                ],
                "Copying config sha256:abc",
                False,
            ),
            (
                "\n".join(
                    [
                        "=> Step 3: RUN apt-get update && apt-get install -y curl",
                        "=> Step 3: RUN apt-get update && apt-get install -y curl",
                    ]
                ),
                ["=> Step 3: RUN apt-get update && apt-get install -y curl"],
                "=> Step 3: RUN apt-get update && apt-get install -y curl",
                False,
            ),
        ],
    )
    def test_summarizes_modal_build_output(
        self,
        output: str,
        expected_summary_lines: list[str],
        expected_excerpt: str | None,
        raw_excerpt_should_be_none: bool,
    ):
        diagnostics = summarize_modal_output(output)

        assert diagnostics.summary_lines == expected_summary_lines
        if raw_excerpt_should_be_none:
            assert diagnostics.raw_excerpt is None
        else:
            assert diagnostics.raw_excerpt is not None
            assert expected_excerpt is not None
            assert expected_excerpt in diagnostics.raw_excerpt

    def test_truncates_long_modal_build_output_excerpt(self):
        output = "\n".join(f"line {index}" for index in range(MAX_PROVISION_LOG_EXCERPT_LINES + 5))

        diagnostics = summarize_modal_output(output)

        assert diagnostics.summary_lines == []
        assert diagnostics.raw_excerpt is not None
        assert diagnostics.raw_excerpt.endswith("\n... (truncated)")
        assert f"line {MAX_PROVISION_LOG_EXCERPT_LINES}" not in diagnostics.raw_excerpt


class TestModalSandboxCommandEscaping:
    @pytest.mark.parametrize(
        "repository",
        [
            "PostHog/posthog",
            "org/repo-name",
            "org/repo; echo hacked",
            "org/repo$(whoami)",
            "org'/repo",
            "org/repo`id`",
        ],
    )
    def test_clone_repository_command_escaping(self, repository):
        import shlex

        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test")
        sandbox._sandbox = MagicMock()

        with patch.object(sandbox, "is_running", return_value=True):
            with patch.object(sandbox, "execute") as mock_execute:
                sandbox.clone_repository(repository, github_token="test-token")
                command = mock_execute.call_args[0][0]

                org, repo = repository.lower().split("/")
                target_path = f"/tmp/workspace/repos/{org}/{repo}"
                org_path = f"/tmp/workspace/repos/{org}"

                assert shlex.quote(target_path) in command
                assert shlex.quote(org_path) in command
                assert shlex.quote(repo) in command

    @pytest.mark.parametrize(
        "shallow,expected_in_command,not_expected_in_command",
        [
            (True, "--depth 1", None),
            (False, "--single-branch", "--depth"),
        ],
    )
    def test_clone_repository_shallow_flag(self, shallow, expected_in_command, not_expected_in_command):
        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test")
        sandbox._sandbox = MagicMock()

        with patch.object(sandbox, "is_running", return_value=True):
            with patch.object(sandbox, "execute") as mock_execute:
                sandbox.clone_repository("PostHog/posthog", github_token="test-token", shallow=shallow)
                command = mock_execute.call_args[0][0]

                assert expected_in_command in command
                if not_expected_in_command:
                    assert not_expected_in_command not in command

    @pytest.mark.parametrize(
        "repository,task_id,run_id,mode",
        [
            ("PostHog/posthog", "task-123", "run-456", "background"),
            ("org/repo; echo hacked", "task-123", "run-456", "background"),
            ("PostHog/posthog", "task; echo hacked", "run-456", "background"),
            ("PostHog/posthog", "task-123", "run$(whoami)", "background"),
            ("PostHog/posthog", "task-123", "run-456", "mode`id`"),
        ],
    )
    def test_start_agent_server_command_escaping(self, repository, task_id, run_id, mode):
        import shlex

        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test")
        sandbox._sandbox = MagicMock()
        sandbox._sandbox_url = None

        with (
            patch.object(sandbox, "is_running", return_value=True),
            patch.object(sandbox, "_setup_agentsh"),
            patch.object(sandbox, "_agent_server_is_healthy", return_value=False),
            patch.object(sandbox, "_free_agent_server_port"),
            patch.object(sandbox, "execute") as mock_execute,
            patch.object(sandbox, "_wait_for_health_check", return_value=True),
        ):
            mock_execute.return_value = MagicMock(exit_code=0)
            sandbox.start_agent_server(repository, task_id, run_id, mode)

            command = _agent_server_launch_command(mock_execute)

            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

            assert shlex.quote(repo_path) in command
            assert shlex.quote(task_id) in command
            assert shlex.quote(run_id) in command
            assert shlex.quote(mode) in command


class TestModalSandboxAgentServerStartupHelpers:
    def _make_sandbox(self) -> Any:
        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test")
        sandbox._sandbox = MagicMock()
        return sandbox

    @pytest.mark.parametrize(
        "exit_code,expected",
        [
            (0, True),
            (1, False),
        ],
    )
    def test_agent_server_is_healthy(self, exit_code: int, expected: bool):
        sandbox = self._make_sandbox()
        sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="ok:1", stderr="", exit_code=exit_code, error=None)
        )

        assert sandbox._agent_server_is_healthy() is expected
        assert sandbox.execute.call_count == 1

    def test_free_agent_server_port_terminates_existing_process(self):
        sandbox = self._make_sandbox()
        sandbox.execute = MagicMock(return_value=ExecutionResult(stdout="", stderr="", exit_code=0, error=None))

        sandbox._free_agent_server_port()

        command = sandbox.execute.call_args_list[0][0][0]
        assert "pkill -TERM -f agent-server" in command
        assert "pkill -KILL -f agent-server" in command


class TestStartupFailureDiagnostics:
    def _sandbox(self) -> Any:
        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-diag"
        sandbox.config = SandboxConfig(name="t")
        sandbox._sandbox = MagicMock()
        return sandbox

    def test_reports_termination_when_sandbox_gone(self):
        sandbox = self._sandbox()
        sandbox._sandbox.poll.return_value = 137

        with patch.object(sandbox, "is_running", return_value=False):
            diagnostics = sandbox._diagnose_startup_failure(allowed_domains=None)

        assert diagnostics["sandbox_terminated"] == "true"
        assert "poll=137" in diagnostics["failure_reason"]
        sandbox._sandbox.exec.assert_not_called()

    def test_reports_blocked_egress_host(self):
        sandbox = self._sandbox()

        def _exec(command: str, timeout_seconds: Any = None) -> ExecutionResult:
            if "printf" in command:
                return ExecutionResult(
                    stdout="api.anthropic.com code=200\nmcp.posthog.com http_code=000",
                    stderr="",
                    exit_code=0,
                    error=None,
                )
            if "agent-server.log" in command:
                return ExecutionResult(stdout="agent log tail", stderr="", exit_code=0, error=None)
            return ExecutionResult(stdout='{"status":"ok","hasSession":false}', stderr="", exit_code=0, error=None)

        with (
            patch.object(sandbox, "is_running", return_value=True),
            patch.object(sandbox, "execute", side_effect=_exec),
        ):
            diagnostics = sandbox._diagnose_startup_failure(allowed_domains=["github.com"])

        assert diagnostics["sandbox_terminated"] == "false"
        assert "egress blocked" in diagnostics["failure_reason"]
        assert "mcp.posthog.com" in diagnostics["failure_reason"]

    def test_reports_alive_without_session_when_no_block(self):
        sandbox = self._sandbox()

        def _exec(command: str, timeout_seconds: Any = None) -> ExecutionResult:
            if "printf" in command:
                return ExecutionResult(
                    stdout="gateway.us.posthog.com http_code=200", stderr="", exit_code=0, error=None
                )
            return ExecutionResult(stdout="ok", stderr="", exit_code=0, error=None)

        with (
            patch.object(sandbox, "is_running", return_value=True),
            patch.object(sandbox, "execute", side_effect=_exec),
        ):
            diagnostics = sandbox._diagnose_startup_failure(allowed_domains=None)

        assert diagnostics["sandbox_terminated"] == "false"
        assert "never reported hasSession=true" in diagnostics["failure_reason"]


class TestModalSandboxCreateAllowlist:
    def _create_with_config(self, config: SandboxConfig) -> Any:
        mock_sb = MagicMock()
        mock_sb.object_id = "sb-created"
        with (
            patch("products.tasks.backend.logic.services.modal_sandbox.modal.enable_output"),
            patch.object(ModalSandbox, "_get_app_for_template", return_value=MagicMock()),
            patch("products.tasks.backend.logic.services.modal_sandbox._get_template_image", return_value=MagicMock()),
            patch(
                "products.tasks.backend.logic.services.modal_sandbox.modal.Sandbox.create", return_value=mock_sb
            ) as mock_create,
        ):
            ModalSandbox.create(config)
        return mock_create

    def test_create_forwards_exact_outbound_domain_allowlist(self):
        domains = ["github.com", "api.github.com", "example.com", "*.posthog.com", "api.anthropic.com"]
        config = SandboxConfig(name="t", outbound_domain_allowlist=domains)

        mock_create = self._create_with_config(config)

        assert mock_create.call_args.kwargs["outbound_domain_allowlist"] == domains

    def test_create_omits_allowlist_when_unset(self):
        config = SandboxConfig(name="t")

        mock_create = self._create_with_config(config)

        assert "outbound_domain_allowlist" not in mock_create.call_args.kwargs

    def test_create_sets_vm_runtime_experimental_option(self):
        config = SandboxConfig(name="t", vm_runtime=True)

        mock_create = self._create_with_config(config)

        assert mock_create.call_args.kwargs["experimental_options"] == {"vm_runtime": True}


class TestResourceCreateKwargs:
    def test_flat_scalars_when_not_burstable(self):
        config = SandboxConfig(name="t", cpu_cores=4, memory_gb=16)

        kwargs = _resource_create_kwargs(config)

        # Not burstable -> fixed-size box: request == limit, emitted as flat scalars.
        assert kwargs == {"cpu": 4.0, "memory": 16384}

    def test_tuple_request_and_limit_when_burstable(self):
        config = SandboxConfig(name="t", cpu_cores=4, memory_gb=16, burstable_resources=True)

        kwargs = _resource_create_kwargs(config)

        # Request the 0.5 CPU / 1024 MiB floor, burst up to the configured size (the limit).
        assert kwargs == {"cpu": (0.5, 4.0), "memory": (1024, 16384)}

    def test_floor_is_clamped_to_limit_when_config_is_below_floor(self):
        # A 1 GB / 1-core box whose configured size is at/under the floor still emits a valid
        # (request, limit) pair — the request is clamped so it never exceeds the limit.
        config = SandboxConfig(name="t", cpu_cores=1, memory_gb=1, burstable_resources=True)

        kwargs = _resource_create_kwargs(config)

        assert kwargs == {"cpu": (0.5, 1.0), "memory": (1024, 1024)}

    def test_explicit_request_floor_is_honored_when_burstable(self):
        config = SandboxConfig(
            name="t",
            cpu_cores=8,
            memory_gb=16,
            burstable_resources=True,
            cpu_request_cores=2,
            memory_request_mb=4096,
        )

        kwargs = _resource_create_kwargs(config)

        # Reserve the explicitly requested floor, burst up to the configured limit.
        assert kwargs == {"cpu": (2.0, 8.0), "memory": (4096, 16384)}

    def test_vm_runtime_pins_memory_but_keeps_cpu_elastic(self):
        config = SandboxConfig(name="t", cpu_cores=4, memory_gb=16, burstable_resources=True, vm_runtime=True)

        kwargs = _resource_create_kwargs(config)

        assert kwargs == {"cpu": (0.5, 4.0), "memory": 16384}

    def test_vm_template_pins_memory_but_keeps_cpu_elastic(self):
        config = SandboxConfig(
            name="t",
            cpu_cores=4,
            memory_gb=16,
            burstable_resources=True,
            template=SandboxTemplate.VM_BASE,
        )

        kwargs = _resource_create_kwargs(config)

        assert kwargs == {"cpu": (0.5, 4.0), "memory": 16384}

    def test_explicit_request_floor_is_clamped_to_limit(self):
        # A request floor above the configured limit is clamped down to the limit.
        config = SandboxConfig(
            name="t",
            cpu_cores=1,
            memory_gb=2,
            burstable_resources=True,
            cpu_request_cores=4,
            memory_request_mb=8192,
        )

        kwargs = _resource_create_kwargs(config)

        assert kwargs == {"cpu": (1.0, 1.0), "memory": (2048, 2048)}


class TestModalSandboxCreateSnapshot:
    @pytest.fixture
    def mock_sandbox(self) -> Any:
        mock_modal_sandbox = MagicMock()
        mock_modal_sandbox.object_id = "test-sandbox-id"
        mock_modal_sandbox.poll.return_value = None  # None => still running

        config = SandboxConfig(name="test-sandbox")
        with patch.object(ModalSandbox, "_get_app_for_template", return_value=MagicMock()):
            return ModalSandbox(sandbox=mock_modal_sandbox, config=config)

    def test_create_snapshot_success(self, mock_sandbox: Any):
        mock_sandbox._sandbox.snapshot_filesystem.return_value = MagicMock(object_id="im-123")

        with patch("products.tasks.backend.exceptions.capture_exception") as capture_exception:
            assert mock_sandbox.create_snapshot() == "im-123"

        capture_exception.assert_not_called()

    @pytest.mark.parametrize(
        "error",
        [
            ModalTimeoutError("Deadline exceeded"),
            ModalConnectionError("connection reset"),
            ModalServiceError("Timeout expired"),
            builtins.TimeoutError("timed out"),
            builtins.ConnectionError("connection error"),
            asyncio.CancelledError(),
        ],
    )
    def test_transient_modal_errors_are_retryable_and_not_captured(self, mock_sandbox: Any, error: BaseException):
        mock_sandbox._sandbox.snapshot_filesystem.side_effect = error

        with (
            patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
            pytest.raises(SnapshotTimeoutError) as exc,
        ):
            mock_sandbox.create_snapshot()

        # Transient timeouts must stay retryable (Temporal retries) and must not create error-tracking issues.
        assert exc.value.non_retryable is False
        capture_exception.assert_not_called()

    def test_genuine_failure_raises_snapshot_creation_error_and_is_captured(self, mock_sandbox: Any):
        mock_sandbox._sandbox.snapshot_filesystem.side_effect = RuntimeError("Failed to create image")

        with (
            patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
            pytest.raises(SnapshotCreationError),
        ):
            mock_sandbox.create_snapshot()

        capture_exception.assert_called_once()

    def test_create_directory_snapshot_overrides_modal_default_timeout(self, mock_sandbox: Any):
        mock_sandbox._sandbox.snapshot_directory.return_value = MagicMock(object_id="im-dir-123")

        assert mock_sandbox.create_directory_snapshot("/tmp/workspace") == "im-dir-123"

        mock_sandbox._sandbox.snapshot_directory.assert_called_once_with(
            "/tmp/workspace", timeout=DIRECTORY_SNAPSHOT_TIMEOUT_SECONDS, ttl=None
        )
