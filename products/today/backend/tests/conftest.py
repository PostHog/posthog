from contextlib import AbstractContextManager

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _set_team_scope(request):
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


class TodayTeamScopedTestMixin:
    """Wraps TestCase tests in the team scope that ProductTeamModel queries need. Put it before APIBaseTest."""

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
