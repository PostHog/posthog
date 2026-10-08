import pytest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.model_router import model_router_options


@pytest.fixture
def team(db):
    organization = Organization.objects.create(name="Org")
    return Team.objects.create(organization=organization, name="Team")


class TestModelRouterOptions:
    def test_options_leave_out_a_model_the_viewer_may_not_use(self, team):
        with patch(
            "products.tasks.backend.facade.run_config.get_model_access_error",
            side_effect=lambda model, distinct_id: "gated" if model.startswith("claude-") else None,
        ):
            options = model_router_options(team_id=team.id, user_id=None, distinct_id="viewer")

        assert options
        assert not [option for option in options if option.model.startswith("claude-")]
        assert len({option.key for option in options}) == len(options)
