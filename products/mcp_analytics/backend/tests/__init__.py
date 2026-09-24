from contextlib import AbstractContextManager

from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.mcp_analytics.backend.facade.contracts import MCP_ANALYTICS_INTENT_ROUTING_FEATURE_FLAG


def _only_mcp_analytics_flag(flag_key: str, *args: object, **kwargs: object) -> bool:
    # Enable just the intent-routing flag; leave every other flag off so tests don't silently
    # mask unrelated flag-gated behavior.
    return flag_key == MCP_ANALYTICS_INTENT_ROUTING_FEATURE_FLAG


def deny_mcp_analytics_access() -> AbstractContextManager[object]:
    return patch.object(
        UserAccessControl,
        "assert_access_level_for_resource",
        side_effect=UserAccessControlError("mcp_analytics", "viewer"),
    )


class _MCPAnalyticsTeamScopedTestMixin:
    """Shared setUp/tearDown for mcp_analytics presentation tests:

    - wraps the test in ``team_scope`` so direct queries against the fail-closed
      MCPSession / MCPIntentClusterSnapshot managers find a scope, and
    - enables the MCP analytics intent-routing feature flag (and only that flag),
      since the intent-clustering endpoints are gated behind it.

    Place this BEFORE the TestCase base in the MRO so its setUp creates self.team first.
    """

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm
        flag_patcher = patch("posthoganalytics.feature_enabled", side_effect=_only_mcp_analytics_flag)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]
