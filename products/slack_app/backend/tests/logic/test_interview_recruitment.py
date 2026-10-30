import json

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.logic import interview_recruitment
from products.slack_app.backend.logic.feature_tips.state import get_state, update_state
from products.slack_app.backend.logic.interview_recruitment import (
    BOOKING_URL,
    INTERVIEW_OPT_OUT_ACTION_ID,
    FrustrationInviteRequest,
    FrustrationSignal,
    handle_interview_action,
    offer_frustration_invite,
)
from products.slack_app.backend.models import SlackThreadTaskMapping

WORKSPACE = "T_INTERVIEW"
SLACK_USER = "U_READER"


def _verdict(choice: str, confidence: float) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(
        model="m",
        answers={"sentiment": ChoiceAnswer(choice=choice, confidence=confidence, probabilities={})},
        input_tokens=None,
    )
    return client


@pytest.mark.django_db
class TestFrustrationInvite:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=organization, name="Team")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "xoxb-test"}
        )
        with (
            patch.object(interview_recruitment, "post_slack_ephemeral") as self.post,
            patch.object(interview_recruitment, "SlackIntegration"),
            patch.object(interview_recruitment, "capture_slack_event") as self.capture,
            patch.object(interview_recruitment, "build_system_one_client", return_value=_verdict("unhappy", 0.9)),
        ):
            yield

    def _threads(self, count: int) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        for index in range(count):
            task = Task.objects.create(team=self.team, title="t")
            SlackThreadTaskMapping.objects.create(
                team=self.team,
                integration=self.integration,
                slack_workspace_id=WORKSPACE,
                channel="C1",
                thread_ts=f"{index}.1",
                task=task,
                task_run=TaskRun.objects.create(team=self.team, task=task),
                mentioning_slack_user_id=SLACK_USER,
            )

    def _offer(self, signal: FrustrationSignal = "message") -> bool:
        return offer_frustration_invite(
            FrustrationInviteRequest(
                integration=self.integration,
                slack_user_id=SLACK_USER,
                posthog_user=None,
                channel="C1",
                thread_ts="1.1",
                signal=signal,
                person_message="this is the third time you got the funnel wrong",
            )
        )

    def test_a_frustrated_reader_is_invited_once_a_month(self):
        self._threads(3)

        assert [self._offer(), self._offer()] == [True, False]
        self.post.assert_called_once()
        book = self.post.call_args.kwargs["blocks"][1]["elements"][0]
        assert book["url"] == BOOKING_URL
        assert self.capture.call_args.args[1] == "slack app interview invite shown"
        assert self.capture.call_args.kwargs["surface"] == "frustration"

    @parameterized.expand(
        [
            ("calm_message", 3, _verdict("not_unhappy", 0.95), None),
            ("unsure_model", 3, _verdict("unhappy", 0.5), None),
            ("new_reader", 2, _verdict("unhappy", 0.9), None),
            ("tips_turned_off", 3, _verdict("unhappy", 0.9), "opted_out_at"),
            ("invitations_turned_off", 3, _verdict("unhappy", 0.9), "interview_opted_out_at"),
            ("tip_under_the_same_answer", 3, _verdict("unhappy", 0.9), "last_shown_at"),
        ]
    )
    def test_no_invitation_when_a_gate_fails(self, _name, threads, client, stamped_field):
        self._threads(threads)
        if stamped_field:
            update_state(WORKSPACE, SLACK_USER, lambda state: setattr(state, stamped_field, timezone.now()))

        with patch.object(interview_recruitment, "build_system_one_client", return_value=client):
            assert self._offer() is False
        self.post.assert_not_called()

    def test_a_failed_post_keeps_the_readers_slot(self):
        self._threads(3)
        self.post.side_effect = [RuntimeError("channel_not_found"), {"ok": True}]

        assert [self._offer(), self._offer()] == [False, True]

    def test_a_thumbs_down_reaction_needs_no_model(self):
        self._threads(3)

        with patch.object(interview_recruitment, "build_system_one_client", side_effect=RuntimeError) as model:
            assert self._offer(signal="reaction") is True
        model.assert_not_called()

    def test_dont_ask_again_stops_every_later_invitation(self):
        self._threads(3)
        value = json.dumps({"integration_id": self.integration.id, "surface": "frustration"})

        with patch.object(interview_recruitment, "post_response_url"):
            handle_interview_action(
                {
                    "team": {"id": WORKSPACE},
                    "user": {"id": SLACK_USER},
                    "response_url": "https://hooks.slack.com/actions/x",
                    "actions": [{"action_id": INTERVIEW_OPT_OUT_ACTION_ID, "value": value}],
                }
            )

        assert get_state(WORKSPACE, SLACK_USER).interview_opted_out_at is not None
        assert self.capture.call_args.args[1] == "slack app interview invites turned off"
        assert self._offer(signal="reaction") is False
