import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.engineering_analytics.backend.tests._logic_helpers import anchor_seed_clock


def _only_engineering_analytics_flag(flag_key: str, *args: object, **kwargs: object) -> bool:
    # Every other flag stays off, so the tests do not mask unrelated flag-gated behavior.
    return flag_key == "engineering-analytics"


@pytest.fixture(autouse=True)
def _enable_engineering_analytics_flag():
    with patch("posthoganalytics.feature_enabled", side_effect=_only_engineering_analytics_flag):
        yield


@pytest.fixture(autouse=True)
def _anchor_seed_clock():
    anchor_seed_clock()


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield
