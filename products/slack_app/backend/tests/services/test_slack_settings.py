import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings, UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import resolve_untagged_followup_mode


@pytest.fixture
def slack_setup(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    integration = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_WS",
        sensitive_config={"access_token": "xoxb"},
    )
    return integration


class TestResolveUntaggedFollowupMode:
    @pytest.mark.parametrize(
        "stored,expected",
        [
            (UntaggedFollowupMode.ASK, UntaggedFollowupMode.ASK),
            (UntaggedFollowupMode.NEVER, UntaggedFollowupMode.NEVER),
            (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
            # A row that predates the column, and a value retired since it was written,
            # both leave the feature off rather than opting someone in by accident.
            (None, UntaggedFollowupMode.NEVER),
            ("retired-value", UntaggedFollowupMode.NEVER),
        ],
    )
    def test_stored_value_governs_with_never_as_the_floor(self, slack_setup, stored, expected):
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            untagged_followup_mode=stored,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == expected

    def test_no_row_at_all_resolves_never(self, slack_setup):
        assert resolve_untagged_followup_mode(slack_setup, "U001") == UntaggedFollowupMode.NEVER

    def test_another_users_choice_does_not_leak(self, slack_setup):
        # The mode is read per thread creator, so one person opting in must not
        # turn follow-ups on in everybody else's threads.
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U002",
            untagged_followup_mode=UntaggedFollowupMode.AUTO,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == UntaggedFollowupMode.NEVER
