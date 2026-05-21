from contextlib import AbstractContextManager

from posthog.models.scoping import team_scope


class _MCPAnalyticsTeamScopedTestMixin:
    """Wrap setUp/tearDown with team_scope so direct queries against the
    fail-closed MCPSession / MCPIntentClusterSnapshot managers find a scope.
    Place this BEFORE the TestCase base in the MRO so its setUp creates
    self.team first.
    """

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]
