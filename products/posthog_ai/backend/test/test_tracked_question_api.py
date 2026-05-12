import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from products.posthog_ai.backend.models import TrackedQuestion
from products.signals.backend.models import SignalSourceConfig

from ee.models.assistant import Conversation


class TestTrackedQuestionViewSet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.human_message_id = uuid.uuid4()
        self.visualization_message_id = uuid.uuid4()
        # Patch the helpers that depend on the chat-agent runtime.
        self.message_pair_patcher = patch(
            "products.posthog_ai.backend.api.serializers.load_conversation_message_pair",
            autospec=True,
        )
        self.baseline_patcher = patch(
            "products.posthog_ai.backend.api.serializers.generate_baseline_summary_for_message",
            autospec=True,
        )
        mock_load = self.message_pair_patcher.start()
        mock_baseline = self.baseline_patcher.start()
        from products.posthog_ai.backend.services.conversation_fork import ConversationMessagePair

        mock_load.return_value = ConversationMessagePair(
            question_text="What's our weekly activation rate?",
            visualization_title="Weekly activation funnel",
            visualization_message_dict={"id": str(self.visualization_message_id), "type": "ai/viz"},
            human_message_dict={"id": str(self.human_message_id), "content": "What's our weekly activation rate?"},
        )
        mock_baseline.return_value = "Baseline weekly activation is 41.3%."
        self.addCleanup(self.message_pair_patcher.stop)
        self.addCleanup(self.baseline_patcher.stop)

    def _payload(self, **overrides) -> dict:
        payload = {
            "conversation_id": str(self.conversation.id),
            "human_message_id": str(self.human_message_id),
            "visualization_message_id": str(self.visualization_message_id),
            "title": "Weekly activation",
            "cadence": "weekly",
        }
        payload.update(overrides)
        return payload

    def _url(self, suffix: str = "") -> str:
        base = f"/api/environments/{self.team.id}/posthog_ai/watched_questions/"
        return f"{base}{suffix}"

    def test_create_watched_question_enables_signal_source(self) -> None:
        response = self.client.post(self._url(), self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        tracked_question = TrackedQuestion.objects.get(id=response.data["id"])
        self.assertEqual(tracked_question.team, self.team)
        self.assertEqual(tracked_question.cadence, "weekly")
        self.assertEqual(tracked_question.status, TrackedQuestion.Status.ACTIVE)
        self.assertTrue(
            SignalSourceConfig.objects.filter(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.POSTHOG_AI,
                source_type=SignalSourceConfig.SourceType.QUESTION_DRIFT,
                enabled=True,
            ).exists()
        )

    def test_pause_and_resume(self) -> None:
        tracked_question = TrackedQuestion.objects.create(
            team=self.team,
            created_by=self.user,
            source_conversation=self.conversation,
            source_human_message_id=self.human_message_id,
            source_visualization_message_id=self.visualization_message_id,
            title="Weekly activation",
            question_text="What's our weekly activation rate?",
            baseline_summary="Baseline.",
            baseline_captured_at=timezone.now(),
            cadence="weekly",
            next_run_at=timezone.now() + timedelta(days=7),
        )

        pause_response = self.client.post(self._url(f"{tracked_question.id}/pause/"), {}, format="json")
        self.assertEqual(pause_response.status_code, status.HTTP_200_OK)
        tracked_question.refresh_from_db()
        self.assertEqual(tracked_question.status, TrackedQuestion.Status.PAUSED)

        resume_response = self.client.post(self._url(f"{tracked_question.id}/resume/"), {}, format="json")
        self.assertEqual(resume_response.status_code, status.HTTP_200_OK)
        tracked_question.refresh_from_db()
        self.assertEqual(tracked_question.status, TrackedQuestion.Status.ACTIVE)

    def test_archive_soft_delete(self) -> None:
        tracked_question = TrackedQuestion.objects.create(
            team=self.team,
            created_by=self.user,
            source_conversation=self.conversation,
            source_human_message_id=self.human_message_id,
            source_visualization_message_id=self.visualization_message_id,
            title="Activation",
            question_text="Q",
            baseline_summary="",
            baseline_captured_at=timezone.now(),
            cadence="weekly",
            next_run_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.delete(self._url(f"{tracked_question.id}/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        tracked_question.refresh_from_db()
        self.assertEqual(tracked_question.status, TrackedQuestion.Status.ARCHIVED)
