import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackChannel, SlackSettings, UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import (
    resolve_unprompted_question_mode,
    resolve_untagged_followup_mode,
)


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
            (None, UntaggedFollowupMode.ASK),
            ("retired-value", UntaggedFollowupMode.NEVER),
        ],
    )
    def test_stored_value_governs_with_ask_as_the_default(self, slack_setup, stored, expected):
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            untagged_followup_mode=stored,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == expected

    def test_no_row_at_all_resolves_ask(self, slack_setup):
        assert resolve_untagged_followup_mode(slack_setup, "U001") == UntaggedFollowupMode.ASK

    def test_another_users_choice_does_not_leak(self, slack_setup):
        integration = slack_setup
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U002",
            untagged_followup_mode=UntaggedFollowupMode.AUTO,
        )
        assert resolve_untagged_followup_mode(integration, "U001") == UntaggedFollowupMode.ASK


class TestResolveUnpromptedQuestionMode:
    @pytest.mark.parametrize(
        "user_mode,channel_mode,expected",
        [
            (None, None, UntaggedFollowupMode.ASK),
            # A channel nobody configured caps an author's AUTO at ASK, so no public answer goes out unclicked.
            (UntaggedFollowupMode.AUTO, None, UntaggedFollowupMode.ASK),
            (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
            (UntaggedFollowupMode.ASK, UntaggedFollowupMode.AUTO, UntaggedFollowupMode.ASK),
            (UntaggedFollowupMode.NEVER, UntaggedFollowupMode.AUTO, UntaggedFollowupMode.NEVER),
            (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.NEVER, UntaggedFollowupMode.NEVER),
        ],
    )
    def test_the_stricter_of_author_and_channel_wins(self, db, user_mode, channel_mode, expected):
        SlackSettings.objects.create(slack_workspace_id="T_WS", slack_user_id="U001", untagged_followup_mode=user_mode)
        SlackChannel.objects.create(
            slack_workspace_id="T_WS", slack_channel_id="C001", unprompted_answer_mode=channel_mode
        )
        assert resolve_unprompted_question_mode("T_WS", "C001", "U001") == expected

    def test_another_channels_ceiling_does_not_leak(self, db):
        SlackSettings.objects.create(
            slack_workspace_id="T_WS", slack_user_id="U001", untagged_followup_mode=UntaggedFollowupMode.AUTO
        )
        SlackChannel.objects.create(
            slack_workspace_id="T_WS", slack_channel_id="C002", unprompted_answer_mode=UntaggedFollowupMode.NEVER
        )
        assert resolve_unprompted_question_mode("T_WS", "C001", "U001") == UntaggedFollowupMode.ASK
