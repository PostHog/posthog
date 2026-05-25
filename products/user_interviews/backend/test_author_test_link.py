from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend.models import IntervieweeContext, UserInterview, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestAuthorTestLink(_FeatureFlagEnabledMixin):
    def _topics_url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/"

    def _test_link_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/test_link/"

    def _create_topic_via_api(self, **overrides) -> UserInterviewTopic:
        payload = {
            "topic": "Session replay adoption",
            "interviewee_emails": ["jordan@example.com"],
            "interviewee_distinct_ids": [],
            "questions": ["What blocks adoption?"],
            **overrides,
        }
        response = self.client.post(self._topics_url(), payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return UserInterviewTopic.objects.get(id=response.json()["id"])

    def test_topic_creation_does_not_eagerly_seed_author_context(self) -> None:
        topic = self._create_topic_via_api()
        assert not IntervieweeContext.objects.filter(topic=topic).exists()
        assert self.user.email not in topic.interviewee_emails
        assert self.user.email not in topic.interviewee_distinct_ids

    def test_test_link_materializes_author_context_and_share(self) -> None:
        topic = self._create_topic_via_api()

        response = self.client.post(self._test_link_url(str(topic.id)))

        assert response.status_code == status.HTTP_200_OK, response.content
        ic = IntervieweeContext.objects.get(topic=topic, interviewee_identifier=self.user.email)
        assert ic.created_by_id == self.user.id
        assert SharingConfiguration.objects.filter(team=self.team, interviewee_context=ic, enabled=True).exists()

    def test_test_link_returns_url_and_no_latest_when_no_interviews(self) -> None:
        topic = self._create_topic_via_api()

        response = self.client.post(self._test_link_url(str(topic.id)))

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert "/interview/" in body["interview_url"]
        assert body["latest_test_interview"] is None

    def test_test_link_is_idempotent(self) -> None:
        topic = self._create_topic_via_api()
        first = self.client.post(self._test_link_url(str(topic.id))).json()
        second = self.client.post(self._test_link_url(str(topic.id))).json()
        assert first["interview_url"] == second["interview_url"]
        assert IntervieweeContext.objects.filter(topic=topic, interviewee_identifier=self.user.email).count() == 1
        assert (
            SharingConfiguration.objects.filter(
                team=self.team,
                interviewee_context__topic=topic,
                interviewee_context__interviewee_identifier=self.user.email,
            ).count()
            == 1
        )

    def test_test_link_uses_topic_creator_not_request_user(self) -> None:
        topic = self._create_topic_via_api()
        other_user = self._create_user("other@example.com")
        self.client.force_login(other_user)

        response = self.client.post(self._test_link_url(str(topic.id)))

        assert response.status_code == status.HTTP_200_OK, response.content
        contexts = IntervieweeContext.objects.filter(topic=topic)
        assert contexts.count() == 1
        assert contexts.get().interviewee_identifier == self.user.email

    def test_test_link_surfaces_latest_test_interview(self) -> None:
        topic = self._create_topic_via_api()
        self.client.post(self._test_link_url(str(topic.id)))
        ic = IntervieweeContext.objects.get(topic=topic, interviewee_identifier=self.user.email)
        UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            topic=topic,
            interviewee_identifier=ic.interviewee_identifier,
            transcript="hello",
            summary="said hello",
        )

        response = self.client.post(self._test_link_url(str(topic.id)))

        assert response.status_code == status.HTTP_200_OK, response.content
        latest = response.json()["latest_test_interview"]
        assert latest is not None
        assert latest["transcript"] == "hello"
        assert latest["summary"] == "said hello"
