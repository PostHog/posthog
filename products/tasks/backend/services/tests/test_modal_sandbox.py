from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError, Timeout

from products.tasks.backend.services.modal_sandbox import (
    AGENT_SERVER_PORT,
    SANDBOX_IMAGE,
    ModalSandbox,
    _get_sandbox_image_reference,
)
from products.tasks.backend.services.sandbox import AgentServerResult, ExecutionResult, SandboxConfig
from products.tasks.backend.temporal.exceptions import SandboxExecutionError


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


class TestGetSandboxImageReference:
    def setup_method(self):
        _get_sandbox_image_reference.cache_clear()

    def test_returns_digest_reference_on_success(self):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest="sha256:abc123")],
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}@sha256:abc123"

    @pytest.mark.parametrize("status_code", [401, 403, 404, 500, 502, 503])
    def test_falls_back_to_master_on_token_request_failure(self, status_code: int):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            return_value=_mock_token_response(status_code=status_code),
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}:master"

    def test_falls_back_to_master_when_token_missing(self):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            return_value=_mock_token_response(token=None),
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}:master"

    @pytest.mark.parametrize("status_code", [401, 403, 404, 500, 502, 503])
    def test_falls_back_to_master_on_manifest_request_failure(self, status_code: int):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(status_code=status_code)],
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}:master"

    def test_falls_back_to_master_when_digest_header_missing(self):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest=None)],
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}:master"

    @pytest.mark.parametrize(
        "exception",
        [
            ConnectionError("Connection refused"),
            Timeout("Request timed out"),
            Exception("Unknown error"),
        ],
    )
    def test_falls_back_to_master_on_request_exception(self, exception: Exception):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            side_effect=exception,
        ):
            result = _get_sandbox_image_reference()

        assert result == f"{SANDBOX_IMAGE}:master"

    def test_caches_result_across_calls(self):
        with patch(
            "products.tasks.backend.services.modal_sandbox.requests.get",
            side_effect=[_mock_token_response(), _mock_manifest_response(digest="sha256:cached123")],
        ) as mock_get:
            result1 = _get_sandbox_image_reference()
            result2 = _get_sandbox_image_reference()
            result3 = _get_sandbox_image_reference()

        assert result1 == result2 == result3 == f"{SANDBOX_IMAGE}@sha256:cached123"
        assert mock_get.call_count == 2  # token + manifest, called only once due to cache


class TestGetSandboxImageReferenceIntegration:
    def setup_method(self):
        _get_sandbox_image_reference.cache_clear()

    def test_resolves_digest_from_ghcr(self):
        result = _get_sandbox_image_reference()

        assert result.startswith(f"{SANDBOX_IMAGE}@sha256:")
        digest_part = result.split("@")[1]
        assert digest_part.startswith("sha256:")
        assert len(digest_part) == 71  # "sha256:" + 64 hex chars


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

    def test_start_agent_server_success(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="200", stderr="", exit_code=0, error=None),
            ]
        )

        mock_sandbox.start_agent_server(
            repository="posthog/posthog",
            task_id="task-123",
            run_id="run-456",
            mode="background",
        )

        start_call = mock_sandbox.execute.call_args_list[0]
        command = start_call[0][0]
        import shlex

        assert f"--port {AGENT_SERVER_PORT}" in command
        assert f"--repositoryPath {shlex.quote('/tmp/workspace/repos/posthog/posthog')}" in command
        assert f"--taskId {shlex.quote('task-123')}" in command
        assert f"--runId {shlex.quote('run-456')}" in command
        assert f"--mode {shlex.quote('background')}" in command

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

        with pytest.raises(SandboxExecutionError, match="Failed to start agent-server"):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
            )

    def test_start_agent_server_raises_on_health_check_failure(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
            ]
            + [ExecutionResult(stdout="502", stderr="", exit_code=0, error=None)] * 20
            + [ExecutionResult(stdout="some log output", stderr="", exit_code=0, error=None)]
        )

        with patch("products.tasks.backend.services.modal_sandbox.time.sleep"):
            with pytest.raises(SandboxExecutionError, match="Agent-server failed to start"):
                mock_sandbox.start_agent_server(
                    repository="posthog/posthog",
                    task_id="task-123",
                    run_id="run-456",
                )

    def test_wait_for_health_check_retries(self, mock_sandbox: Any):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="502", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="502", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="200", stderr="", exit_code=0, error=None),
            ]
        )

        with patch("products.tasks.backend.services.modal_sandbox.time.sleep") as mock_sleep:
            result = mock_sandbox._wait_for_health_check()

        assert result is True
        assert mock_sandbox.execute.call_count == 3
        assert mock_sleep.call_count == 2


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
        sandbox._host_port = 8080

        with patch.object(sandbox, "is_running", return_value=True):
            with patch.object(sandbox, "execute") as mock_execute:
                mock_execute.return_value = MagicMock(exit_code=0)
                with patch.object(sandbox, "_wait_for_health_check", return_value=True):
                    sandbox.start_agent_server(repository, task_id, run_id, mode)

                command = mock_execute.call_args_list[0][0][0]

                org, repo = repository.lower().split("/")
                repo_path = f"/tmp/workspace/repos/{org}/{repo}"

                assert shlex.quote(repo_path) in command
                assert shlex.quote(task_id) in command
                assert shlex.quote(run_id) in command
                assert shlex.quote(mode) in command
