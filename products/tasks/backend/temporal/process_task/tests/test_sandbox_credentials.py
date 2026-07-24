import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.agentsh import GITHUB_ENV_FILE, OAUTH_ENV_FILE
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    GitHubSandboxCredential,
    build_sandbox_credentials,
    github_refresh_interval_seconds,
    replace_sandbox_credentials,
    set_git_remote_token,
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

    def test_removes_stale_token_when_current_credential_is_missing(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok()

        assert set_git_remote_token(sandbox, "owner/repo", None) is True

        command = sandbox.execute.call_args[0][0]
        assert "https://github.com/owner/repo.git" in command
        assert "x-access-token" not in command

    def test_returns_false_on_failure(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = ExecutionResult(stdout="", stderr="not a git repo", exit_code=128)

        assert set_git_remote_token(sandbox, "owner/repo", "ghs_new") is False


class TestReplaceSandboxCredentials:
    def test_replaces_each_credential_domain_without_reading_existing_state(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok()
        sandbox.write_file.return_value = _ok()

        assert replace_sandbox_credentials(sandbox, "ghs_new", "oauth_new") is True

        assert sandbox.write_file.call_args_list[0].args == (
            GITHUB_ENV_FILE,
            b"GITHUB_TOKEN=ghs_new\x00GH_TOKEN=ghs_new\x00",
        )
        assert sandbox.write_file.call_args_list[1].args == (
            OAUTH_ENV_FILE,
            b"POSTHOG_PERSONAL_API_KEY=oauth_new\x00",
        )
        assert [call.args[0] for call in sandbox.execute.call_args_list] == [
            f"chmod 600 {GITHUB_ENV_FILE}",
            f"chmod 600 {OAUTH_ENV_FILE}",
        ]

    def test_empty_current_credentials_clear_both_files(self):
        sandbox = MagicMock()
        sandbox.execute.return_value = _ok()
        sandbox.write_file.return_value = _ok()

        assert replace_sandbox_credentials(sandbox, None, None) is True

        assert [call.args for call in sandbox.write_file.call_args_list] == [
            (GITHUB_ENV_FILE, b""),
            (OAUTH_ENV_FILE, b""),
        ]


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

    def test_scheduled_refresh_skips_when_sandbox_bound_to_different_actor(self):
        # A per-message actor transition rebound this sandbox to another actor. The scheduled
        # refresh resolves the actor from the startup context, so it carries the owner's token;
        # applying it would resurrect the owner's identity over the current actor's session.
        from products.tasks.backend.temporal.process_task.utils import mark_sandbox_github_identity

        sandbox = MagicMock()
        task = MagicMock()
        task.github_integration_id = 123
        task.created_by_id = 2  # run owner
        mark_sandbox_github_identity("run-transition", 99)  # transitioned to a different actor

        with patch(f"{MODULE}.get_sandbox_github_token") as resolve:
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(run_id="run-transition"), task)

        assert outcome.refreshed is False
        resolve.assert_not_called()  # never resolved or applied the owner's token
        sandbox.execute.assert_not_called()
        sandbox.write_file.assert_not_called()


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
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox", return_value=True))

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
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox", return_value=True))
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
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox", return_value=True))

            sandbox = MagicMock()
            sandbox.id = "sb-own"
            outcome = GitHubSandboxCredential().refresh(sandbox, _context(), MagicMock())

            assert outcome.refreshed is True
            resolve.assert_not_called()
            apply.assert_called_once_with(sandbox, "explore-science/paper-wizard-frontend", "ghu_caller")


class TestApplyOwnerTokenLocked:
    def _lock(self, stack, *, acquired):
        lock = MagicMock()
        lock.acquire.return_value = acquired
        get_client = stack.enter_context(patch(f"{MODULE}.get_client"))
        get_client.return_value.lock.return_value = lock
        return lock

    def test_applies_while_sandbox_still_bound_to_owner(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import _apply_owner_token_locked

        with contextlib.ExitStack() as stack:
            self._lock(stack, acquired=True)
            stack.enter_context(patch(f"{MODULE}.get_sandbox_github_identity_user", return_value=None))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox", return_value=True))
            sandbox = MagicMock()
            sandbox.id = "sb-1"

            assert _apply_owner_token_locked(sandbox, "org/repo", "ghu_x", "run-1", {}, 7) is True
            apply.assert_called_once_with(sandbox, "org/repo", "ghu_x")

    def test_skips_when_a_transition_rebound_the_sandbox_to_another_actor(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import _apply_owner_token_locked

        with contextlib.ExitStack() as stack:
            self._lock(stack, acquired=True)
            # Marker moved to actor 99 under the lock — the owner (7) token must not overwrite it.
            stack.enter_context(patch(f"{MODULE}.get_sandbox_github_identity_user", return_value=99))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))
            sandbox = MagicMock()
            sandbox.id = "sb-1"

            assert _apply_owner_token_locked(sandbox, "org/repo", "ghu_x", "run-1", {}, 7) is False
            apply.assert_not_called()

    def test_fails_closed_without_applying_when_the_lock_is_contended(self):
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import _apply_owner_token_locked

        with contextlib.ExitStack() as stack:
            lock = self._lock(stack, acquired=False)
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))
            sandbox = MagicMock()
            sandbox.id = "sb-1"

            assert _apply_owner_token_locked(sandbox, "org/repo", "ghu_x", "run-1", {}, 7) is False
            apply.assert_not_called()
            lock.release.assert_not_called()

    def test_lock_is_leased_long_enough_to_outlive_a_writer_past_the_old_30s_lease(self):
        # A credential write does a git-remote rewrite + env-file write + chmod, each an in-sandbox
        # exec bounded by a 30s timeout, so it can run well past the old 30s lease. The redis lock
        # must be leased for that whole worst case, or the lease expires mid-write and a concurrent
        # refresh could acquire and interleave.
        import contextlib

        from products.tasks.backend.temporal.process_task.sandbox_credentials import (
            _CREDENTIAL_LOCK_TTL_SECONDS,
            _apply_owner_token_locked,
        )

        assert _CREDENTIAL_LOCK_TTL_SECONDS == 5 * 60
        assert _CREDENTIAL_LOCK_TTL_SECONDS > 2 * 30  # clears a 30s git-remote + 30s chmod worst case

        with contextlib.ExitStack() as stack:
            get_client = stack.enter_context(patch(f"{MODULE}.get_client"))
            lock = MagicMock()
            lock.acquire.return_value = True
            get_client.return_value.lock.return_value = lock
            stack.enter_context(patch(f"{MODULE}.get_sandbox_github_identity_user", return_value=None))
            stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox", return_value=True))
            sandbox = MagicMock()
            sandbox.id = "sb-1"

            _apply_owner_token_locked(sandbox, "org/repo", "ghu_x", "run-1", {}, 7)

            # The lock is leased for the full worst-case write, not the old 30s.
            get_client.return_value.lock.assert_called_once()
            assert get_client.return_value.lock.call_args.kwargs["timeout"] == _CREDENTIAL_LOCK_TTL_SECONDS


class TestLoopOwnerRefreshGate:
    def _as_user_integration_run(self, stack):
        from products.tasks.backend.temporal.process_task.utils import PrAuthorshipMode

        stack.enter_context(patch(f"{MODULE}.get_pr_authorship_mode", return_value=PrAuthorshipMode.USER))
        stack.enter_context(patch(f"{MODULE}.is_caller_token_run", return_value=False))

    def test_user_token_refresh_is_withheld_when_the_loop_owner_lost_access(self):
        import contextlib

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            stack.enter_context(patch(f"{MODULE}.resolve_coordinated_user_token", return_value="ghu_fresh"))
            stack.enter_context(patch(f"{MODULE}.transaction"))
            stack.enter_context(patch(f"{MODULE}.loop_owner_eligible_for_credentials", return_value=False))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))

            outcome = GitHubSandboxCredential().refresh(MagicMock(), _context(state={"loop_id": "loop-1"}), MagicMock())

            assert outcome.refreshed is False
            apply.assert_not_called()

    def test_installation_fallback_is_withheld_when_the_loop_owner_lost_access(self):
        import contextlib

        from posthog.models.user_integration import ReauthorizationRequired

        with contextlib.ExitStack() as stack:
            self._as_user_integration_run(stack)
            stack.enter_context(patch(f"{MODULE}.resolve_user_github_integration_for_task", return_value=MagicMock()))
            stack.enter_context(
                patch(f"{MODULE}.resolve_coordinated_user_token", side_effect=ReauthorizationRequired("expired"))
            )
            stack.enter_context(patch(f"{MODULE}.get_github_token", return_value="ghs_team"))
            stack.enter_context(patch(f"{MODULE}.transaction"))
            stack.enter_context(patch(f"{MODULE}.loop_owner_eligible_for_credentials", return_value=False))
            apply = stack.enter_context(patch(f"{MODULE}.apply_github_credentials_to_sandbox"))
            task = MagicMock()
            task.github_integration_id = 456

            outcome = GitHubSandboxCredential().refresh(MagicMock(), _context(state={"loop_id": "loop-1"}), task)

            assert outcome.refreshed is False
            apply.assert_not_called()


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

        # Loop runs pass the owner-eligibility gate per row: an eligible member's loop sandbox
        # still receives the sibling token, a deactivated owner's must not.
        member = User.objects.create(email="member@test.com")
        org.members.add(member)
        eligible_loop = Task.objects.create(
            team=team, created_by=member, repository="org/loop", github_user_integration=integration
        )
        eligible_loop_run = TaskRun.objects.create(
            task=eligible_loop,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-loop", "pr_authorship_mode": "user", "loop_id": "loop-1"},
        )
        deactivated = User.objects.create(email="gone@test.com", is_active=False)
        org.members.add(deactivated)
        revoked_loop = Task.objects.create(
            team=team, created_by=deactivated, repository="org/revoked", github_user_integration=integration
        )
        TaskRun.objects.create(
            task=revoked_loop,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-revoked", "pr_authorship_mode": "user", "loop_id": "loop-2"},
        )

        result = _live_sandboxes_for_user_integration(integration.id)

        assert {(r.run_id, r.sandbox_id, r.repository) for r in result} == {
            (str(live_run.id), "sb-live", "org/live"),
            (str(eligible_loop_run.id), "sb-loop", "org/loop"),
        }

    @pytest.mark.parametrize("marker,included", [("none", True), ("owner", True), ("other", False)])
    def test_actor_transition_gates_owner_token_propagation(self, marker, included):
        from posthog.models import Organization, Team
        from posthog.models.user import User
        from posthog.models.user_integration import UserIntegration

        from products.tasks.backend.models import Task, TaskRun
        from products.tasks.backend.temporal.process_task.sandbox_credentials import (
            _live_sandboxes_for_user_integration,
        )
        from products.tasks.backend.temporal.process_task.utils import mark_sandbox_github_identity

        org = Organization.objects.create(name="o")
        team = Team.objects.create(organization=org, name="t")
        owner = User.objects.create(email="owner@test.com")
        other = User.objects.create(email="other@test.com")
        integration = UserIntegration.objects.create(
            user=owner, kind=UserIntegration.IntegrationKind.GITHUB, integration_id="i1", config={}, sensitive_config={}
        )
        task = Task.objects.create(
            team=team, created_by=owner, repository="org/repo", github_user_integration=integration
        )
        run = TaskRun.objects.create(
            task=task,
            team=team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-x", "pr_authorship_mode": "user"},
        )
        # An unset marker (no transition yet) and one bound to the owner both propagate; a marker
        # bound to a different per-message actor means the sandbox was logged out / rebound, so the
        # owner's rotating token must not overwrite it.
        if marker == "owner":
            mark_sandbox_github_identity("sb-x", owner.id)
        elif marker == "other":
            mark_sandbox_github_identity("sb-x", other.id)

        result = _live_sandboxes_for_user_integration(integration.id)

        assert (
            [(r.run_id, r.sandbox_id, r.repository) for r in result] == [(str(run.id), "sb-x", "org/repo")]
        ) is included
