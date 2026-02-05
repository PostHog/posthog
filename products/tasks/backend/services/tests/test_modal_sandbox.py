import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError, Timeout

from products.tasks.backend.services.modal_sandbox import (
    AGENT_SERVER_PORT,
    SANDBOX_IMAGE,
    ModalSandbox,
    _get_sandbox_image_reference,
)
from products.tasks.backend.services.sandbox import ExecutionResult, SandboxConfig
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
    def mock_sandbox(self):
        mock_modal_sandbox = MagicMock()
        mock_modal_sandbox.object_id = "test-sandbox-id"
        mock_modal_sandbox.poll.return_value = None

        mock_tunnel = MagicMock()
        mock_tunnel.url = "https://test-tunnel.modal.run"
        mock_modal_sandbox.tunnels.return_value = {AGENT_SERVER_PORT: mock_tunnel}

        config = SandboxConfig(name="test-sandbox")
        return ModalSandbox(sandbox=mock_modal_sandbox, config=config)

    def test_start_agent_server_success(self, mock_sandbox: ModalSandbox):
        mock_sandbox.execute = MagicMock(
            side_effect=[
                ExecutionResult(stdout="", stderr="", exit_code=0, error=None),
                ExecutionResult(stdout="200", stderr="", exit_code=0, error=None),
            ]
        )

        url = mock_sandbox.start_agent_server(
            repository="posthog/posthog",
            task_id="task-123",
            run_id="run-456",
            mode="background",
        )

        assert url == "https://test-tunnel.modal.run"
        assert mock_sandbox.sandbox_url == "https://test-tunnel.modal.run"

        start_call = mock_sandbox.execute.call_args_list[0]
        command = start_call[0][0]
        assert f"--port {AGENT_SERVER_PORT}" in command
        assert "--repositoryPath /tmp/workspace/repos/posthog/posthog" in command
        assert "--taskId task-123" in command
        assert "--runId run-456" in command
        assert "--mode background" in command

    def test_start_agent_server_raises_when_not_running(self, mock_sandbox: ModalSandbox):
        mock_sandbox._sandbox.poll.return_value = 0

        with pytest.raises(RuntimeError, match="Sandbox not in running state"):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
            )

    def test_start_agent_server_raises_on_start_failure(self, mock_sandbox: ModalSandbox):
        mock_sandbox.execute = MagicMock(
            return_value=ExecutionResult(stdout="", stderr="npx: command not found", exit_code=127, error=None)
        )

        with pytest.raises(SandboxExecutionError, match="Failed to start agent-server"):
            mock_sandbox.start_agent_server(
                repository="posthog/posthog",
                task_id="task-123",
                run_id="run-456",
            )

    def test_start_agent_server_raises_on_health_check_failure(self, mock_sandbox: ModalSandbox):
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

    def test_wait_for_health_check_retries(self, mock_sandbox: ModalSandbox):
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
