from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, RefusalAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import claim_message_handled
from products.slack_app.backend.models import SlackSettings, UntaggedFollowupMode
from products.slack_app.backend.temporal.activities.untagged_question import (
    ANSWERABLE_QUESTION_ID,
    ASKS_QUESTION_ID,
    UntaggedQuestionVerdict,
    classify_untagged_question,
    classify_untagged_question_activity,
    request_untagged_question_confirmation_activity,
)
from products.slack_app.backend.temporal.types import PostHogCodeSlackMentionWorkflowInputs

MODULE = "products.slack_app.backend.temporal.activities.untagged_question"


def _result(asks: Any, answerable: Any) -> SystemOneResult:
    return SystemOneResult(
        model="jev", answers={ASKS_QUESTION_ID: asks, ANSWERABLE_QUESTION_ID: answerable}, input_tokens=None
    )


class TestClassifyUntaggedQuestion(SimpleTestCase):
    @parameterized.expand(
        [
            ("both confident", NoulAnswer(probability=0.97), NoulAnswer(probability=0.91), True),
            ("a question PostHog cannot answer", NoulAnswer(probability=0.97), NoulAnswer(probability=0.6), False),
            ("answerable but not a question", NoulAnswer(probability=0.5), NoulAnswer(probability=0.95), False),
            ("a refusal", NoulAnswer(probability=0.99), RefusalAnswer(), None),
        ]
    )
    def test_both_judgments_must_clear_the_threshold(self, _name, asks, answerable, expected):
        client = MagicMock()
        client.decide.return_value = _result(asks, answerable)
        with patch(f"{MODULE}.build_system_one_client", return_value=client):
            verdict = classify_untagged_question(
                "How many people signed up last week?", team_id=1, distinct_id="user-1"
            )

        assert (verdict.answerable if verdict else None) == expected
        # The message travels as state, never inside the instructions.
        state = client.decide.call_args.kwargs["state"]
        assert state == {"message": "How many people signed up last week?"}


class TestRequestUntaggedQuestionConfirmation(TestCase):
    def setUp(self):
        cache.clear()
        organization = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=organization, name="Team")
        self.user = User.objects.create(email="alice@example.com", distinct_id="user-1")
        self.integration = Integration.objects.create(
            team=team, kind="slack", integration_id="T_WS", sensitive_config={"access_token": "xoxb"}
        )
        self.inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"type": "message", "channel": "C1", "user": "U_ALICE", "ts": "1.0", "text": "how many signups?"},
            integration_id=self.integration.id,
            slack_team_id="T_WS",
            user_id=self.user.id,
            untagged_question=True,
        )

    @parameterized.expand(
        [
            ("auto answers", UntaggedFollowupMode.AUTO, False, False),
            ("never stays quiet", UntaggedFollowupMode.NEVER, True, False),
            ("ask offers privately", UntaggedFollowupMode.ASK, True, True),
            ("unset offers privately", None, True, True),
        ]
    )
    def test_the_authors_mode_decides(self, _name, user_mode, expect_stop, expect_prompt):
        if user_mode is not None:
            SlackSettings.objects.create(
                slack_workspace_id="T_WS", slack_user_id="U_ALICE", untagged_question_mode=user_mode
            )
        with (
            patch("products.slack_app.backend.api._post_untagged_question_prompt", return_value=True) as mock_prompt,
            patch(f"{MODULE}.channel_is_ext_shared", return_value=False),
        ):
            stop = request_untagged_question_confirmation_activity(self.inputs)

        assert stop is expect_stop
        assert mock_prompt.called is expect_prompt

    def test_auto_stays_quiet_in_a_channel_shared_since_the_webhook(self):
        SlackSettings.objects.create(
            slack_workspace_id="T_WS", slack_user_id="U_ALICE", untagged_question_mode=UntaggedFollowupMode.AUTO
        )
        with patch(f"{MODULE}.channel_is_ext_shared", return_value=True):
            assert request_untagged_question_confirmation_activity(self.inputs) is True

    @parameterized.expand(
        [
            ("first to claim", None, True),
            ("an edited mention claimed it first", "edited_mention", False),
            # A retry after a crash between the claim and its recorded result keeps the message.
            ("its own earlier attempt claimed it", "untagged_question:run-1", True),
        ]
    )
    def test_an_answerable_question_runs_only_when_it_claims_the_message(self, _name, claimed_by, expected):
        if claimed_by is not None:
            claim_message_handled("T_WS", self.inputs.event, claimed_by)
        verdict = UntaggedQuestionVerdict(asks_for_information=0.99, answerable_by_posthog=0.99)
        info = MagicMock(workflow_run_id="run-1")
        with (
            patch(f"{MODULE}.classify_untagged_question", return_value=verdict),
            patch(f"{MODULE}.activity.info", return_value=info),
        ):
            assert classify_untagged_question_activity(self.inputs) is expected
