import uuid
from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.posthog_ai.backend.models import TrackedQuestion, TrackedQuestionRun

from ee.models.assistant import Conversation


class TestTrackedQuestionModel(BaseTest):
    def _make_conversation(self) -> Conversation:
        return Conversation.objects.create(team=self.team, user=self.user)

    def _make_tracked_question(self, **overrides) -> TrackedQuestion:
        conversation = overrides.pop("source_conversation", None) or self._make_conversation()
        now = timezone.now()
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "source_conversation": conversation,
            "source_human_message_id": uuid.uuid4(),
            "source_visualization_message_id": uuid.uuid4(),
            "title": "Weekly activation",
            "question_text": "What's our weekly activation rate?",
            "baseline_summary": "Baseline activation is 41.3%.",
            "baseline_captured_at": now,
            "cadence": TrackedQuestion.Cadence.WEEKLY,
            "next_run_at": now + timedelta(days=7),
        }
        defaults.update(overrides)
        return TrackedQuestion.objects.create(**defaults)

    def test_create_and_default_status(self) -> None:
        tracked_question = self._make_tracked_question()
        self.assertEqual(tracked_question.status, TrackedQuestion.Status.ACTIVE)
        self.assertEqual(tracked_question.cadence, TrackedQuestion.Cadence.WEEKLY)
        self.assertEqual(tracked_question.team, self.team)

    def test_unique_per_message_constraint(self) -> None:
        conversation = self._make_conversation()
        viz_id = uuid.uuid4()
        self._make_tracked_question(
            source_conversation=conversation,
            source_visualization_message_id=viz_id,
        )
        with self.assertRaises(Exception):
            self._make_tracked_question(
                source_conversation=conversation,
                source_visualization_message_id=viz_id,
            )

    def test_runs_relationship(self) -> None:
        tracked_question = self._make_tracked_question()
        run = TrackedQuestionRun.objects.create(
            team=self.team,
            tracked_question=tracked_question,
            state=TrackedQuestionRun.State.DRIFTED,
            severity=TrackedQuestionRun.Severity.MODERATE,
            narrative="Activation dropped to 28%.",
            judge_summary="Material drop in activation.",
        )
        self.assertEqual(list(tracked_question.runs.all()), [run])
        self.assertEqual(tracked_question.runs.first().severity, TrackedQuestionRun.Severity.MODERATE)
