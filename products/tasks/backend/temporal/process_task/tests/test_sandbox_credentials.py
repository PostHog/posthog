import base64

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    GitHubSandboxCredential,
    build_sandbox_credentials,
    github_refresh_interval_seconds,
    set_git_remote_token,
    update_sandbox_env_file,
)


def _ok(stdout: str = "") -> ExecutionResult:
    return ExecutionResult(stdout=stdout, stderr="", exit_code=0)


def _context(**overrides) -> TaskProcessingContext:
    defaults: dict = {
        "task_id": "task-id",
        "run_id": "run-id",
        "team_id": 1,
        "team_uuid": "team-uuid",
        "organization_id": "org-id",
        "github_integration_id": 123,
        "repository": "explore-science/paper-wizard-frontend",
        "distinct_id": "distinct",
    }
    defaults.update(overrides)
    return TaskProcessingContext(**defaults)


class TestGithubRefreshInterval:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("ghs_installationtoken", 20 * 60),
            ("ghu_usertoken", 2 * 60 * 60),
            ("gho_oauthtoken", DEFAULT_REFRESH_INTERVAL_SECONDS),
            ("unknown", DEFAULT_REFRESH_INTERVAL_SECONDS),
        ],
    )
    def test_interval_is_keyed_off_token_prefix(self, token, expected):
        assert github_refresh_interval_seconds(token) == expected


class TestSetGitRemoteToken:
    def test_rewrites_remote_with_fresh_token(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok()

        assert set_git_remote_token(sandbox, "explore-science/paper-wizard-frontend", "ghs_new") is True

        command = sandbox.execute.call_args[0][0]
        assert "git remote set-url origin" in command
        assert "x-access-token:ghs_new" in command
        assert "explore-science/paper-wizard-frontend" in command

    def test_returns_false_on_failure(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = ExecutionResult(stdout="", stderr="not a git repo", exit_code=128)

        assert set_git_remote_token(sandbox, "owner/repo", "ghs_new") is False


class TestUpdateSandboxEnvFile:
    def test_preserves_other_keys_and_replaces_updated_ones(self):
        sandbox = MagicMock()
        existing = b"PATH=/usr/bin\x00GITHUB_TOKEN=ghs_old\x00HOME=/root\x00"
        sandbox.execute.return_value = _ok(base64.b64encode(existing).decode())
        sandbox.write_file.return_value = _ok()

        assert update_sandbox_env_file(sandbox, {"GITHUB_TOKEN": "ghs_new", "GH_TOKEN": "ghs_new"}) is True

        _, payload = sandbox.write_file.call_args[0]
        entries = {e.split(b"=", 1)[0]: e.split(b"=", 1)[1] for e in payload.split(b"\x00") if e}
        # Untouched keys survive, updated key is replaced, new key is appended.
        assert entries[b"PATH"] == b"/usr/bin"
        assert entries[b"HOME"] == b"/root"
        assert entries[b"GITHUB_TOKEN"] == b"ghs_new"
        assert entries[b"GH_TOKEN"] == b"ghs_new"

    def test_noop_when_no_updates(self):
        sandbox = MagicMock()
        assert update_sandbox_env_file(sandbox, {}) is True
        sandbox.execute.assert_not_called()
        sandbox.write_file.assert_not_called()

    def test_writes_updates_when_env_file_absent(self):
        sandbox = MagicMock()
        # base64 of empty file (the `|| true` path yields empty stdout).
        sandbox.execute.return_value = _ok("")
        sandbox.write_file.return_value = _ok()

        assert update_sandbox_env_file(sandbox, {"GH_TOKEN": "ghs_new"}) is True

        _, payload = sandbox.write_file.call_args[0]
        assert payload == b"GH_TOKEN=ghs_new\x00"


class TestGitHubSandboxCredential:
    def test_resolves_and_applies_token_and_reports_interval(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok("")
        sandbox.write_file.return_value = _ok()
        ctx = _context()

        with patch(
            "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
            return_value="ghs_resolved",
        ) as resolve:
            outcome = GitHubSandboxCredential().refresh(sandbox, ctx, MagicMock())

        resolve.assert_called_once()
        assert outcome.refreshed is True
        assert outcome.kind == "github"
        assert outcome.next_refresh_seconds == 20 * 60
        # git remote rewrite ran with the fresh token.
        assert any("x-access-token:ghs_resolved" in str(c.args[0]) for c in sandbox.execute.call_args_list)
        sandbox.write_file.assert_called_once()

    def test_user_token_reports_longer_interval(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok("")
        sandbox.write_file.return_value = _ok()

        with patch(
            "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
            return_value="ghu_resolved",
        ):
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), MagicMock())

        assert outcome.next_refresh_seconds == 2 * 60 * 60

    def test_no_op_without_github_credentials(self):
        sandbox = MagicMock()
        ctx = _context(github_integration_id=None, github_user_integration_id=None)

        outcome = GitHubSandboxCredential().refresh(sandbox, ctx, MagicMock())

        assert outcome.refreshed is False
        sandbox.execute.assert_not_called()
        sandbox.write_file.assert_not_called()


class TestBuildSandboxCredentials:
    def test_includes_github_when_credentials_present(self):
        credentials = build_sandbox_credentials(_context())
        assert [c.kind for c in credentials] == ["github"]

    def test_empty_without_github_credentials(self):
        ctx = _context(github_integration_id=None, github_user_integration_id=None)
        assert build_sandbox_credentials(ctx) == []
