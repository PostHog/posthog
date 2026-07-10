from contextlib import AbstractContextManager

import pytest

from posthog.models.scoping import team_scope

PRODUCT_DATABASES = {"default", "stamphog_db_writer", "stamphog_db_reader"}


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    """Set team context for raw pytest tests that hit the database.

    ProductTeamModel is fail-closed — queries without context raise
    TeamScopeError. TestCase / APIBaseTest subclasses create their own team in
    setUp() and are skipped here (getfixturevalue("team") would duplicate-create
    with the same api_token); those use StamphogTeamScopedTestMixin instead.
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


class StamphogTeamScopedTestMixin:
    """Mixin for TestCase / APIBaseTest tests that use ProductTeamModel.

    Wraps setUp/tearDown with team_scope so the test body's queries find a
    scope. Place BEFORE APIBaseTest in the MRO so its setUp runs first
    (creating self.team) and ours can use it.
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
