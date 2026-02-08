import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError, Timeout

from products.tasks.backend.services.modal_sandbox import SANDBOX_IMAGE, ModalSandbox, _get_sandbox_image_reference
from products.tasks.backend.services.sandbox import SandboxConfig


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


class TestModalSandboxCommandEscaping:
    @pytest.mark.parametrize(
        "task_id,run_id,repo_path",
        [
            ("task-123", "run-456", "/tmp/workspace/repos/org/repo"),
            ("task; echo hacked", "run-789", "/tmp/workspace/repos/org/repo"),
            ("task-abc", "run; rm -rf /", "/tmp/workspace/repos/org/repo"),
            ("task-xyz", "run-123", "/tmp/workspace/repos/org'; echo hacked; echo '/repo"),
            ("task$(whoami)", "run-123", "/tmp/workspace/repos/org/repo"),
            ("task-123", "run`id`", "/tmp/workspace/repos/org/repo"),
        ],
    )
    def test_task_command_shell_injection_prevention(self, task_id, run_id, repo_path):
        import shlex

        sandbox = ModalSandbox.__new__(ModalSandbox)
        sandbox.id = "sb-123"
        sandbox.config = SandboxConfig(name="test")

        command = sandbox._get_task_command(task_id, run_id, repo_path, create_pr=True)

        assert shlex.quote(task_id) in command
        assert shlex.quote(run_id) in command
        assert shlex.quote(repo_path) in command

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
                call_args = mock_execute.call_args
                command = call_args[0][0]

                org, repo = repository.lower().split("/")
                target_path = f"/tmp/workspace/repos/{org}/{repo}"
                org_path = f"/tmp/workspace/repos/{org}"

                assert shlex.quote(target_path) in command
                assert shlex.quote(org_path) in command
                assert shlex.quote(repo) in command
