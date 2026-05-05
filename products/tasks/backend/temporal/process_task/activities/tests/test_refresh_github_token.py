import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.tasks.backend.services.agent_command import CommandResult
from products.tasks.backend.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.refresh_github_token import (
    RefreshGithubTokenInput,
    refresh_github_token,
)
from products.tasks.backend.temporal.process_task.utils import _gh_token_issued_cache_key, mark_gh_token_issued

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_gh_token_cache():
    """Each test starts with no recorded issuance so the gate doesn't carry
    state between cases."""
    cache.delete(_gh_token_issued_cache_key("run-1"))
    yield
    cache.delete(_gh_token_issued_cache_key("run-1"))


def _make_task_run(
    *,
    integration_id: int | None = 99,
    user_integration_id: str | None = None,
    repository: str | None = "posthog/posthog",
    sandbox_id: str | None = "sandbox-abc",
    sandbox_url: str | None = "https://sandbox.example.com",
    created_by: MagicMock | None = None,
) -> MagicMock:
    task = MagicMock()
    task.id = "task-1"
    task.repository = repository
    task.github_integration_id = integration_id
    task.github_user_integration_id = user_integration_id
    task.created_by = created_by
    task_run = MagicMock()
    task_run.id = "run-1"
    task_run.task = task
    task_run.state = {"sandbox_id": sandbox_id, "sandbox_url": sandbox_url}
    return task_run


def _patch_paths():
    return {
        "TaskRun": "products.tasks.backend.temporal.process_task.activities.refresh_github_token.TaskRun",
        "get_token": "products.tasks.backend.temporal.process_task.activities.refresh_github_token.get_sandbox_github_token",
        "send_set": "products.tasks.backend.temporal.process_task.activities.refresh_github_token.send_set_gh_token",
        "Sandbox": "products.tasks.backend.temporal.process_task.activities.refresh_github_token.Sandbox",
        "conn_token": "products.tasks.backend.temporal.process_task.activities.refresh_github_token.create_sandbox_connection_token",
    }


class TestRefreshGithubTokenSkips:
    """Activity is a no-op without contradicting any external systems when
    inputs are incomplete."""

    @patch("products.tasks.backend.temporal.process_task.activities.refresh_github_token.send_set_gh_token")
    def test_skipped_when_recently_issued(self, mock_send):
        mark_gh_token_issued("run-1")

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_not_called()

    @patch(_patch_paths()["TaskRun"])
    @patch(_patch_paths()["send_set"])
    def test_skipped_when_run_missing(self, mock_send, mock_task_run_cls):
        from products.tasks.backend.models import TaskRun as RealTaskRun

        mock_task_run_cls.DoesNotExist = RealTaskRun.DoesNotExist
        mock_task_run_cls.objects.select_related.return_value.get.side_effect = RealTaskRun.DoesNotExist

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_not_called()

    @patch(_patch_paths()["TaskRun"])
    @patch(_patch_paths()["send_set"])
    def test_skipped_when_no_sandbox_in_state(self, mock_send, mock_task_run_cls):
        task_run = _make_task_run(sandbox_id=None, sandbox_url=None)
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_not_called()

    @patch(_patch_paths()["TaskRun"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["send_set"])
    def test_skipped_when_no_github_credentials(self, mock_send, mock_get_token, mock_task_run_cls):
        task_run = _make_task_run(integration_id=None, user_integration_id=None)
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_get_token.assert_not_called()
        mock_send.assert_not_called()


class TestRefreshGithubTokenSuccess:
    @patch(_patch_paths()["Sandbox"])
    @patch(_patch_paths()["conn_token"])
    @patch(_patch_paths()["send_set"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["TaskRun"])
    def test_dispatches_set_token_and_rewrites_git_remote(
        self, mock_task_run_cls, mock_get_token, mock_send, mock_conn_token, mock_sandbox_cls
    ):
        created_by = MagicMock(id=42, distinct_id="u42")
        task_run = _make_task_run(created_by=created_by)
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_get_token.return_value = "ghs_fresh"
        mock_conn_token.return_value = "jwt"
        mock_send.return_value = CommandResult(success=True, status_code=200, data={"result": {"updated": True}})

        sandbox = MagicMock()
        sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
        mock_sandbox_cls.get_by_id.return_value = sandbox

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_get_token.assert_called_once()
        send_args, send_kwargs = mock_send.call_args
        assert send_args[0] is task_run
        assert send_args[1] == "ghs_fresh"
        assert send_kwargs["auth_token"] == "jwt"

        sandbox.execute.assert_called_once()
        cmd = sandbox.execute.call_args[0][0]
        assert "git remote set-url origin" in cmd
        assert "x-access-token:ghs_fresh" in cmd
        assert "github.com/posthog/posthog.git" in cmd

        # Cache gate is set so subsequent calls within the window are no-ops.
        assert cache.get(_gh_token_issued_cache_key("run-1")) is True

    @patch(_patch_paths()["Sandbox"])
    @patch(_patch_paths()["conn_token"])
    @patch(_patch_paths()["send_set"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["TaskRun"])
    def test_skips_git_remote_rewrite_for_repoless_run(
        self, mock_task_run_cls, mock_get_token, mock_send, mock_conn_token, mock_sandbox_cls
    ):
        created_by = MagicMock(id=42, distinct_id="u42")
        task_run = _make_task_run(repository=None, created_by=created_by)
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_get_token.return_value = "gho_user"
        mock_conn_token.return_value = "jwt"
        mock_send.return_value = CommandResult(success=True, status_code=200)

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_called_once()
        mock_sandbox_cls.get_by_id.assert_not_called()
        assert cache.get(_gh_token_issued_cache_key("run-1")) is True

    @patch(_patch_paths()["Sandbox"])
    @patch(_patch_paths()["conn_token"])
    @patch(_patch_paths()["send_set"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["TaskRun"])
    def test_skips_when_no_token_resolved(
        self, mock_task_run_cls, mock_get_token, mock_send, mock_conn_token, mock_sandbox_cls
    ):
        task_run = _make_task_run(created_by=MagicMock(id=42, distinct_id="u42"))
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_get_token.return_value = None

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_not_called()
        mock_sandbox_cls.get_by_id.assert_not_called()
        assert cache.get(_gh_token_issued_cache_key("run-1")) is None

    @patch(_patch_paths()["Sandbox"])
    @patch(_patch_paths()["conn_token"])
    @patch(_patch_paths()["send_set"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["TaskRun"])
    def test_does_not_mark_when_set_token_fails(
        self, mock_task_run_cls, mock_get_token, mock_send, mock_conn_token, mock_sandbox_cls
    ):
        task_run = _make_task_run(created_by=MagicMock(id=42, distinct_id="u42"))
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_get_token.return_value = "ghs_fresh"
        mock_conn_token.return_value = "jwt"
        mock_send.return_value = CommandResult(success=False, status_code=502, error="down")

        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        # Failure is non-fatal but the cache stays empty so the next iteration retries.
        assert cache.get(_gh_token_issued_cache_key("run-1")) is None
        mock_sandbox_cls.get_by_id.assert_not_called()

    @patch(_patch_paths()["Sandbox"])
    @patch(_patch_paths()["conn_token"])
    @patch(_patch_paths()["send_set"])
    @patch(_patch_paths()["get_token"])
    @patch(_patch_paths()["TaskRun"])
    def test_token_mint_failure_is_non_fatal(
        self, mock_task_run_cls, mock_get_token, mock_send, mock_conn_token, mock_sandbox_cls
    ):
        task_run = _make_task_run(created_by=MagicMock(id=42, distinct_id="u42"))
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_get_token.side_effect = RuntimeError("github 503")

        # Must not raise.
        refresh_github_token(RefreshGithubTokenInput(run_id="run-1"))

        mock_send.assert_not_called()
        mock_sandbox_cls.get_by_id.assert_not_called()
        assert cache.get(_gh_token_issued_cache_key("run-1")) is None
