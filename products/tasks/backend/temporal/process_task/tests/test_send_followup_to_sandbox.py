import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from temporalio.exceptions import ApplicationError

from posthog.models.user_integration import ReauthorizationRequired

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    DENIED_PERMISSION_STOP_MESSAGE,
    REFRESH_RETRY_DELAY_SECONDS,
    SANDBOX_STOPPED_MESSAGE,
    SEND_FOLLOWUP_MAX_ATTEMPTS,
    STEER_DECLINED_OUTCOME,
    LiveSandboxLookup,
    SandboxRebindFailure,
    SendFollowupToSandboxInput,
    _refresh_sandbox_github,
    _refresh_sandbox_mcp,
    _resolve_peer_credential_actor,
    send_followup_to_sandbox,
)
from products.tasks.backend.temporal.process_task.utils import (
    McpServerConfig,
    PrAuthorshipMode,
    _sandbox_identity_cache_key,
    get_sandbox_github_identity_user,
    get_sandbox_mcp_session_user,
    mark_sandbox_github_identity,
    mark_sandbox_mcp_session,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """Ensure each test starts with no recorded session bindings so the
    refresh gate doesn't carry state between tests."""
    cache.clear()
    yield
    cache.clear()


def _make_mcp_config(name: str = "posthog", token: str = "tok") -> McpServerConfig:
    return McpServerConfig(
        type="http",
        name=name,
        url="https://mcp.posthog.com/mcp",
        headers=[{"name": "Authorization", "value": f"Bearer {token}"}],
    )


def _make_task_run_mock(team_id: int = 7, created_by_id: int | None = 42, state: dict | None = None) -> MagicMock:
    task = MagicMock()
    task.created_by_id = created_by_id
    task.team_id = team_id
    task.internal = False
    task.origin_product = "user_created"
    task.mcp_builtin_agent_key = None
    task.mcp_credential_owner_id = None
    task.mcp_gateway_server_allowlist = None
    if created_by_id is not None:
        task.created_by = MagicMock(id=created_by_id, distinct_id=f"user-{created_by_id}")
    else:
        task.created_by = None
    task_run = MagicMock()
    task_run.id = "run-1"
    task_run.team_id = team_id
    task_run.task = task
    task_run.task_id = "task-1"
    # Default to None so `(task_run.state or {}).get(...)` returns None cleanly.
    # MagicMock auto-attributes would otherwise return further MagicMock objects
    # and leak into kwargs passed to `get_sandbox_ph_mcp_configs`.
    task_run.state = state
    task_run.imported_mcp_servers = None
    return task_run


def _refresh(task_run, actor_id: int | None = 42, scopes="read_only", auth_token=None) -> None:
    actor = MagicMock(id=actor_id) if actor_id is not None else None
    _refresh_sandbox_mcp(task_run, scopes, auth_token, actor_user=actor, state=task_run.state)


def _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh):
    mock_oauth.return_value = "fresh-token"
    mock_ph_configs.return_value = [_make_mcp_config(token="fresh-token")]
    mock_user_configs.return_value = []
    mock_send_refresh.return_value = CommandResult(success=True, status_code=200)


@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.time.sleep")
@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_refresh_session")
@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_user_mcp_server_configs")
@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_ph_mcp_configs")
@patch(
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_oauth_access_token_for_run"
)
class TestRefreshSandboxMcp:
    def test_success_path_uses_persisted_task_agent_marker(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        task_run = _make_task_run_mock(state={"mcp_builtin_agent_key": "scout"})
        task_run.task.internal = True
        task_run.task.origin_product = "support_reply"
        task_run.task.mcp_builtin_agent_key = "support"
        task_run.task.mcp_credential_owner_id = 99
        task_run.task.mcp_gateway_server_allowlist = ["srv-9"]
        _refresh(task_run, auth_token="jwt")

        mock_oauth.assert_called_once_with(task_run.task, task_run.state, scopes="read_only")
        mock_ph_configs.assert_called_once_with(
            token="fresh-token", project_id=7, scopes="read_only", interaction_origin=None, task_id="task-1"
        )
        mock_user_configs.assert_called_once_with(
            token="fresh-token",
            team_id=7,
            user_id=42,
            include_personal=False,
            interaction_origin=None,
            allowed_installation_ids=None,
            origin_product="support_reply",
            task_agent_key="support",
            credential_owner_id=99,
            allowed_gateway_server_ids=["srv-9"],
        )
        mock_send_refresh.assert_called_once()
        _, kwargs = mock_send_refresh.call_args
        assert kwargs["auth_token"] == "jwt"
        assert mock_send_refresh.call_args.args[0] is task_run
        # mcpServers payload is serialized McpServerConfig shape
        mcp_servers = mock_send_refresh.call_args.args[1]
        assert mcp_servers == [_make_mcp_config(token="fresh-token").to_dict()]

    def test_refresh_keeps_imported_mcp_servers(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        """refresh_session replaces the session's server list wholesale; without
        this, the run's client-imported servers vanish at the first token refresh."""
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config(token="fresh-token")]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=True, status_code=200)

        task_run = _make_task_run_mock()
        task_run.imported_mcp_servers = [
            {
                "type": "http",
                "name": "grafana",
                "url": "https://mcp.grafana.example.com/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer x"}],
            },
            # collides with the PostHog MCP config: existing servers win
            {"type": "http", "name": "posthog", "url": "https://shadow.example.com/mcp", "headers": []},
        ]

        _refresh(task_run, auth_token="jwt")

        mcp_servers = mock_send_refresh.call_args.args[1]
        assert [server["name"] for server in mcp_servers] == ["posthog", "grafana"]
        assert mcp_servers[1] == {
            "type": "http",
            "name": "grafana",
            "url": "https://mcp.grafana.example.com/mcp",
            "headers": [{"name": "Authorization", "value": "Bearer x"}],
        }

    def test_retries_once_on_first_failure(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, mock_sleep
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_send_refresh.side_effect = [
            CommandResult(success=False, status_code=502, error="transient", retryable=True),
            CommandResult(success=True, status_code=200),
        ]

        _refresh(_make_task_run_mock())

        assert mock_send_refresh.call_count == 2
        mock_sleep.assert_called_once_with(REFRESH_RETRY_DELAY_SECONDS)
        # Marked on the successful retry → next same-actor refresh is gated.
        assert get_sandbox_mcp_session_user("run-1") == 42

    def test_two_failures_are_non_fatal_and_unmarked(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")

        # Must not raise.
        _refresh(_make_task_run_mock())

        assert mock_send_refresh.call_count == 2
        # Cache stays empty so the next follow-up retries the dispatch.
        assert get_sandbox_mcp_session_user("run-1") is None

    def test_token_mint_failure_is_non_fatal_and_skips_send(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        mock_oauth.side_effect = RuntimeError("oauth service down")

        _refresh(_make_task_run_mock())

        mock_ph_configs.assert_not_called()
        mock_user_configs.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_skips_send_when_no_mcp_configs_resolved(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        mock_ph_configs.return_value = []

        _refresh(_make_task_run_mock())

        mock_send_refresh.assert_not_called()
        # Marked anyway: with no session to rebind, don't re-mint per message.
        assert get_sandbox_mcp_session_user("run-1") == 42

    def test_no_actor_skips_entirely(self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep):
        # Creator-less non-Slack run: the mint is guaranteed to fail, so the
        # refresh must not attempt (and warn) on every message.
        _refresh(_make_task_run_mock(created_by_id=None), actor_id=None)

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_scopes_propagate_to_oauth_and_configs(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        _refresh(_make_task_run_mock(), scopes="full")

        mock_oauth.assert_called_once_with(mock_oauth.call_args.args[0], None, scopes="full")
        mock_ph_configs.assert_called_once_with(
            token="fresh-token", project_id=7, scopes="full", interaction_origin=None, task_id="task-1"
        )

    def test_transition_refresh_failure_reports_unsafe(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        # A prior actor holds the session and the new actor's refresh fails both
        # attempts: the rebind never happened, so the gate reports unsafe (the
        # caller fails the follow-up closed) and the previous binding is left as is.
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")
        mark_sandbox_mcp_session("run-1", 99)

        actor = MagicMock(id=42)
        failure = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert failure == SandboxRebindFailure.REFRESH_SESSION_FAILED
        assert get_sandbox_mcp_session_user("run-1") == 99

    def test_unknown_binding_refresh_failure_fails_closed(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep
    ):
        # No marker for this scope: the marker self-expires before the OAuth
        # session does, so an absent one may hide the previous actor's still-live
        # session rather than a fresh sandbox. When the refresh can't confirm the
        # rebind, the gate reports unsafe so the caller fails closed.
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")

        actor = MagicMock(id=42)
        failure = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert failure == SandboxRebindFailure.REFRESH_SESSION_FAILED


@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_refresh_session")
@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_user_mcp_server_configs")
@patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_ph_mcp_configs")
@patch(
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_oauth_access_token_for_run"
)
class TestSessionIdentityGate:
    """One cache entry per sandbox records who the live session was last bound
    to and expires with the freshness window — so a same-actor repeat skips,
    while a transition, an expired entry, or a replacement sandbox refreshes."""

    def test_same_actor_within_window_is_skipped(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mark_sandbox_mcp_session("run-1", 42)

        _refresh(_make_task_run_mock(), actor_id=42)

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()

    def test_built_in_agent_same_actor_refreshes_to_pick_up_new_grants(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        task_run = _make_task_run_mock()
        task_run.task.internal = True
        task_run.task.origin_product = "support_reply"
        task_run.task.mcp_builtin_agent_key = "support"
        mark_sandbox_mcp_session("run-1", 42)

        _refresh(task_run, actor_id=42)

        mock_oauth.assert_called_once()
        mock_user_configs.assert_called_once()
        mock_send_refresh.assert_called_once()

    def test_actor_change_bypasses_freshness_window(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # The session is freshly bound to the creator…
        mark_sandbox_mcp_session("run-1", 42)

        # …but the next message comes from a different actor.
        _refresh(_make_task_run_mock(), actor_id=99)

        mock_send_refresh.assert_called_once()
        assert get_sandbox_mcp_session_user("run-1") == 99

    def test_switch_back_refreshes(self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # The session was last bound to another user — the creator speaking
        # again is a transition even though they spoke recently.
        mark_sandbox_mcp_session("run-1", 99)

        _refresh(_make_task_run_mock(), actor_id=42)

        mock_send_refresh.assert_called_once()
        assert get_sandbox_mcp_session_user("run-1") == 42

    def test_unknown_binding_refreshes(self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh):
        # No entry (expired window, cache eviction, pre-rollout sandbox):
        # fail safe by refreshing rather than guessing who the session holds.
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        _refresh(_make_task_run_mock(), actor_id=42)

        mock_send_refresh.assert_called_once()
        assert get_sandbox_mcp_session_user("run-1") == 42

    def test_replacement_sandbox_starts_unmarked(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)
        # A binding recorded against the run id (legacy scope) must not gate a
        # run whose state now points at a concrete sandbox.
        mark_sandbox_mcp_session("run-1", 42)

        _refresh(_make_task_run_mock(state={"sandbox_id": "sb-2"}), actor_id=42)

        mock_send_refresh.assert_called_once()
        assert get_sandbox_mcp_session_user("sb-2") == 42
        assert cache.get(_sandbox_identity_cache_key("mcp-session", "run-1")) == 42  # untouched

    def test_transition_with_no_configs_fails_closed(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        # The prior actor holds the live session and the new actor resolves no MCP
        # configs, so an empty-list refresh can neither rebind nor tear it down.
        # Reject the turn rather than run it against the prior actor's session.
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = []
        mock_user_configs.return_value = []
        mark_sandbox_mcp_session("run-1", 99)

        actor = MagicMock(id=42)
        failure = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert failure == SandboxRebindFailure.NO_CONFIGS_ON_TRANSITION  # fail closed: prior session may still be live
        mock_send_refresh.assert_not_called()
        assert get_sandbox_mcp_session_user("run-1") == 99  # binding unchanged

    def test_unknown_binding_with_no_configs_runs(
        self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        # No recorded prior actor and no MCP configs to establish a session: there
        # is nothing to leak, so the turn runs rather than being blocked just
        # because MCP is unavailable. The binding is recorded for later transitions.
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = []
        mock_user_configs.return_value = []

        actor = MagicMock(id=42)
        failure = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert failure is None
        mock_send_refresh.assert_not_called()
        assert get_sandbox_mcp_session_user("run-1") == 42  # binding recorded


_GH_MODULE = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox"


@patch(f"{_GH_MODULE}.upgrade_run_to_user_authorship", return_value=None)
@patch(f"{_GH_MODULE}.clear_github_credentials_from_sandbox")
@patch(f"{_GH_MODULE}.apply_github_credentials_to_sandbox")
@patch(f"{_GH_MODULE}.get_sandbox_github_token")
@patch(f"{_GH_MODULE}._resolve_live_sandbox")
@patch(f"{_GH_MODULE}.get_pr_authorship_mode")
class TestSandboxGithubIdentityGate:
    """Every turn re-establishes the sandbox's GitHub credentials for the acting user:
    their token when they have access, otherwise a logout so no previous actor's
    identity survives."""

    def test_same_actor_is_re_established_not_skipped(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # The actor can connect or disconnect between messages, and a resume or snapshot restore
        # can drop the token, so an unchanged actor is not evidence the sandbox still holds it.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = "ghu_token"
        mock_apply.return_value = True
        mark_sandbox_github_identity("run-1", 42)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_called_once()
        assert mock_apply.call_args.args[2] == "ghu_token"
        mock_clear.assert_not_called()

    def test_revoked_connection_logs_the_sandbox_out_on_the_same_actor(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # Same actor as last turn, but their install no longer mints: the cheap skip must not
        # leave their token live in the sandbox until the refresh loop next runs.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = None
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 42)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_clear.assert_called_once()
        mock_apply.assert_not_called()

    def test_a_self_revoked_connection_that_cannot_clear_fails_closed(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # Same actor, their own connection revoked, and the clear cannot be confirmed. Deleting the
        # integration does not revoke the token GitHub already issued, so proceeding could leave it
        # usable in the sandbox after the user disconnected.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = None
        mock_clear.return_value = False
        mark_sandbox_github_identity("run-1", 42)

        assert (
            _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None)
            == SandboxRebindFailure.LOGOUT_UNCONFIRMED
        )

    def test_a_transition_that_cannot_clear_still_fails_closed(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # A different actor inheriting the previous one's live token is the case the gate exists for.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = None
        mock_clear.return_value = False
        mark_sandbox_github_identity("run-1", 99)

        assert (
            _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None)
            == SandboxRebindFailure.LOGOUT_UNCONFIRMED
        )

    def test_reconnecting_after_a_logout_rebinds_the_actor(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # Revoke, then reconnect. The logout leaves the sandbox marked against this actor, and the
        # reconnect must still be picked up — no marker check may short-circuit the rebind.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_clear.return_value = True
        mock_get_token.return_value = None
        mark_sandbox_github_identity("run-1", 42)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        assert get_sandbox_github_identity_user("run-1") == 42

        mock_get_token.return_value = "ghu_reconnected"
        mock_apply.return_value = True

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_called_once()
        assert mock_apply.call_args.args[2] == "ghu_reconnected"

    def test_bot_authorship_skips(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # BOT runs share a single installation token, so every actor is already
        # the same GitHub identity — nothing to rebind.
        mock_authorship.return_value = PrAuthorshipMode.BOT
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_get_token.assert_not_called()
        mock_apply.assert_not_called()
        mock_clear.assert_not_called()

    def test_transition_with_access_rebinds(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = "ghu_newtoken"
        mock_apply.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_called_once()
        assert mock_apply.call_args.args[2] == "ghu_newtoken"
        mock_clear.assert_not_called()
        assert get_sandbox_github_identity_user("run-1") == 42

    def test_transition_without_access_logs_out(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.side_effect = ReauthorizationRequired("no repo access")
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_not_called()
        mock_clear.assert_called_once()
        # Still marked: owner-scoped refreshes read this to know the sandbox is bound away from the
        # run owner, and must not inject the owner's token into this actor's session.
        assert get_sandbox_github_identity_user("run-1") == 42

    def test_apply_failure_falls_back_to_logout(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = "ghu_newtoken"
        mock_apply.side_effect = RuntimeError("write failed")
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_called_once()
        mock_clear.assert_called_once()  # fell through to logout so no stale creds remain

    def test_apply_incomplete_falls_back_to_logout(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # A partial credential write (one location refused, no exception) is not a confirmed
        # rebind: the prior actor's token may still be live in the other location, so log out
        # rather than record the new actor.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.return_value = "ghu_newtoken"
        mock_apply.return_value = False
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_called_once()
        mock_clear.assert_called_once()
        # Still marked: owner-scoped refreshes read this to know the sandbox is bound away from the
        # run owner, and must not inject the owner's token into this actor's session.
        assert get_sandbox_github_identity_user("run-1") == 42  # logout confirmed, bound to new actor

    @pytest.mark.parametrize(
        "lookup,expected_reason",
        [
            (LiveSandboxLookup(), SandboxRebindFailure.NO_SANDBOX_HANDLE),
            (LiveSandboxLookup(stopped=True), SandboxRebindFailure.SANDBOX_NOT_RUNNING),
        ],
    )
    def test_no_sandbox_handle_fails_closed(
        self,
        mock_authorship,
        mock_resolve,
        mock_get_token,
        mock_apply,
        mock_clear,
        mock_upgrade,
        lookup,
        expected_reason,
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = lookup
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) == expected_reason
        mock_get_token.assert_not_called()
        mock_apply.assert_not_called()
        mock_clear.assert_not_called()
        assert get_sandbox_github_identity_user("run-1") == 99  # binding unchanged

    def test_logout_failure_fails_closed(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # New actor has no access and the sandbox can't even be cleared — the
        # previous actor's creds may still be live, so fail closed.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.side_effect = ReauthorizationRequired("no repo access")
        mock_clear.return_value = False
        mark_sandbox_github_identity("run-1", 99)

        assert (
            _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None)
            == SandboxRebindFailure.LOGOUT_UNCONFIRMED
        )
        assert get_sandbox_github_identity_user("run-1") == 99  # binding unchanged

    def test_logout_exception_fails_closed(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # The clear itself raising (sandbox stopped/timed out between is_running and here) must
        # fail closed, not escape uncontrolled.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.side_effect = ReauthorizationRequired("no repo access")
        mock_clear.side_effect = RuntimeError("sandbox stopped")
        mark_sandbox_github_identity("run-1", 99)

        assert (
            _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None)
            == SandboxRebindFailure.LOGOUT_ERRORED
        )
        assert get_sandbox_github_identity_user("run-1") == 99  # binding unchanged

    def test_credential_unavailable_logs_out(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear, mock_upgrade
    ):
        # A disconnected/deleted integration mid-run yields no usable credential (not just
        # ReauthorizationRequired): log out rather than let the exception escape.
        from products.tasks.backend.exceptions import CredentialUnavailableError

        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = LiveSandboxLookup(sandbox=MagicMock())
        mock_get_token.side_effect = CredentialUnavailableError("integration disconnected", {})
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is None
        mock_apply.assert_not_called()
        mock_clear.assert_called_once()
        # Still marked: owner-scoped refreshes read this to know the sandbox is bound away from the
        # run owner, and must not inject the owner's token into this actor's session.
        assert get_sandbox_github_identity_user("run-1") == 42


class TestSendFollowupActivityRefreshOrdering:
    """Refresh call must precede user_message, and the activity must succeed
    when refresh fails (non-fatal) as long as user_message succeeds."""

    @pytest.fixture
    def _patches(self):
        """Patch everything the activity touches at module boundary."""
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun"
            ) as mock_task_run_cls,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token"
            ) as mock_conn_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp",
                return_value=None,
            ) as mock_refresh,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_github",
                return_value=None,
            ) as mock_refresh_github,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message"
            ) as mock_user_msg,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_turn_complete"
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_error_and_complete"
            ),
        ):
            task_run = _make_task_run_mock()
            task_run.task.created_by = MagicMock(id=42, distinct_id="u42")
            mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
            mock_conn_token.return_value = "jwt"

            yield {
                "task_run": task_run,
                "task_run_cls": mock_task_run_cls,
                "refresh": mock_refresh,
                "refresh_github": mock_refresh_github,
                "user_msg": mock_user_msg,
                "conn_token": mock_conn_token,
            }

    def test_refresh_called_before_user_message(self, _patches):
        call_order: list[str] = []

        def _record_refresh(*a, **kw):
            call_order.append("refresh")
            return None  # refresh confirmed the session is safe; gate lets the turn proceed

        def _record_user_msg(*a, **kw):
            call_order.append("user_message")
            return CommandResult(success=True, status_code=200, data={"result": {"stopReason": "end_turn"}})

        _patches["refresh"].side_effect = _record_refresh
        _patches["user_msg"].side_effect = _record_user_msg

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", posthog_mcp_scopes="full"))

        assert call_order == ["refresh", "user_message"]

    @pytest.mark.parametrize(
        "gate,reason",
        [("refresh", "refresh_session_failed"), ("refresh_github", "logout_unconfirmed")],
    )
    def test_gate_rejection_names_its_reason_in_the_failure(self, _patches, gate, reason):
        # A fail-closed follow-up raises without delivering, so the reason the gate
        # gave is the only account of why the run stopped.
        _patches[gate].return_value = reason

        with pytest.raises(RuntimeError, match=reason):
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        _patches["user_msg"].assert_not_called()

    def test_a_stopped_sandbox_is_named_before_either_credential_gate_runs(self, _patches):
        _patches["task_run"].state = {"sandbox_id": "sb-1"}
        _patches["refresh"].return_value = SandboxRebindFailure.REFRESH_SESSION_FAILED

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._resolve_live_sandbox",
                return_value=LiveSandboxLookup(stopped=True),
            ),
            pytest.raises(ApplicationError) as excinfo,
        ):
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert str(excinfo.value) == SANDBOX_STOPPED_MESSAGE
        assert excinfo.value.non_retryable
        _patches["refresh"].assert_not_called()
        _patches["user_msg"].assert_not_called()

    def test_stopped_sandbox_says_so_once_instead_of_retrying(self, _patches):
        _patches["refresh_github"].return_value = SandboxRebindFailure.SANDBOX_NOT_RUNNING

        with pytest.raises(ApplicationError) as excinfo:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert str(excinfo.value) == SANDBOX_STOPPED_MESSAGE
        assert excinfo.value.non_retryable
        _patches["user_msg"].assert_not_called()

    def test_scopes_flow_from_input_to_refresh(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", posthog_mcp_scopes="full"))

        _patches["refresh"].assert_called_once()
        args, _kwargs = _patches["refresh"].call_args
        assert args[0] is _patches["task_run"]
        assert args[1] == "full"
        assert args[2] == "jwt"

    def test_payload_actor_pins_resolution_over_run_state(self, _patches):
        # A concurrent follow-up (or permission response) may overwrite the
        # run-state actor between queueing and delivery; the message's own
        # sender must win.
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)
        _patches["task_run"].state = {"interaction_origin": "slack", "slack_actor_user_id": 42}

        with patch(
            "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_task_run_credential_user"
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(id=99)
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", actor_user_id=99))

        resolved_state = mock_resolve.call_args.args[1]
        assert resolved_state["slack_actor_user_id"] == 99

    def test_slack_delivery_stamps_turn_actor(self, _patches):
        # The durable run-state actor must move at turn boundaries: delivery
        # persists this message's sender so between-turn consumers (reply
        # tagging, credential refresh) follow the executing turn.
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)
        _patches["task_run"].state = {"interaction_origin": "slack", "slack_actor_user_id": 42}

        with patch(
            "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_task_run_credential_user"
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(id=99)
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1", message="hi", actor_user_id=99, context={"actor_slack_user_id": "U_BOB"}
                )
            )

        _patches["task_run_cls"].update_state_atomic.assert_any_call(
            _patches["task_run"].id,
            updates={"slack_actor_user_id": 99, "slack_actor_slack_user_id": "U_BOB"},
        )

    def test_non_slack_delivery_does_not_stamp(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", actor_user_id=99))

        _patches["task_run_cls"].update_state_atomic.assert_not_called()

    def test_default_scope_is_read_only(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        args, _kwargs = _patches["refresh"].call_args
        assert args[1] == "read_only"

    def test_steer_from_different_actor_declines_before_using_credentials(self, _patches):
        _patches["task_run"].state = {"sandbox_id": "sandbox-1"}
        _patches["task_run"].task.created_by_id = 42

        outcome = send_followup_to_sandbox(
            SendFollowupToSandboxInput(run_id="run-1", message="hi", actor_user_id=99, steer=True)
        )

        assert outcome == STEER_DECLINED_OUTCOME
        _patches["conn_token"].assert_not_called()
        _patches["refresh"].assert_not_called()
        _patches["user_msg"].assert_not_called()


class TestSendFollowupTurnTimeout:
    """A read timeout (turn_in_flight) means the message was delivered and the
    turn is still running — the activity must not fail the run or write stream
    markers. A 504 *response* leaves delivery unknown and must retry; any other
    delivery failure stays fatal."""

    @pytest.fixture
    def _patches(self):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun"
            ) as mock_task_run_cls,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token"
            ) as mock_conn_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp",
                return_value=None,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_github",
                return_value=None,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message"
            ) as mock_user_msg,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_turn_complete"
            ) as mock_turn_complete,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_error_and_complete"
            ) as mock_error,
        ):
            task_run = _make_task_run_mock()
            task_run.task.created_by = MagicMock(id=42, distinct_id="u42")
            mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
            denial_state: dict[str, object] = {}

            def mutate_state(_run_id, mutator):
                mutator(denial_state)
                return denial_state

            mock_task_run_cls.mutate_state_atomic.side_effect = mutate_state
            mock_conn_token.return_value = "jwt"

            yield {
                "task_run": task_run,
                "task_run_cls": mock_task_run_cls,
                "denial_state": denial_state,
                "user_msg": mock_user_msg,
                "turn_complete": mock_turn_complete,
                "error": mock_error,
            }

    def test_read_timeout_is_non_fatal_and_writes_no_markers(self, _patches):
        # Regression: a turn longer than FOLLOWUP_TIMEOUT_SECONDS used to fail
        # the run and destroy a healthy sandbox mid-work.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox request timed out", retryable=True, turn_in_flight=True
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_retryable_failure_retries_without_sentinel(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=502, error="Connection to sandbox failed", retryable=True
        )

        with pytest.raises(ApplicationError, match="retryable failure") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is False
        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_pi_retryable_failure_writes_sentinel_on_its_only_attempt(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=502, error="Connection to sandbox failed", retryable=True
        )

        with pytest.raises(ApplicationError, match="send_followup failed") as exc_info:
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1",
                    message="hi",
                    message_id="m-1",
                    max_attempts=1,
                )
            )

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        _patches["turn_complete"].assert_not_called()

    def test_retryable_stream_error_final_attempt_writes_actionable_sentinel(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: API Error: Content block not found",
            retryable=True,
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._current_attempt",
                return_value=SEND_FOLLOWUP_MAX_ATTEMPTS,
            ),
            pytest.raises(ApplicationError, match="The model response could not be completed") as exc_info,
        ):
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once_with(
            "run-1",
            "The model response could not be completed. Please retry the task.",
            False,
        )
        _patches["turn_complete"].assert_not_called()

    def test_turn_that_ended_without_a_response_is_redelivered(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )

        with pytest.raises(ApplicationError, match="retryable failure") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is False
        _patches["error"].assert_not_called()

    def test_a_later_steer_race_is_still_redelivered_after_an_earlier_denial(self, _patches):
        _patches["task_run"].state = {}
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )
        _patches["denial_state"].update(
            {
                "slack_permission_rejected": True,
                "slack_permission_rejected_request_id": "req-1",
                "followup_denial_brake_request_id": "req-1",
            }
        )

        with pytest.raises(ApplicationError, match="retryable failure") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is False
        _patches["error"].assert_not_called()

    def test_a_denial_recorded_during_the_turn_is_not_redelivered(self, _patches):
        _patches["task_run"].state = {}
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )
        _patches["denial_state"].update(
            {"slack_permission_rejected": True, "slack_permission_rejected_request_id": "req-1"}
        )

        with pytest.raises(ApplicationError) as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        assert _patches["denial_state"]["followup_denial_brake_request_id"] == "req-1"

    def test_a_denied_turn_tells_the_user_why_it_stopped(self, _patches):
        _patches["task_run"].state = {}
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )
        _patches["denial_state"].update(
            {"slack_permission_rejected": True, "slack_permission_rejected_request_id": "req-1"}
        )

        with pytest.raises(ApplicationError, match="ede_diagnostic") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once_with("run-1", DENIED_PERMISSION_STOP_MESSAGE, False)

    def test_a_steer_never_claims_the_denial_that_ended_its_turn(self, _patches):
        _patches["denial_state"].update(
            {"slack_permission_rejected": True, "slack_permission_rejected_request_id": "req-1"}
        )
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_mcp_session_user",
                return_value=42,
            ),
            pytest.raises(ApplicationError, match="retryable failure") as steer_failure,
        ):
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1", message="wait", message_id="m-steer", actor_user_id=42, steer=True
                )
            )
        with pytest.raises(ApplicationError) as base_failure:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-base"))

        assert steer_failure.value.non_retryable is False
        assert base_failure.value.non_retryable is True
        assert _patches["denial_state"]["followup_denial_brake_request_id"] == "req-1"

    def test_two_deliveries_failing_on_one_denial_only_brake_once(self, _patches):
        # A steer joins the turn the denial ends, so the base delivery and the steer come back
        # on the same diagnostic. Only the racer that claims the denial may brake; the other
        # has to stay retryable or its message is the one that disappears.
        _patches["denial_state"].update(
            {"slack_permission_rejected": True, "slack_permission_rejected_request_id": "req-1"}
        )
        _patches["user_msg"].return_value = CommandResult(
            success=False,
            status_code=200,
            error="Internal error: [ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
            retryable=True,
        )

        verdicts = []
        for message_id in ("m-1", "m-2"):
            with pytest.raises(ApplicationError) as exc_info:
                send_followup_to_sandbox(
                    SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id=message_id)
                )
            verdicts.append(exc_info.value.non_retryable)

        assert verdicts == [True, False]

    def test_response_504_retries_without_sentinel(self, _patches):
        # Regression: a genuine 504 *response* (tunnel gateway timeout,
        # delivery unknown) used to be conflated with the read-timeout case
        # and silently treated as delivered — losing the user's message.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox returned 504", retryable=True
        )

        with pytest.raises(ApplicationError, match="delivery unknown") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is False
        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_response_504_final_attempt_writes_sentinel_and_fails(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox returned 504", retryable=True
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._current_attempt",
                return_value=SEND_FOLLOWUP_MAX_ATTEMPTS,
            ),
            pytest.raises(ApplicationError, match="send_followup failed") as exc_info,
        ):
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        _patches["turn_complete"].assert_not_called()

    def test_duplicate_delivery_skips_markers(self, _patches):
        # A retried attempt whose message the agent-server already accepted
        # must not write a synthetic turn_complete — the turn is still running
        # and the event stream owns its completion.
        _patches["user_msg"].return_value = CommandResult(
            success=True,
            status_code=200,
            data={"result": {"duplicate": True, "stopReason": "duplicate_delivery"}},
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_declined_steer_returns_for_normal_requeue_without_markers(self, _patches):
        _patches["task_run"].state = {"sandbox_id": "sandbox-1"}
        _patches["user_msg"].return_value = CommandResult(
            success=True,
            status_code=200,
            data={"result": {"steered": False, "stopReason": STEER_DECLINED_OUTCOME}},
        )

        with patch(
            "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_mcp_session_user",
            return_value=42,
        ):
            outcome = send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1",
                    message="hi",
                    message_id="m-1",
                    actor_user_id=42,
                    steer=True,
                )
            )

        assert outcome == STEER_DECLINED_OUTCOME
        _patches["user_msg"].assert_called_once()
        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_message_id_forwarded_to_sandbox(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        _, kwargs = _patches["user_msg"].call_args
        assert kwargs["message_id"] == "m-1"


class TestPeerDeliveryMode:
    # Delivery contract, item 2: in peer mode the credential actor can never be
    # derived from message input or task-state overlays, failures never write the
    # recipient's stream sentinels, and the message row carries the outcome.

    _PEER_ID = "7f000000-0000-4000-8000-000000000001"

    def _peer_context(self, peer_id: str | None = None) -> dict:
        return {"kind": "agent_peer_message", "peer_message_id": peer_id or self._PEER_ID}

    @pytest.fixture
    def _patches(self):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun"
            ) as mock_task_run_cls,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token"
            ) as mock_conn_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp"
            ) as mock_refresh_mcp,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_github",
                return_value=None,
            ) as mock_refresh_github,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message"
            ) as mock_user_msg,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_turn_complete"
            ) as mock_turn_complete,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_error_and_complete"
            ) as mock_error,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_task_run_credential_user"
            ) as mock_resolve_actor,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_mcp_session_user"
            ) as mock_bound_user,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._resolve_peer_credential_actor"
            ) as mock_bound_actor,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.mark_peer_message_outcome"
            ) as mock_mark,
        ):
            task_run = _make_task_run_mock()
            mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
            mock_task_run_cls.DoesNotExist = Exception
            mock_conn_token.return_value = "jwt"
            mock_refresh_mcp.return_value = None
            mock_bound_actor.return_value = (None, "the sandbox's bound credential identity is unconfirmed")
            mock_bound_user.return_value = None

            yield {
                "task_run": task_run,
                "conn_token": mock_conn_token,
                "refresh_mcp": mock_refresh_mcp,
                "refresh_github": mock_refresh_github,
                "user_msg": mock_user_msg,
                "turn_complete": mock_turn_complete,
                "error": mock_error,
                "resolve_actor": mock_resolve_actor,
                "bound_actor": mock_bound_actor,
                "mark": mock_mark,
            }

    def test_sender_actor_cannot_influence_credentials_only_bound_identity_can(self, _patches):
        # A spoofed/compromised sender sets actor_user_id=99 on a peer message; the
        # run-state resolver must never run, and every credential call must key on
        # the sandbox's own bound identity instead.
        bound = MagicMock(id=42, distinct_id="u42")
        _patches["bound_actor"].return_value = (bound, "")
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(
            SendFollowupToSandboxInput(
                run_id="run-1",
                message="peer ping",
                message_id="m-1",
                actor_user_id=99,
                context=self._peer_context(),
            )
        )

        _patches["resolve_actor"].assert_not_called()
        assert _patches["conn_token"].call_args.kwargs["user_id"] == 42
        assert _patches["refresh_mcp"].call_args.kwargs["actor_user"] is bound
        assert _patches["refresh_github"].call_args.args[1] is bound
        assert _patches["user_msg"].call_args.kwargs["steer"] is False
        _patches["mark"].assert_called_once()
        assert _patches["mark"].call_args.args == (self._PEER_ID, "delivered")

    def test_unconfirmed_identity_fails_closed_without_delivering(self, _patches):
        # An expired binding marker can hide another actor's still-live session
        # (the marker lives half the token lifetime), so an unconfirmed identity
        # must never run a peer turn on the sandbox's residual credentials.
        with pytest.raises(ApplicationError) as excinfo:
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1", message="peer ping", message_id="m-1", context=self._peer_context()
                )
            )

        assert excinfo.value.non_retryable is True
        _patches["user_msg"].assert_not_called()
        _patches["conn_token"].assert_not_called()
        _patches["error"].assert_not_called()
        assert _patches["mark"].call_args.args == (self._PEER_ID, "delivery_failed")
        assert _patches["mark"].call_args.kwargs["failure_phase"] == "credential_identity"

    @pytest.mark.parametrize("refresh_key", ["refresh_mcp", "refresh_github"])
    def test_refresh_failure_marks_row_without_stream_sentinels(self, _patches, refresh_key):
        _patches["bound_actor"].return_value = (MagicMock(id=42, distinct_id="u42"), "")
        _patches[refresh_key].return_value = SandboxRebindFailure.REFRESH_SESSION_FAILED

        with pytest.raises(ApplicationError) as excinfo:
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1", message="peer ping", message_id="m-1", context=self._peer_context()
                )
            )

        assert excinfo.value.non_retryable is True
        _patches["error"].assert_not_called()
        _patches["user_msg"].assert_not_called()
        assert _patches["mark"].call_args.args == (self._PEER_ID, "delivery_failed")
        assert _patches["mark"].call_args.kwargs["failure_phase"] == "credential_refresh"

    def test_final_delivery_failure_marks_row_without_stream_sentinels(self, _patches):
        _patches["bound_actor"].return_value = (MagicMock(id=42, distinct_id="u42"), "")
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=500, error="agent exploded", retryable=False
        )

        with pytest.raises(ApplicationError) as excinfo:
            send_followup_to_sandbox(
                SendFollowupToSandboxInput(
                    run_id="run-1", message="peer ping", message_id="m-1", context=self._peer_context()
                )
            )

        assert excinfo.value.non_retryable is True
        _patches["error"].assert_not_called()
        assert _patches["mark"].call_args.args == (self._PEER_ID, "delivery_failed")
        assert _patches["mark"].call_args.kwargs["failure_phase"] == "sandbox_delivery"

    def test_duplicate_delivery_marks_row_delivered_without_turn_complete(self, _patches):
        # duplicate:true means a prior attempt already delivered this message_id,
        # so the audit outcome is delivered; that attempt owns the turn bookkeeping.
        _patches["bound_actor"].return_value = (MagicMock(id=42, distinct_id="u42"), "")
        _patches["user_msg"].return_value = CommandResult(
            success=True, status_code=200, data={"result": {"duplicate": True}}
        )

        send_followup_to_sandbox(
            SendFollowupToSandboxInput(
                run_id="run-1", message="peer ping", message_id="m-1", context=self._peer_context()
            )
        )

        assert _patches["mark"].call_args.args == (self._PEER_ID, "delivered")
        _patches["turn_complete"].assert_not_called()

    def test_malformed_peer_context_falls_back_to_user_path(self, _patches):
        # A context that claims the peer kind but fails strict id validation must
        # NOT unlock peer mode — the message runs as an ordinary follow-up, whose
        # path resolves the actor from run state.
        _patches["resolve_actor"].return_value = MagicMock(id=42, distinct_id="u42")
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(
            SendFollowupToSandboxInput(
                run_id="run-1",
                message="hi",
                message_id="m-1",
                context={"kind": "agent_peer_message", "peer_message_id": "spoof-not-a-uuid"},
            )
        )

        _patches["resolve_actor"].assert_called_once()
        _patches["mark"].assert_not_called()


class TestResolvePeerCredentialActor:
    # The fail-closed identity gate: a peer turn may only ever execute as the task
    # creator, confirmed bound and still holding active team access. Residual or
    # foreign credentials must never run a turn the sender authorized as creator.

    def _resolve(self, bound_user_id, has_team_access=True, created_by_id=42):
        task_run = _make_task_run_mock(created_by_id=created_by_id)
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_mcp_session_user",
                return_value=bound_user_id,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.user_has_current_team_access",
                return_value=has_team_access,
            ) as mock_access,
        ):
            actor, reason = _resolve_peer_credential_actor(task_run)
        return task_run, actor, reason, mock_access

    @pytest.mark.parametrize(
        "bound_user_id,has_team_access,expected_reason_fragment",
        [
            (None, True, "unconfirmed"),
            (99, True, "different user"),
            (42, False, "no longer has active access"),
        ],
    )
    def test_fails_closed(self, bound_user_id, has_team_access, expected_reason_fragment):
        _, actor, reason, _ = self._resolve(bound_user_id, has_team_access=has_team_access)
        assert actor is None
        assert expected_reason_fragment in reason

    def test_creatorless_task_fails_closed_even_when_bound(self):
        _, actor, reason, _ = self._resolve(42, created_by_id=None)
        assert actor is None
        assert "different user" in reason

    def test_creator_bound_with_access_is_honored(self):
        task_run, actor, reason, mock_access = self._resolve(42)
        assert actor is task_run.task.created_by
        assert reason == ""
        mock_access.assert_called_once_with(task_run.task.created_by, task_run.task.team)
