import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.sandbox_credentials import CredentialRefreshOutcome
from products.tasks.backend.temporal.process_task.sandbox_identity import (
    REFRESH_RETRY_DELAY_SECONDS,
    ensure_sandbox_identity,
)
from products.tasks.backend.temporal.process_task.tests.helpers import make_mcp_config, make_task_run_mock
from products.tasks.backend.temporal.process_task.utils import (
    _mcp_token_issued_cache_key,
    _sandbox_identity_cache_key,
    mark_mcp_token_issued,
    mark_sandbox_identity,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_identity_cache():
    """Ensure each test starts with no recorded token issuances or session
    identities so the gates don't carry state between tests."""
    cache.clear()
    yield
    cache.clear()


def _make_processing_context(**overrides: object) -> TaskProcessingContext:
    defaults: dict = {
        "task_id": "task-1",
        "run_id": "run-1",
        "team_id": 7,
        "team_uuid": "team-uuid",
        "organization_id": "org-id",
        "github_integration_id": 11,
        "repository": "posthog/example",
        "distinct_id": "d-1",
    }
    defaults.update(overrides)
    return TaskProcessingContext(**defaults)


def _ensure(task_run, actor_id: int | None = 42, scopes="read_only", auth_token=None, processing_context=None) -> None:
    actor = MagicMock(id=actor_id) if actor_id is not None else None
    ensure_sandbox_identity(
        task_run,
        actor,
        posthog_mcp_scopes=scopes,
        auth_token=auth_token,
        processing_context=processing_context,
    )


def _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh):
    mock_oauth.return_value = "fresh-token"
    mock_ph_configs.return_value = [make_mcp_config(token="fresh-token")]
    mock_user_configs.return_value = []
    mock_send_refresh.return_value = CommandResult(success=True, status_code=200)


@patch("products.tasks.backend.temporal.process_task.sandbox_identity.time.sleep")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.send_refresh_session")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_user_mcp_server_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_sandbox_ph_mcp_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.create_oauth_access_token_for_run")
class TestRebindMcp:
    def test_success_path_single_call(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        task_run = make_task_run_mock()
        _ensure(task_run, auth_token="jwt")

        mock_oauth.assert_called_once_with(task_run.task, task_run.state, scopes="read_only")
        mock_ph_configs.assert_called_once_with(
            token="fresh-token", project_id=7, scopes="read_only", interaction_origin=None, task_id="task-1"
        )
        mock_user_configs.assert_called_once_with(token="fresh-token", team_id=7, user_id=42, interaction_origin=None)
        mock_send_refresh.assert_called_once()
        _, kwargs = mock_send_refresh.call_args
        assert kwargs["auth_token"] == "jwt"
        assert mock_send_refresh.call_args.args[0] is task_run
        # mcpServers payload is serialized McpServerConfig shape
        mcp_servers = mock_send_refresh.call_args.args[1]
        assert mcp_servers == [make_mcp_config(token="fresh-token").to_dict()]

    def test_retries_once_on_first_failure(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_send_refresh.side_effect = [
            CommandResult(success=False, status_code=502, error="transient", retryable=True),
            CommandResult(success=True, status_code=200),
        ]

        _ensure(make_task_run_mock())

        assert mock_send_refresh.call_count == 2
        mock_sleep.assert_called_once_with(REFRESH_RETRY_DELAY_SECONDS)

    def test_two_failures_are_non_fatal(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")
        mock_send_refresh.side_effect = None

        # Must not raise.
        _ensure(make_task_run_mock())

        assert mock_send_refresh.call_count == 2
        # Cache stays empty so the next follow-up retries the dispatch.
        assert cache.get(_mcp_token_issued_cache_key("run-1", 42)) is None
        assert cache.get(_sandbox_identity_cache_key("run-1", "mcp")) is None

    def test_token_mint_failure_is_non_fatal_and_skips_send(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        mock_oauth.side_effect = RuntimeError("oauth service down")

        _ensure(make_task_run_mock())

        mock_ph_configs.assert_not_called()
        mock_user_configs.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_skips_send_when_no_mcp_configs_resolved(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_ph_configs.return_value = []

        _ensure(make_task_run_mock())

        mock_send_refresh.assert_not_called()

    def test_user_mcp_configs_skipped_when_no_actor(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        _ensure(make_task_run_mock(created_by_id=None), actor_id=None)

        mock_user_configs.assert_not_called()
        mock_send_refresh.assert_called_once()

    def test_scopes_propagate_to_oauth_and_configs(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        _ensure(make_task_run_mock(), scopes="full")

        mock_oauth.assert_called_once_with(mock_oauth.call_args.args[0], None, scopes="full")
        mock_ph_configs.assert_called_once_with(
            token="fresh-token", project_id=7, scopes="full", interaction_origin=None, task_id="task-1"
        )


@patch("products.tasks.backend.temporal.process_task.sandbox_identity.time.sleep")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.send_refresh_session")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_user_mcp_server_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_sandbox_ph_mcp_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.create_oauth_access_token_for_run")
class TestMcpRefreshIntervalGate:
    """Refreshes within MCP_TOKEN_REFRESH_INTERVAL_SECONDS of a previous
    successful issuance for the same actor must be skipped without minting a
    new token or contacting the sandbox."""

    def test_skipped_when_token_recently_issued(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        mark_mcp_token_issued("run-1", 42)

        _ensure(make_task_run_mock())

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_marks_after_successful_refresh(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        _ensure(make_task_run_mock())

        # Cache entries now exist → next refresh for this actor within the
        # interval is gated, and the session identity is recorded.
        assert cache.get(_mcp_token_issued_cache_key("run-1", 42)) is True
        assert cache.get(_sandbox_identity_cache_key("run-1", "mcp")) == 42

    def test_marks_after_successful_retry(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_send_refresh.side_effect = [
            CommandResult(success=False, status_code=502, error="transient"),
            CommandResult(success=True, status_code=200),
        ]

        _ensure(make_task_run_mock())

        assert cache.get(_mcp_token_issued_cache_key("run-1", 42)) is True


@patch("products.tasks.backend.temporal.process_task.sandbox_identity.send_refresh_session")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_user_mcp_server_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.get_sandbox_ph_mcp_configs")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.create_oauth_access_token_for_run")
class TestMcpIdentityTransitionGate:
    """An actor transition (run-state actor differs from the identity last
    pushed to the sandbox) must bypass the freshness window and rebind the
    session; the marks are keyed per sandbox so a replacement sandbox starts
    unmarked."""

    def test_actor_change_bypasses_freshness_window(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # The creator's token is fresh and the session is bound to them…
        mark_mcp_token_issued("run-1", 42)
        mark_sandbox_identity("run-1", "mcp", 42)

        # …but the next message comes from a different actor.
        _ensure(make_task_run_mock(), actor_id=99)

        mock_send_refresh.assert_called_once()
        assert cache.get(_sandbox_identity_cache_key("run-1", "mcp")) == 99
        assert cache.get(_mcp_token_issued_cache_key("run-1", 99)) is True

    def test_switch_back_to_creator_refreshes_despite_fresh_window(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # The creator's window is still warm, but the session was last bound
        # to another user — the creator speaking again is a transition.
        mark_mcp_token_issued("run-1", 42)
        mark_sandbox_identity("run-1", "mcp", 99)

        _ensure(make_task_run_mock(), actor_id=42)

        mock_send_refresh.assert_called_once()
        assert cache.get(_sandbox_identity_cache_key("run-1", "mcp")) == 42

    def test_same_actor_within_window_is_skipped(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mark_mcp_token_issued("run-1", 99)
        mark_sandbox_identity("run-1", "mcp", 99)

        _ensure(make_task_run_mock(), actor_id=99)

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_replacement_sandbox_starts_unmarked(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_mcp_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # Marks recorded against the run id (legacy scope) must not gate a run
        # whose state now points at a concrete sandbox.
        mark_mcp_token_issued("run-1", 42)
        mark_sandbox_identity("run-1", "mcp", 42)

        _ensure(make_task_run_mock(state={"sandbox_id": "sb-2"}), actor_id=42)

        mock_send_refresh.assert_called_once()
        assert cache.get(_mcp_token_issued_cache_key("sb-2", 42)) is True
        assert cache.get(_sandbox_identity_cache_key("sb-2", "mcp")) == 42


@patch("products.tasks.backend.temporal.process_task.sandbox_identity.notify_sandbox_credentials_refreshed")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.GitHubSandboxCredential")
@patch("products.tasks.backend.temporal.process_task.sandbox_identity.Sandbox")
class TestGithubIdentityTransitionGate:
    """The GitHub surface rebinds on actor transitions only — token TTL
    between messages is owned by the credential-refresh loop."""

    def _quiet_mcp(self, user_id: int, scope: str = "run-1") -> None:
        """Pre-mark the MCP surface so `ensure_sandbox_identity` exercises only
        the GitHub gate (no oauth/config mocks needed)."""
        mark_mcp_token_issued(scope, user_id)
        mark_sandbox_identity(scope, "mcp", user_id)

    def _arm_refresh(self, mock_credential_cls, refreshed: bool = True):
        mock_credential_cls.return_value.refresh.return_value = CredentialRefreshOutcome(
            "github", refreshed=refreshed, next_refresh_seconds=60
        )

    def test_actor_transition_rebinds_credentials(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        self._arm_refresh(mock_credential_cls)
        mock_notify.return_value = CommandResult(success=True, status_code=200)
        self._quiet_mcp(99, scope="sb-2")
        mark_sandbox_identity("sb-2", "github", 42)
        state = {"sandbox_id": "sb-2", "pr_authorship_mode": "user"}
        task_run = make_task_run_mock(state=state)

        _ensure(task_run, actor_id=99, auth_token="jwt", processing_context=_make_processing_context())

        mock_sandbox_cls.get_by_id.assert_called_once_with("sb-2")
        refresh_call = mock_credential_cls.return_value.refresh.call_args
        live_ctx = refresh_call.args[1]
        assert live_ctx.state == state  # boot snapshot replaced with live run state
        mock_notify.assert_called_once_with(task_run, ["github"], auth_token="jwt")
        assert cache.get(_sandbox_identity_cache_key("sb-2", "github")) == 99

    def test_same_actor_does_not_touch_sandbox(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        self._quiet_mcp(99)
        mark_sandbox_identity("run-1", "github", 99)

        _ensure(
            make_task_run_mock(state={"sandbox_id": "run-1"}),
            actor_id=99,
            processing_context=_make_processing_context(),
        )

        mock_sandbox_cls.get_by_id.assert_not_called()
        mock_notify.assert_not_called()

    def test_skipped_without_processing_context(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        self._quiet_mcp(99)
        mark_sandbox_identity("run-1", "github", 42)

        _ensure(make_task_run_mock(), actor_id=99, processing_context=None)

        mock_sandbox_cls.get_by_id.assert_not_called()

    def test_skipped_without_github_credentials(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        self._quiet_mcp(99)
        mark_sandbox_identity("run-1", "github", 42)
        context = _make_processing_context(github_integration_id=None)

        _ensure(make_task_run_mock(), actor_id=99, processing_context=context)

        mock_sandbox_cls.get_by_id.assert_not_called()

    def test_rebind_failure_leaves_identity_unmarked_for_retry(
        self, mock_sandbox_cls, mock_credential_cls, mock_notify
    ):
        mock_credential_cls.return_value.refresh.side_effect = RuntimeError("sandbox unreachable")
        self._quiet_mcp(99, scope="sb-2")
        mark_sandbox_identity("sb-2", "github", 42)

        _ensure(
            make_task_run_mock(state={"sandbox_id": "sb-2"}),
            actor_id=99,
            processing_context=_make_processing_context(),
        )

        assert cache.get(_sandbox_identity_cache_key("sb-2", "github")) == 42
        mock_notify.assert_not_called()

    def test_missing_sandbox_id_leaves_identity_unmarked(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        self._quiet_mcp(99)
        mark_sandbox_identity("run-1", "github", 42)

        _ensure(make_task_run_mock(state=None), actor_id=99, processing_context=_make_processing_context())

        assert cache.get(_sandbox_identity_cache_key("run-1", "github")) == 42
        mock_sandbox_cls.get_by_id.assert_not_called()

    def test_unrefreshable_credential_marks_without_notify(self, mock_sandbox_cls, mock_credential_cls, mock_notify):
        # e.g. a caller-token run: nothing we manage, so nothing can diverge —
        # mark to avoid re-probing the sandbox on every message.
        self._arm_refresh(mock_credential_cls, refreshed=False)
        self._quiet_mcp(99, scope="sb-2")
        mark_sandbox_identity("sb-2", "github", 42)

        _ensure(
            make_task_run_mock(state={"sandbox_id": "sb-2"}),
            actor_id=99,
            processing_context=_make_processing_context(),
        )

        assert cache.get(_sandbox_identity_cache_key("sb-2", "github")) == 99
        mock_notify.assert_not_called()
