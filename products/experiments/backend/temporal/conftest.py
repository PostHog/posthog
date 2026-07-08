import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _enter_team_scope(request):
    """Open team_scope around every DB-touching test that exposes self.team (i.e. BaseTest subclasses).

    Tests without self.team (no BaseTest, or pure helper-level tests) get a no-op fixture; they explicitly
    don't need scope because they don't hit the fail-closed ORM manager on ExperimentMetricsRecalculation.
    """
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    instance = getattr(request.node, "instance", None)
    team = getattr(instance, "team", None) if instance is not None else None
    if team is None:
        yield
        return
    with team_scope(team.id, canonical=True):
        yield
