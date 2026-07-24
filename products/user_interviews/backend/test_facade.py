from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.user_interviews.backend.facade.api import has_replied, parse_interviewee_identifier
from products.user_interviews.backend.facade.contracts import IntervieweeIdentity
from products.user_interviews.backend.logic import valid_distinct_id, valid_session_id
from products.user_interviews.backend.models import UserInterview, UserInterviewClassification, UserInterviewTopic


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


class TestLinkageValidation(SimpleTestCase):
    # A UUIDv7 (version nibble 7); a UUIDv4 for the wrong-version case.
    _V7 = "018f0b7a-0000-7000-8000-000000000000"
    _V4 = "018f0b7a-0000-4000-8000-000000000000"

    @parameterized.expand(
        [
            ("uuid_v7", _V7, _V7),
            ("uuid_v7_trimmed", f"  {_V7}  ", _V7),
            ("uuid_v4_wrong_version", _V4, ""),
            ("not_a_uuid", "session-123", ""),
            ("empty", "", ""),
            ("none", None, ""),
        ]
    )
    def test_valid_session_id(self, _name: str, value: object, expected: str) -> None:
        assert valid_session_id(value) == expected

    @parameterized.expand(
        [
            ("normal", "user_42", "user_42"),
            ("trimmed", "  user_42  ", "user_42"),
            ("illegal_sentinel", "anonymous", ""),
            ("illegal_case_insensitive", "ANONYMOUS", ""),
            ("illegal_after_trim", "  guest  ", ""),
            ("all_zero_uuid", "00000000-0000-0000-0000-000000000000", ""),
            ("empty", "", ""),
            ("none", None, ""),
            ("too_long", "x" * 201, ""),
            ("max_length_ok", "x" * 200, "x" * 200),
        ]
    )
    def test_valid_distinct_id(self, _name: str, value: object, expected: str) -> None:
        assert valid_distinct_id(value) == expected


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

    def test_abandoned_reply_does_not_count(self) -> None:
        # An accidental refresh mid-call leaves an abandoned partial behind. Treating that as
        # "replied" would lock the interviewee out of ever finishing — so it must not count.
        topic = self._create_topic()
        UserInterview.objects.create(
            team=self.team,
            created_by=self.user,
            interviewee_emails=["alex@example.com"],
            interviewee_identifier="alex@example.com",
            transcript="",
            topic=topic,
            classifications=[UserInterviewClassification.ABANDONED],
        )
        assert not has_replied(team_id=self.team.id, topic_id=topic.id, interviewee_identifier="alex@example.com")

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
