import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings, ThreadJoinMode, UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import (
    resolve_thread_join_mode,
    resolve_untagged_followup_mode,
    resolve_untagged_question_mode,
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


class TestResolveUntaggedQuestionMode:
    def test_unset_resolves_ask(self, slack_setup):
        assert resolve_untagged_question_mode("T_WS", "U001") == UntaggedFollowupMode.ASK

    @pytest.mark.parametrize(
        "followup_mode,question_mode,expected",
        [
            # Each column answers only its own question.
            (UntaggedFollowupMode.AUTO, None, UntaggedFollowupMode.ASK),
            (UntaggedFollowupMode.NEVER, UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
        ],
    )
    def test_the_followup_choice_does_not_leak(self, slack_setup, followup_mode, question_mode, expected):
        SlackSettings.objects.create(
            slack_workspace_id="T_WS",
            slack_user_id="U001",
            untagged_followup_mode=followup_mode,
            untagged_question_mode=question_mode,
        )
        assert resolve_untagged_question_mode("T_WS", "U001") == expected


class TestWorkspaceReplyDefaults:
    @pytest.mark.parametrize(
        "column,personal,workspace,expected",
        [
            ("untagged_followup_mode", None, UntaggedFollowupMode.NEVER, UntaggedFollowupMode.NEVER),
            (
                "untagged_followup_mode",
                UntaggedFollowupMode.AUTO,
                UntaggedFollowupMode.NEVER,
                UntaggedFollowupMode.AUTO,
            ),
            ("untagged_followup_mode", "no_row", UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
            ("untagged_followup_mode", None, "retired-value", UntaggedFollowupMode.NEVER),
            ("untagged_question_mode", None, UntaggedFollowupMode.AUTO, UntaggedFollowupMode.AUTO),
            ("untagged_question_mode", None, None, UntaggedFollowupMode.ASK),
            ("thread_join_mode", None, ThreadJoinMode.NEVER, ThreadJoinMode.NEVER),
            ("thread_join_mode", ThreadJoinMode.ALLOW, ThreadJoinMode.NEVER, ThreadJoinMode.ALLOW),
        ],
    )
    def test_a_person_who_never_picked_gets_the_workspace_default(
        self, slack_setup, column, personal, workspace, expected
    ):
        SlackSettings.objects.create(slack_workspace_id="T_WS", slack_user_id=None, **{column: workspace})
        if personal != "no_row":
            SlackSettings.objects.create(slack_workspace_id="T_WS", slack_user_id="U001", **{column: personal})

        resolved = {
            "untagged_followup_mode": lambda: resolve_untagged_followup_mode(slack_setup, "U001"),
            "untagged_question_mode": lambda: resolve_untagged_question_mode("T_WS", "U001"),
            "thread_join_mode": lambda: resolve_thread_join_mode(slack_setup, "U001"),
        }[column]()

        assert resolved == expected
