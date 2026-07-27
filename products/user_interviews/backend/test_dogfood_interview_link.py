from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.sharing_configuration import SharingConfiguration

from products.user_interviews.backend.models import IntervieweeContext, UserInterview, UserInterviewTopic


class _FeatureFlagEnabledMixin(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestDogfoodInterviewLink(_FeatureFlagEnabledMixin):
    def _topics_url(self) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/"

    def _test_link_url(self, topic_id: str) -> str:
        return f"/api/environments/{self.team.id}/user_interview_topics/{topic_id}/test_link/"

    def _create_topic(self) -> UserInterviewTopic:
        response = self.client.post(
            self._topics_url(),
            {
                "topic": "Session replay adoption",
                "interviewee_emails": ["jordan@example.com"],
                "interviewee_distinct_ids": [],
                "questions": ["What blocks adoption?"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return UserInterviewTopic.objects.get(team=self.team, id=response.json()["id"])

    def test_topic_creation_does_not_eagerly_seed_dogfood_context(self) -> None:
        topic = self._create_topic()
        assert not IntervieweeContext.objects.filter(team=self.team, topic=topic).exists()

    def test_test_link_materializes_caller_context_and_share(self) -> None:
        topic = self._create_topic()

        response = self.client.get(self._test_link_url(str(topic.id)))

        assert response.status_code == status.HTTP_200_OK, response.content
        ic = IntervieweeContext.objects.get(team=self.team, topic=topic, interviewee_identifier=self.user.email)
        assert ic.created_by_id == self.user.id
        assert SharingConfiguration.objects.filter(team=self.team, interviewee_context=ic, enabled=True).exists()

    def test_test_link_is_idempotent(self) -> None:
        topic = self._create_topic()
        first = self.client.get(self._test_link_url(str(topic.id))).json()
        second = self.client.get(self._test_link_url(str(topic.id))).json()
        assert first["interview_url"] == second["interview_url"]
        assert (
            IntervieweeContext.objects.filter(
                team=self.team, topic=topic, interviewee_identifier=self.user.email
            ).count()
            == 1
        )
        assert (
            SharingConfiguration.objects.filter(
                team=self.team,
                interviewee_context__topic=topic,
                interviewee_context__interviewee_identifier=self.user.email,
            ).count()
            == 1
        )

    def test_each_caller_gets_their_own_dogfood_context(self) -> None:
        topic = self._create_topic()
        first_response = self.client.get(self._test_link_url(str(topic.id))).json()

        other_user = self._create_user("other@example.com")
        self.client.force_login(other_user)
        second_response = self.client.get(self._test_link_url(str(topic.id))).json()

        assert first_response["interview_url"] != second_response["interview_url"]
        identifiers = set(
            IntervieweeContext.objects.filter(team=self.team, topic=topic).values_list(
                "interviewee_identifier", flat=True
            )
        )
        assert identifiers == {self.user.email, other_user.email}

    @parameterized.expand(
        [
            ("no_interview", None, None, None),
            ("transcript_only", "hello", "", "hello"),
            ("summary_only", "", "said hello", ""),
            ("both", "hello", "said hello", "hello"),
        ]
    )
    def test_test_link_surfaces_latest_test_interview(
        self,
        _name: str,
        transcript: str | None,
        summary: str | None,
        expected_transcript: str | None,
    ) -> None:
        topic = self._create_topic()
        # First call materializes the dogfood context so we have an identifier to attach an interview to.
        self.client.get(self._test_link_url(str(topic.id)))
        if transcript is not None:
            UserInterview.objects.create(
                team=self.team,
                created_by=self.user,
                topic=topic,
                interviewee_identifier=self.user.email,
                transcript=transcript,
                summary=summary or "",
            )

        latest = self.client.get(self._test_link_url(str(topic.id))).json()["latest_test_interview"]

        if transcript is None:
            assert latest is None
        else:
            assert latest is not None
            assert latest["transcript"] == expected_transcript
            assert latest["summary"] == (summary or "")
