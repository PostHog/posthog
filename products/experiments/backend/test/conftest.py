import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _enter_team_scope(request):
    """Open team_scope around every test that exposes self.team (BaseTest / APIBaseTest subclasses).

    Tests without self.team get a no-op fixture; they don't hit the fail-closed ORM manager on
    ExperimentMetricsRecalculation. (The django_db marker check that the temporal-package conftest uses
    doesn't apply here — APIBaseTest is unittest-style via DRFTestCase, not a pytest-marked function.)
    """
    instance = getattr(request.node, "instance", None)
    team = getattr(instance, "team", None) if instance is not None else None
    if team is None:
        yield
        return
    with team_scope(team.id, canonical=True):
        yield
