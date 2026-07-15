from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.user_interviews.backend.models import UserInterviewTopic

SENSITIVE_LIST_FIELDS = (
    "interviewee_emails",
    "interviewee_distinct_ids",
    "agent_context",
    "questions",
    "invite_subject",
    "invite_message",
)


class TestUserInterviewTopicListSummary(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.topic = UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            topic="Session replay adoption",
            interviewee_emails=["jordan@example.com", "sam@example.com"],
            interviewee_distinct_ids=["distinct-1"],
            agent_context="Be warm and curious",
            questions=["What blocks adoption?", "What would help?"],
            invite_subject="Chat about replay?",
            invite_message="We'd love your input",
        )

    def _topics_url(self) -> str:
        return f"/api/projects/{self.team.id}/user_interview_topics/"

    def test_list_returns_summary_without_sensitive_fields(self) -> None:
        response = self.client.get(self._topics_url())
        assert response.status_code == status.HTTP_200_OK, response.content
        [row] = response.json()["results"]
        for leaked in SENSITIVE_LIST_FIELDS:
            assert leaked not in row, f"{leaked} leaked in topics list response"
        assert row["interviewee_email_count"] == 2
        assert row["interviewee_distinct_id_count"] == 1
        assert row["question_count"] == 2

    def test_retrieve_still_returns_full_targeting_and_agent_config(self) -> None:
        response = self.client.get(f"{self._topics_url()}{self.topic.id}/")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["interviewee_emails"] == ["jordan@example.com", "sam@example.com"]
        assert body["interviewee_distinct_ids"] == ["distinct-1"]
        assert body["agent_context"] == "Be warm and curious"
        assert body["questions"] == ["What blocks adoption?", "What would help?"]
