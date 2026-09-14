import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _use_default_wizard_registry():
    with patch("posthoganalytics.get_feature_flag_payload", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield
