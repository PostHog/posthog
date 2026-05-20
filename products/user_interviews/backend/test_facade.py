from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.user_interviews.backend.facade.api import has_replied, parse_interviewee_identifier
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity
from products.user_interviews.backend.models import UserInterview, UserInterviewTopic


class TestParseIntervieweeIdentifier(APIBaseTest):
    @parameterized.expand(
        [
            ("display+email", "Alex Smith <alex@example.com>", "Alex Smith", "alex@example.com"),
            ("display+email_whitespace", "  Alex  <alex@example.com>  ", "Alex", "alex@example.com"),
            ("plain_email", "alex.smith@example.com", "Alex Smith", "alex.smith@example.com"),
            ("plain_email_with_underscores", "alex_smith@example.com", "Alex Smith", "alex_smith@example.com"),
            ("distinct_id", "user_abc_123", "user_abc_123", None),
        ]
    )
    def test_parses_identifier(self, _: str, identifier: str, expected_name: str, expected_email: str | None) -> None:
        assert parse_interviewee_identifier(identifier) == IntervieweeIdentity(
            display_name=expected_name, email=expected_email
        )


class TestHasReplied(APIBaseTest):
    def _create_topic(self) -> UserInterviewTopic:
        return UserInterviewTopic.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            topic="MCP usage",
        )

    def test_false_when_no_reply(self) -> None:
        topic = self._create_topic()
        assert not has_replied(team_id=self.team.id, topic_id=topic.id, interviewee_identifier="alex@example.com")

    def test_true_when_reply_exists(self) -> None:
        topic = self._create_topic()
        UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            interviewee_identifier="alex@example.com",
            transcript="hi",
            summary="hi",
            topic=topic,
        )
        assert has_replied(team_id=self.team.id, topic_id=topic.id, interviewee_identifier="alex@example.com")

    def test_scoped_by_team(self) -> None:
        topic = self._create_topic()
        other_team = self.organization.teams.create(name="other team")
        UserInterview.objects.create(
            team=topic.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            interviewee_identifier="alex@example.com",
            transcript="hi",
            summary="hi",
            topic=topic,
        )
        assert not has_replied(team_id=other_team.id, topic_id=topic.id, interviewee_identifier="alex@example.com")
