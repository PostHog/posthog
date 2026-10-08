import pytest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.model_router import model_router_options
from products.tasks.backend.facade.model_catalogue import CAPABILITY_LADDER_BY_RUNTIME_ADAPTER


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
        assert len({option.model for option in options}) == len(options)

    def test_every_ladder_option_says_what_its_model_is_good_for(self, team):
        with patch("products.tasks.backend.facade.run_config.get_model_access_error", return_value=None):
            options = model_router_options(team_id=team.id, user_id=None, distinct_id="viewer")

        ladder = {notch.model for notches in CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.values() for notch in notches}
        unexplained = [
            option.model for option in options if option.model in ladder and "Model: " not in option.description
        ]
        assert unexplained == []
