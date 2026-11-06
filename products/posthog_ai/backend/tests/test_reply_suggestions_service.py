from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.posthog_ai.backend.reply_suggestions.service import (
    REPLY_SUGGESTIONS_METHOD,
    ReplySuggestionsOutcome,
    generate_reply_suggestions,
)
from products.tasks.backend.facade.api import TaskClientProvenance
from products.tasks.backend.facade.contracts import StreamNotificationDelivery
from products.tasks.backend.facade.reply_suggestions import SuggestedReply
from products.tasks.backend.models import Task

SERVICE = "products.posthog_ai.backend.reply_suggestions.service"
OPEN_PR = SuggestedReply(label="Yes, open the PR", reply="Yes, open the pull request with the fix")


def _notification(method: str, params: dict) -> dict:
    return {"type": "notification", "notification": {"method": method, "params": params}}


def _user_message(text: str) -> dict:
    return _notification("_posthog/user_message", {"content": text})


def _agent_final(text: str) -> dict:
    return _notification(
        "session/update",
        {"update": {"sessionUpdate": "agent_message", "messageId": "m1", "content": {"type": "text", "text": text}}},
    )


def _turn_complete() -> dict:
    return _notification("_posthog/turn_complete", {"stopReason": "end_turn"})


TWO_TURNS = [
    _user_message("How many signups last week?"),
    _agent_final("There were 120 signups."),
    _turn_complete(),
    _user_message("Why did the relay keep retrying?"),
    _agent_final("The retry loop never stops. Should I open a pull request with the fix?"),
    _turn_complete(),
]


class TestGenerateReplySuggestions(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        self.task_run = self.task.create_run(mode="interactive")

        patchers = {
            "history": patch(f"{SERVICE}.read_task_run_history", return_value=TWO_TURNS),
            "publish": patch(
                f"{SERVICE}.publish_task_run_stream_notification",
                return_value=StreamNotificationDelivery(live=True, persisted=False),
            ),
            "suggest": patch(f"{SERVICE}.suggest_replies", return_value=[OPEN_PR]),
            "flag": patch(f"{SERVICE}.feature_enabled_or_false", return_value=True),
        }
        self.mocks = {name: patcher.start() for name, patcher in patchers.items()}
        for patcher in patchers.values():
            self.addCleanup(patcher.stop)

    def _generate(self) -> ReplySuggestionsOutcome:
        return generate_reply_suggestions(str(self.task_run.id), self.team.id)

    def test_publishes_the_latest_turns_suggestions_to_the_live_stream_only(self):
        assert self._generate() == ReplySuggestionsOutcome(status="emitted", reason="1")

        answer, attribution, person_message = self.mocks["suggest"].call_args.args
        assert answer == "The retry loop never stops. Should I open a pull request with the fix?"
        assert person_message == "Why did the relay keep retrying?"
        assert attribution.ai_product == "posthog_ai"
        assert attribution.run_id == str(self.task_run.id)
        publish = self.mocks["publish"].call_args
        assert publish.args[3] == REPLY_SUGGESTIONS_METHOD
        assert publish.args[4] == {
            "turnIndex": 1,
            "suggestions": [{"label": OPEN_PR.label, "reply": OPEN_PR.reply}],
        }
        assert publish.kwargs == {"persist": False}

    @parameterized.expand(
        [
            ("answer_still_streaming", {"history": TWO_TURNS[:-1]}, "turn_in_progress"),
            ("flag_off", {"flag": False}, "flag_off"),
            ("nothing_to_suggest", {"suggest": []}, "nothing_to_suggest"),
        ]
    )
    def test_skips_without_publishing(self, _name: str, returns: dict, reason: str):
        for name, value in returns.items():
            self.mocks[name].return_value = value

        assert self._generate() == ReplySuggestionsOutcome(status="skipped", reason=reason)
        self.mocks["publish"].assert_not_called()

    @parameterized.expand(
        [
            ("desktop_conversation", "client_provenance", TaskClientProvenance.POSTHOG_DESKTOP, "not_started_in_web"),
            ("slack_conversation", "origin_product", Task.OriginProduct.SLACK, "not_posthog_ai_conversation"),
        ]
    )
    def test_skips_conversations_the_web_composer_does_not_show(self, _name: str, field: str, value, reason: str):
        setattr(self.task, field, value)
        self.task.save()

        assert self._generate() == ReplySuggestionsOutcome(status="skipped", reason=reason)
        self.mocks["suggest"].assert_not_called()
