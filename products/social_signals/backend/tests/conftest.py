"""Shared fixtures for social_signals tests.

ProductTeamModel is fail-closed — queries without team context raise
TeamScopeError. Pure-pytest tests get an autouse fixture; TestCase /
APIBaseTest subclasses use the mixin below so they can create their own
team in setUp() without colliding on api_token.
"""

from contextlib import AbstractContextManager

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    """Scope DB queries to ``team.id`` for raw pytest tests.

    Activates only for tests marked with ``@pytest.mark.django_db``; skipped
    for TestCase / APIBaseTest subclasses which use ``SocialSignalsTeamScopedTestMixin``
    instead.
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


class SocialSignalsTeamScopedTestMixin:
    """Wrap setUp/tearDown with team_scope for TestCase / APIBaseTest subclasses.

    Place BEFORE the test-case base in the MRO so its setUp runs first
    (creating ``self.team``) and our setUp can scope to that team.
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
