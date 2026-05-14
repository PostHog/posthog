from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.user_interviews.backend.models import UserInterview, UserInterviewTopic


class TestUserInterviewsListFilters(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _list_url(self, team: Team | None = None) -> str:
        return f"/api/environments/{(team or self.team).id}/user_interviews/"

    def _create_topic(self, topic_text: str, team: Team | None = None) -> UserInterviewTopic:
        return UserInterviewTopic.objects.create(
            team=team or self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic=topic_text,
        )

    def _create_interview(
        self, *, topic: UserInterviewTopic | None, summary: str, team: Team | None = None
    ) -> UserInterview:
        return UserInterview.objects.create(
            team=team or self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            transcript="Hello world",
            summary=summary,
            topic=topic,
        )

    @parameterized.expand(
        [
            ("no filter returns all interviews", None, {"A1", "A2", "B1", "orphan"}),
            ("topic A filter narrows to that topic", "topic_a", {"A1", "A2"}),
            ("topic B filter narrows to that topic", "topic_b", {"B1"}),
            ("topic with zero interviews returns empty set", "topic_c", set()),
        ]
    )
    def test_topic_filter(self, _name: str, filter_topic_key: str | None, expected_summaries: set[str]) -> None:
        topic_a = self._create_topic("Topic A")
        topic_b = self._create_topic("Topic B")
        topic_c = self._create_topic("Topic C")
        self._create_interview(topic=topic_a, summary="A1")
        self._create_interview(topic=topic_a, summary="A2")
        self._create_interview(topic=topic_b, summary="B1")
        self._create_interview(topic=None, summary="orphan")

        params = (
            {}
            if filter_topic_key is None
            else {"topic": str({"topic_a": topic_a.id, "topic_b": topic_b.id, "topic_c": topic_c.id}[filter_topic_key])}
        )
        response = self.client.get(self._list_url(), params)

        assert response.status_code == status.HTTP_200_OK, response.content
        summaries = {row["summary"] for row in response.json()["results"]}
        assert summaries == expected_summaries

    def test_list_does_not_leak_interviews_across_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        other_topic = self._create_topic("Other team topic", team=other_team)
        self._create_interview(topic=other_topic, summary="other-team-secret", team=other_team)
        own_topic = self._create_topic("Own topic")
        self._create_interview(topic=own_topic, summary="own-team-summary")

        plain_list = self.client.get(self._list_url())
        assert plain_list.status_code == status.HTTP_200_OK, plain_list.content
        summaries = {row["summary"] for row in plain_list.json()["results"]}
        assert summaries == {"own-team-summary"}

        filtered_by_other_team_topic = self.client.get(self._list_url(), {"topic": str(other_topic.id)})
        assert filtered_by_other_team_topic.status_code == status.HTTP_200_OK, filtered_by_other_team_topic.content
        assert filtered_by_other_team_topic.json()["results"] == []

    def test_retrieve_returns_full_transcript_and_summary(self) -> None:
        topic = self._create_topic("Topic A")
        interview = self._create_interview(topic=topic, summary="Full summary text")

        response = self.client.get(f"{self._list_url()}{interview.id}/")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["summary"] == "Full summary text"
        assert body["transcript"] == "Hello world"
        assert body["topic"] == str(topic.id)
