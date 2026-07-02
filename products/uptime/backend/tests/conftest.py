from contextlib import AbstractContextManager

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    """Set team context for raw pytest tests (Monitor is a ProductTeamModel).

    Skipped for Django TestCase subclasses — they create their own team in setUp()
    and would collide on the team's unique api_token. Those use UptimeTeamScopedTestMixin
    instead, which wraps setUp/tearDown around the test's own self.team.
    """
    if request.node.get_closest_marker("django_db") is None:
        yield
        return

    is_django_testcase = request.cls is not None and any(cls.__name__ == "TestCase" for cls in request.cls.__mro__)
    if is_django_testcase:
        yield
        return

    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield


class UptimeTeamScopedTestMixin:
    """Wraps setUp/tearDown with team_scope for TestCase / APIBaseTest tests using ProductTeamModel.

    Place BEFORE BaseTest / APIBaseTest in the MRO so its setUp runs first
    (creating self.team) and this setUp can use it:

        class TestFoo(UptimeTeamScopedTestMixin, APIBaseTest):
            ...
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
