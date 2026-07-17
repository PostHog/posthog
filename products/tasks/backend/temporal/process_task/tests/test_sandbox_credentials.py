import base64

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.sandbox import ExecutionResult
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

    def test_deleted_integration_raises_credential_unavailable(self):
        from products.tasks.backend.exceptions import CredentialUnavailableError

        task = MagicMock()
        task.github_integration_id = None
        task.github_user_integration_id = None

        with (
            patch(f"{MODULE}.is_caller_token_run", return_value=False),
            patch(f"{MODULE}.get_sandbox_github_token") as resolve,
        ):
            with pytest.raises(CredentialUnavailableError):
                GitHubSandboxCredential().refresh(MagicMock(), _context(), task)

        resolve.assert_not_called()

    def test_fresh_task_ids_take_precedence_over_ctx_snapshot(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok("")
        sandbox.write_file.return_value = _ok()
        task = MagicMock()
        task.github_integration_id = 456
        task.github_user_integration_id = None

        with patch(f"{MODULE}.get_sandbox_github_token", return_value="ghs_fresh") as resolve:
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), task)

        assert outcome.refreshed is True
        assert resolve.call_args.args[0] == 456
        assert resolve.call_args.kwargs["github_user_integration_id"] is None

    def test_caller_token_run_with_deleted_integration_is_not_orphaned(self):
        from products.tasks.backend.temporal.process_task.utils import PrAuthorshipMode

        sandbox = MagicMock()
        sandbox.execute.return_value = _ok("")
        sandbox.write_file.return_value = _ok()
        task = MagicMock()
        task.github_integration_id = None
        task.github_user_integration_id = None

        with (
            patch(f"{MODULE}.get_pr_authorship_mode", return_value=PrAuthorshipMode.USER),
            patch(f"{MODULE}.is_caller_token_run", return_value=True),
            patch(f"{MODULE}.get_sandbox_github_token", return_value="ghu_caller"),
        ):
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), task)

        assert outcome.refreshed is True


class TestBuildSandboxCredentials:
    def test_includes_github_when_credentials_present(self):
        credentials = build_sandbox_credentials(_context())
        assert [c.kind for c in credentials] == ["github"]

    def test_empty_without_github_credentials(self):
        ctx = _context(github_integration_id=None, github_user_integration_id=None)
        assert build_sandbox_credentials(ctx) == []


MODULE = "products.tasks.backend.temporal.process_task.sandbox_credentials"


class TestSharedUserIntegrationRefresh:
    def _as_user_integration_run(self, stack):
        from products.tasks.backend.temporal.process_task.utils import PrAuthorshipMode

        stack.enter_context(patch(f"{MODULE}.get_pr_authorship_mode", return_value=PrAuthorshipMode.USER))
        stack.enter_context(patch(f"{MODULE}.is_caller_token_run", return_value=False))

    def test_refresh_applies_coordinated_token(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import USER_TOKEN_REFRESH_INTERVAL_SECONDS

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            resolve = stack.enter_context(patch(f"{MODULE}.resolve_coordinated_user_token", return_value="ghu_fresh"))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))

            sandbox = MagicMock()
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), MagicMock())

            assert outcome.refreshed is True
            assert outcome.next_refresh_seconds == USER_TOKEN_REFRESH_INTERVAL_SECONDS
            resolve.assert_called_once()
            apply.assert_called_once_with(sandbox, "explore-science/paper-wizard-frontend", "ghu_fresh")

    def test_refresh_reports_not_refreshed_when_no_token(self):
        import contextlib

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            stack.enter_context(patch(f"{MODULE}.resolve_coordinated_user_token", return_value=None))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))

            outcome = GitHubSandboxCredential().refresh(MagicMock(), _context(), MagicMock())

            assert outcome.refreshed is False
            apply.assert_not_called()

    def test_reauthorization_falls_back_to_installation_token(self):
        import contextlib

        from posthog.models.user_integration import ReauthorizationRequired

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            stack.enter_context(
                patch(f"{MODULE}.resolve_coordinated_user_token", side_effect=ReauthorizationRequired("expired"))
            )
            installation_token = stack.enter_context(patch(f"{MODULE}.get_github_token", return_value="ghs_team"))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))
            task = MagicMock()
            task.github_integration_id = 456

            sandbox = MagicMock()
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), task)

            assert outcome.refreshed is True
            assert outcome.next_refresh_seconds == 20 * 60
            installation_token.assert_called_once_with(456)
            apply.assert_called_once_with(sandbox, "explore-science/paper-wizard-frontend", "ghs_team")

    def test_reauthorization_without_team_integration_raises_credential_unavailable(self):
        import contextlib

        from posthog.models.user_integration import ReauthorizationRequired

        from products.tasks.backend.exceptions import CredentialUnavailableError

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            stack.enter_context(
                patch(f"{MODULE}.resolve_coordinated_user_token", side_effect=ReauthorizationRequired("expired"))
            )
            task = MagicMock()
            task.github_integration_id = None

            with pytest.raises(CredentialUnavailableError):
                GitHubSandboxCredential().refresh(MagicMock(), _context(), task)

    def test_caller_token_run_skips_coordinated_path(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.utils import PrAuthorshipMode

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.get_pr_authorship_mode", return_value=PrAuthorshipMode.USER))
            stack.enter_context(patch(f"{MODULE}.is_caller_token_run", return_value=True))
            resolve = stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task"))
            stack.enter_context(patch(f"{MODULE}.get_sandbox_github_token", return_value="ghu_caller"))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))

            sandbox = MagicMock()
            sandbox.id = "sb-own"
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), MagicMock())

            assert outcome.refreshed is True
            resolve.assert_not_called()
            apply.assert_called_once_with(sandbox, "explore-science/paper-wizard-frontend", "ghu_caller")


class TestResolveCoordinatedUserToken:
    def _patch_lock(self, stack, *, acquired: bool):
        lock = MagicMock()
        lock.acquire.return_value = acquired
        get_client = stack.enter_context(patch(f"{MODULE}.get_client"))
        get_client.return_value.lock.return_value = lock
        return lock

    def test_valid_token_returned_without_locking(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import resolve_coordinated_user_token

        with contextlib.ExitStack() as stack:
            get_client = stack.enter_context(patch(f"{MODULE}.get_client"))
            propagate = stack.enter_context(patch(f"{MODULE}._propagate_user_token"))
            integration = MagicMock()
            integration.user_access_token_expired.return_value = False
            integration.get_usable_user_access_token.return_value = "ghu_current"

            assert resolve_coordinated_user_token(integration) == "ghu_current"
            get_client.return_value.lock.assert_not_called()
            propagate.assert_not_called()

    def test_expired_token_minted_and_propagated_under_lock(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import resolve_coordinated_user_token

        with contextlib.ExitStack() as stack:
            lock = self._patch_lock(stack, acquired=True)
            integration = MagicMock()
            integration.integration.id = 7
            integration.user_access_token_expired.return_value = True
            current = MagicMock()
            current.user_access_token_expired.return_value = True
            current.get_usable_user_access_token.return_value = "ghu_fresh"
            stack.enter_context(patch(f"{MODULE}.UserGitHubIntegration", return_value=current))
            propagate = stack.enter_context(patch(f"{MODULE}._propagate_user_token", return_value=2))

            assert resolve_coordinated_user_token(integration) == "ghu_fresh"
            current.get_usable_user_access_token.assert_called_once()
            propagate.assert_called_once_with(7, "ghu_fresh")
            lock.release.assert_called_once()

    def test_acquired_but_already_fresh_does_not_propagate(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import resolve_coordinated_user_token

        with contextlib.ExitStack() as stack:
            lock = self._patch_lock(stack, acquired=True)
            integration = MagicMock()
            integration.integration.id = 7
            integration.user_access_token_expired.return_value = True
            current = MagicMock()
            current.user_access_token_expired.return_value = False  # a prior holder already minted
            current.get_usable_user_access_token.return_value = "ghu_already_fresh"
            stack.enter_context(patch(f"{MODULE}.UserGitHubIntegration", return_value=current))
            propagate = stack.enter_context(patch(f"{MODULE}._propagate_user_token"))

            assert resolve_coordinated_user_token(integration) == "ghu_already_fresh"
            propagate.assert_not_called()
            lock.release.assert_called_once()

    def test_contended_lock_returns_current_without_minting(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import resolve_coordinated_user_token

        with contextlib.ExitStack() as stack:
            lock = self._patch_lock(stack, acquired=False)
            integration = MagicMock()
            integration.integration.id = 7
            integration.user_access_token_expired.return_value = True
            sibling = MagicMock()
            sibling.user_access_token = "ghu_sibling_fresh"
            stack.enter_context(patch(f"{MODULE}.UserGitHubIntegration", return_value=sibling))
            propagate = stack.enter_context(patch(f"{MODULE}._propagate_user_token"))

            assert resolve_coordinated_user_token(integration) == "ghu_sibling_fresh"
            sibling.get_usable_user_access_token.assert_not_called()
            propagate.assert_not_called()
            lock.release.assert_not_called()


@pytest.mark.django_db
class TestLiveSandboxRegistry:
    def test_scopes_to_in_progress_runs_with_a_sandbox_for_the_integration(self):
        from posthog.models import Organization, Team
        from posthog.models.user import User
        from posthog.models.user_integration import UserIntegration

        from products.tasks.backend.models import Task, TaskRun
        from products.tasks.backend.temporal.process_task.sandbox_credentials import (
            _live_sandboxes_for_user_integration,
        )

        org = Organization.objects.create(name="o")
        team = Team.objects.create(organization=org, name="t")
        user = User.objects.create(email="reg@test.com")
        integration = UserIntegration.objects.create(
            user=user, kind=UserIntegration.IntegrationKind.GITHUB, integration_id="i1", config={}, sensitive_config={}
        )
        other = UserIntegration.objects.create(
            user=user, kind=UserIntegration.IntegrationKind.GITHUB, integration_id="i2", config={}, sensitive_config={}
        )

        def _task(repo):
            return Task.objects.create(team=team, created_by=user, repository=repo, github_user_integration=integration)

        live = _task("org/live")
        live_run = TaskRun.objects.create(
            task=live,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-live", "pr_authorship_mode": "user"},
        )
        no_sandbox = _task("org/nosandbox")
        TaskRun.objects.create(task=no_sandbox, team=team, status=TaskRun.Status.IN_PROGRESS, state={})
        done = _task("org/done")
        TaskRun.objects.create(task=done, team=team, status=TaskRun.Status.COMPLETED, state={"sandbox_id": "sb-done"})
        other_task = Task.objects.create(
            team=team, created_by=user, repository="org/other", github_user_integration=other
        )
        TaskRun.objects.create(
            task=other_task, team=team, status=TaskRun.Status.IN_PROGRESS, state={"sandbox_id": "sb-other"}
        )
        # Bot-authored — uses an installation token, never the user integration's rotating token.
        bot = _task("org/bot")
        TaskRun.objects.create(
            task=bot,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-bot", "pr_authorship_mode": "bot"},
        )
        # Authorized by a caller-supplied token — excluded so we never overwrite its credential.
        caller = _task("org/caller")
        TaskRun.objects.create(
            task=caller,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-caller", "pr_authorship_mode": "user", "github_credential_source": "caller_token"},
        )

        result = _live_sandboxes_for_user_integration(integration.id)

        assert result == [(str(live_run.id), "sb-live", "org/live")]
