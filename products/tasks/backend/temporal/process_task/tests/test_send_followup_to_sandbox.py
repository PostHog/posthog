import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    REFRESH_RETRY_DELAY_SECONDS,
    SendFollowupToSandboxInput,
    _refresh_sandbox_mcp,
    refresh_sandbox_mcp_for_user,
    send_followup_to_sandbox,
)
from products.tasks.backend.temporal.process_task.utils import (
    McpServerConfig,
    _mcp_token_issued_cache_key,
    mark_mcp_token_issued,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_mcp_token_cache():
    """Ensure each test starts with no recorded token issuances so the
    refresh gate doesn't carry state between tests. The rate-limit cache key
    is scoped to ``(run_id, user_id)`` so cross-user follow-ups don't get
    silently blocked by a same-run prior refresh — clear both shapes."""
    keys = [_mcp_token_issued_cache_key("run-1"), _mcp_token_issued_cache_key("run-1:42")]
    for key in keys:
        cache.delete(key)
    yield
    for key in keys:
        cache.delete(key)


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
    task.created_by = MagicMock(id=created_by_id) if created_by_id is not None else None
    task_run = MagicMock()
    task_run.id = "run-1"
    task_run.team_id = team_id
    task_run.task = task
    task_run.task_id = "task-1"
    # Default to None so `(task_run.state or {}).get(...)` returns None cleanly.
    # MagicMock auto-attributes would otherwise return further MagicMock objects
    # and leak into kwargs passed to `get_sandbox_ph_mcp_configs`.
    task_run.state = state
    return task_run


def _make_user_mock(user_id: int = 42) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


_OAUTH_FOR_USER_PATH = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_oauth_access_token_for_user"
_OAUTH_APP_PATH = (
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.oauth_application_for_task"
)
_PH_CONFIGS_PATH = (
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_ph_mcp_configs"
)
_USER_CONFIGS_PATH = (
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_user_mcp_server_configs"
)
_SEND_REFRESH_PATH = (
    "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_refresh_session"
)
_TIME_SLEEP_PATH = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.time.sleep"


class TestRefreshSandboxMcpForUser:
    """Covers the actor-parameterized helper that the Slack and web follow-up
    paths share. The legacy ``_refresh_sandbox_mcp`` is now a thin wrapper that
    fills in ``task.created_by`` and delegates here."""

    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_success_path_single_call(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mock_oauth.return_value = "fresh-token"
        mock_oauth_app.return_value = "array"
        mock_ph_configs.return_value = [_make_mcp_config(token="fresh-token")]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=True, status_code=200)

        task_run = _make_task_run_mock()
        user = _make_user_mock(user_id=42)
        result = refresh_sandbox_mcp_for_user(task_run, user, scopes="read_only", auth_token="jwt")

        assert result is not None and result.success is True
        mock_oauth.assert_called_once_with(user, 7, scopes="read_only", application="array")
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

    @patch(_TIME_SLEEP_PATH)
    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_retries_once_on_first_failure(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh, mock_sleep
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.side_effect = [
            CommandResult(success=False, status_code=502, error="transient", retryable=True),
            CommandResult(success=True, status_code=200),
        ]

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        assert mock_send_refresh.call_count == 2
        mock_sleep.assert_called_once_with(REFRESH_RETRY_DELAY_SECONDS)

    @patch(_TIME_SLEEP_PATH)
    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_two_failures_are_non_fatal(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")

        # Must not raise.
        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        assert mock_send_refresh.call_count == 2

    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_token_mint_failure_is_non_fatal_and_skips_send(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mock_oauth.side_effect = RuntimeError("oauth service down")

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        mock_ph_configs.assert_not_called()
        mock_user_configs.assert_not_called()
        mock_send_refresh.assert_not_called()

    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_skips_send_when_no_mcp_configs_resolved(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = []
        mock_user_configs.return_value = []

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        mock_send_refresh.assert_not_called()

    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_scopes_propagate_to_oauth_and_configs(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mock_oauth.return_value = "fresh-token"
        mock_oauth_app.return_value = "array"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=True, status_code=200)

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="full", auth_token=None)

        mock_oauth.assert_called_once_with(mock_oauth.call_args.args[0], 7, scopes="full", application="array")
        mock_ph_configs.assert_called_once_with(
            token="fresh-token", project_id=7, scopes="full", interaction_origin=None, task_id="task-1"
        )

    @patch(_SEND_REFRESH_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_legacy_wrapper_skips_when_no_creator(self, mock_oauth, mock_send_refresh):
        """``_refresh_sandbox_mcp`` (the no-actor wrapper used by the web-layer
        signal path) short-circuits when the task has no ``created_by``. The
        prior implementation would try to mint and log a warning; the new
        wrapper just skips, since the helper requires an explicit user."""
        _refresh_sandbox_mcp(_make_task_run_mock(created_by_id=None), "read_only", auth_token=None)

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()


class TestRefreshIntervalGate:
    """Refreshes within MCP_TOKEN_REFRESH_INTERVAL_SECONDS of a previous
    successful issuance for the *same actor* must be skipped without minting a
    new token or contacting the sandbox. The rate-limit key is scoped to
    ``(run_id, user_id)`` so a cross-user follow-up isn't silently blocked by
    a prior same-run refresh under a different identity."""

    @patch(_SEND_REFRESH_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_skipped_when_token_recently_issued(self, mock_oauth, mock_send_refresh):
        mark_mcp_token_issued("run-1:42")

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        mock_oauth.assert_not_called()
        mock_send_refresh.assert_not_called()

    @patch(_SEND_REFRESH_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_force_bypasses_rate_limit(self, mock_oauth, mock_send_refresh):
        """Cross-user follow-ups pass ``force=True`` so an identity transition
        is never silently dropped on a recent same-run refresh."""
        mark_mcp_token_issued("run-1:42")
        mock_oauth.return_value = "fresh-token"
        mock_send_refresh.return_value = CommandResult(success=True, status_code=200)
        with (
            patch(_PH_CONFIGS_PATH, return_value=[_make_mcp_config()]),
            patch(_USER_CONFIGS_PATH, return_value=[]),
            patch(_OAUTH_APP_PATH, return_value="array"),
        ):
            refresh_sandbox_mcp_for_user(
                _make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None, force=True
            )

        mock_oauth.assert_called_once()
        mock_send_refresh.assert_called_once()

    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_marks_after_successful_refresh(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=True, status_code=200)

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        # Cache entry now exists → next refresh within the interval is gated.
        assert cache.get(_mcp_token_issued_cache_key("run-1:42")) is True

    @patch(_TIME_SLEEP_PATH)
    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_marks_after_successful_retry(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.side_effect = [
            CommandResult(success=False, status_code=502, error="transient"),
            CommandResult(success=True, status_code=200),
        ]

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        assert cache.get(_mcp_token_issued_cache_key("run-1:42")) is True

    @patch(_TIME_SLEEP_PATH)
    @patch(_SEND_REFRESH_PATH)
    @patch(_USER_CONFIGS_PATH)
    @patch(_PH_CONFIGS_PATH)
    @patch(_OAUTH_APP_PATH)
    @patch(_OAUTH_FOR_USER_PATH)
    def test_does_not_mark_after_two_failures(
        self, mock_oauth, mock_oauth_app, mock_ph_configs, mock_user_configs, mock_send_refresh, _mock_sleep
    ):
        mock_oauth.return_value = "fresh-token"
        mock_ph_configs.return_value = [_make_mcp_config()]
        mock_user_configs.return_value = []
        mock_send_refresh.return_value = CommandResult(success=False, status_code=502, error="down")

        refresh_sandbox_mcp_for_user(_make_task_run_mock(), _make_user_mock(), scopes="read_only", auth_token=None)

        # Cache stays empty so the next follow-up retries the dispatch.
        assert cache.get(_mcp_token_issued_cache_key("run-1:42")) is None


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
                "refresh": mock_refresh,
                "user_msg": mock_user_msg,
                "conn_token": mock_conn_token,
            }

    def test_refresh_called_before_user_message(self, _patches):
        call_order: list[str] = []

        def _record_refresh(*a, **kw):
            call_order.append("refresh")

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

    def test_default_scope_is_read_only(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        args, _kwargs = _patches["refresh"].call_args
        assert args[1] == "read_only"
