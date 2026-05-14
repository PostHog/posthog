from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.user_interviews.backend.models import UserInterview, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestUserInterviewsListFilters(_FeatureFlagEnabledMixin):
    def _list_url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interviews/"

    def _create_topic(self, topic_text: str) -> UserInterviewTopic:
        return UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic=topic_text,
        )

    def _create_interview(self, *, topic: UserInterviewTopic | None, summary: str) -> UserInterview:
        return UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            transcript="Hello world",
            summary=summary,
            topic=topic,
        )

    def test_list_returns_all_interviews_when_no_topic_filter(self) -> None:
        topic_a = self._create_topic("Topic A")
        topic_b = self._create_topic("Topic B")
        self._create_interview(topic=topic_a, summary="A1")
        self._create_interview(topic=topic_b, summary="B1")
        self._create_interview(topic=None, summary="orphan")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK, response.content
        summaries = {row["summary"] for row in response.json()["results"]}
        assert summaries == {"A1", "B1", "orphan"}

    def test_list_filters_by_topic_uuid(self) -> None:
        topic_a = self._create_topic("Topic A")
        topic_b = self._create_topic("Topic B")
        self._create_interview(topic=topic_a, summary="A1")
        self._create_interview(topic=topic_a, summary="A2")
        self._create_interview(topic=topic_b, summary="B1")
        self._create_interview(topic=None, summary="orphan")

        response = self.client.get(self._list_url(), {"topic": str(topic_a.id)})

        assert response.status_code == status.HTTP_200_OK, response.content
        summaries = {row["summary"] for row in response.json()["results"]}
        assert summaries == {"A1", "A2"}

    def test_list_filters_to_empty_when_topic_has_no_interviews(self) -> None:
        topic_a = self._create_topic("Topic A")
        topic_b = self._create_topic("Topic B")
        self._create_interview(topic=topic_a, summary="A1")

        response = self.client.get(self._list_url(), {"topic": str(topic_b.id)})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["results"] == []

    def test_retrieve_returns_full_transcript_and_summary(self) -> None:
        topic = self._create_topic("Topic A")
        interview = self._create_interview(topic=topic, summary="Full summary text")

        response = self.client.get(f"{self._list_url()}{interview.id}/")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["summary"] == "Full summary text"
        assert body["transcript"] == "Hello world"
        assert body["topic"] == str(topic.id)
