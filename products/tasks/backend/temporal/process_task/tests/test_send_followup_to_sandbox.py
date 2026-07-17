import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from temporalio.exceptions import ApplicationError

from posthog.models.user_integration import ReauthorizationRequired

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    REFRESH_RETRY_DELAY_SECONDS,
    SEND_FOLLOWUP_MAX_ATTEMPTS,
    SendFollowupToSandboxInput,
    _refresh_sandbox_github,
    _refresh_sandbox_mcp,
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
    def test_success_path_single_call(self, mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh, _sleep):
        _arm_success(mock_oauth, mock_ph_configs, mock_user_configs, mock_send_refresh)

        task_run = _make_task_run_mock()
        _refresh(task_run, auth_token="jwt")

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
        safe = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert safe is False
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
        safe = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert safe is False


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
        safe = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert safe is False  # fail closed: prior session may still be live
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
        safe = _refresh_sandbox_mcp(_make_task_run_mock(), "read_only", None, actor_user=actor, state=None)

        assert safe is True
        mock_send_refresh.assert_not_called()
        assert get_sandbox_mcp_session_user("run-1") == 42  # binding recorded


_GH_MODULE = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox"


@patch(f"{_GH_MODULE}.clear_github_credentials_from_sandbox")
@patch(f"{_GH_MODULE}.apply_github_credentials_to_sandbox")
@patch(f"{_GH_MODULE}.get_sandbox_github_token")
@patch(f"{_GH_MODULE}._resolve_live_sandbox")
@patch(f"{_GH_MODULE}.get_pr_authorship_mode")
class TestSandboxGithubIdentityGate:
    """On an actor transition the sandbox's GitHub credentials rebind to the new
    actor when they have access, otherwise the sandbox is logged out so the
    previous actor's identity can't be used."""

    def test_same_actor_skips(self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mark_sandbox_github_identity("run-1", 42)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is True
        mock_resolve.assert_not_called()
        mock_get_token.assert_not_called()
        mock_apply.assert_not_called()
        mock_clear.assert_not_called()

    def test_bot_authorship_skips(self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear):
        # BOT runs share a single installation token, so every actor is already
        # the same GitHub identity — nothing to rebind.
        mock_authorship.return_value = PrAuthorshipMode.BOT
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is True
        mock_get_token.assert_not_called()
        mock_apply.assert_not_called()
        mock_clear.assert_not_called()

    def test_transition_with_access_rebinds(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = MagicMock()
        mock_get_token.return_value = "ghu_newtoken"
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is True
        mock_apply.assert_called_once()
        assert mock_apply.call_args.args[2] == "ghu_newtoken"
        mock_clear.assert_not_called()
        assert get_sandbox_github_identity_user("run-1") == 42

    def test_transition_without_access_logs_out(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = MagicMock()
        mock_get_token.side_effect = ReauthorizationRequired("no repo access")
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is True
        mock_apply.assert_not_called()
        mock_clear.assert_called_once()
        assert get_sandbox_github_identity_user("run-1") == 42

    def test_apply_failure_falls_back_to_logout(
        self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear
    ):
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = MagicMock()
        mock_get_token.return_value = "ghu_newtoken"
        mock_apply.side_effect = RuntimeError("write failed")
        mock_clear.return_value = True
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is True
        mock_apply.assert_called_once()
        mock_clear.assert_called_once()  # fell through to logout so no stale creds remain

    def test_logout_failure_fails_closed(self, mock_authorship, mock_resolve, mock_get_token, mock_apply, mock_clear):
        # New actor has no access and the sandbox can't even be cleared — the
        # previous actor's creds may still be live, so fail closed.
        mock_authorship.return_value = PrAuthorshipMode.USER
        mock_resolve.return_value = MagicMock()
        mock_get_token.side_effect = ReauthorizationRequired("no repo access")
        mock_clear.return_value = False
        mark_sandbox_github_identity("run-1", 99)

        assert _refresh_sandbox_github(_make_task_run_mock(), MagicMock(id=42), None) is False
        assert get_sandbox_github_identity_user("run-1") == 99  # binding unchanged


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
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp"
            ) as mock_refresh,
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
                "user_msg": mock_user_msg,
                "conn_token": mock_conn_token,
            }

    def test_refresh_called_before_user_message(self, _patches):
        call_order: list[str] = []

        def _record_refresh(*a, **kw):
            call_order.append("refresh")
            return True  # refresh confirmed the session is safe; gate lets the turn proceed

        def _record_user_msg(*a, **kw):
            call_order.append("user_message")
            return CommandResult(success=True, status_code=200, data={"result": {"stopReason": "end_turn"}})

        _patches["refresh"].side_effect = _record_refresh
        _patches["user_msg"].side_effect = _record_user_msg

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", posthog_mcp_scopes="full"))

        assert call_order == ["refresh", "user_message"]

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
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp"
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
            mock_conn_token.return_value = "jwt"

            yield {
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

    def test_undelivered_message_stays_fatal(self, _patches):
        # The non-fatal carve-out must stay scoped to delivered-but-running —
        # a connection failure means the user's message never arrived.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=502, error="Connection to sandbox failed", retryable=True
        )

        with pytest.raises(ApplicationError, match="Connection to sandbox failed") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        _patches["turn_complete"].assert_not_called()

    def test_response_504_retries_without_sentinel(self, _patches):
        # Regression: a genuine 504 *response* (tunnel gateway timeout,
        # delivery unknown) used to be conflated with the read-timeout case
        # and silently treated as delivered — losing the user's message.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox returned 504", retryable=True
        )

        with pytest.raises(ApplicationError, match="delivery unknown") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

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
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

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

    def test_message_id_forwarded_to_sandbox(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        _, kwargs = _patches["user_msg"].call_args
        assert kwargs["message_id"] == "m-1"
