import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope


def _only_engineering_analytics_flag(flag_key: str, *args: object, **kwargs: object) -> bool:
    # Enable just the engineering-analytics rollout flag; leave every other flag at its
    # default (off) so tests don't silently mask unrelated flag-gated behavior.
    return flag_key == "engineering-analytics"


@pytest.fixture(autouse=True)
def _enable_engineering_analytics_flag():
    # The viewset is gated on PostHogFeatureFlagPermission; without this every endpoint test 403s.
    with patch("posthoganalytics.feature_enabled", side_effect=_only_engineering_analytics_flag):
        yield


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield
