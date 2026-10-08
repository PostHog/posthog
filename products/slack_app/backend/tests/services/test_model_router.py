import pytest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.model_router import (
    PERSONAL_DEFAULT_NOTE,
    SLACK_DEFAULT_NOTE,
    model_router_options,
)
from products.slack_app.backend.services.run_preferences import SLACK_DEFAULT_MODEL
from products.tasks.backend.facade.ai_run_defaults import update_user_ai_run_preferences
from products.tasks.backend.facade.model_catalogue import CAPABILITY_LADDER_BY_RUNTIME_ADAPTER

ACCESS_ERROR = "products.tasks.backend.facade.run_config.get_model_access_error"


@pytest.fixture
def team(db):
    organization = Organization.objects.create(name="Org")
    return Team.objects.create(organization=organization, name="Team")


class TestModelRouterOptions:
    def test_options_leave_out_a_model_the_viewer_may_not_use(self, team):
        with patch(
            ACCESS_ERROR,
            side_effect=lambda model, distinct_id: "gated" if model.startswith("claude-") else None,
        ):
            options = model_router_options(team_id=team.id, user_id=None, distinct_id="viewer")

        assert options
        assert not [option for option in options if option.model.startswith("claude-")]
        assert len({option.model for option in options}) == len(options)

    def test_every_ladder_option_says_what_its_model_is_good_for(self, team):
        with patch(ACCESS_ERROR, return_value=None):
            options = model_router_options(team_id=team.id, user_id=None, distinct_id="viewer")

        ladder = {notch.model for notches in CAPABILITY_LADDER_BY_RUNTIME_ADAPTER.values() for notch in notches}
        unexplained = [
            option.model for option in options if option.model in ladder and "Model: " not in option.description
        ]
        assert unexplained == []

    @pytest.mark.parametrize(
        "stored_model,gated_model,expected_default,expected_note",
        [
            ("openai/gpt-6-sol", None, "gpt-6-sol", PERSONAL_DEFAULT_NOTE),
            ("gpt-6-sol", "gpt-6-sol", SLACK_DEFAULT_MODEL, SLACK_DEFAULT_NOTE),
        ],
        ids=["provider_qualified_default", "gated_default_falls_to_slack_default"],
    )
    def test_marks_the_default_the_run_would_use(
        self, team, stored_model, gated_model, expected_default, expected_note
    ):
        user = User.objects.create_and_join(team.organization, "router@example.com", None)
        update_user_ai_run_preferences(
            team.id, user.id, runtime_adapter="codex", model=stored_model, reasoning_effort=None
        )
        with patch(ACCESS_ERROR, side_effect=lambda model, distinct_id: "gated" if model == gated_model else None):
            options = model_router_options(team_id=team.id, user_id=user.id, distinct_id="viewer")

        assert [option.model for option in options if expected_note in option.description] == [expected_default]
