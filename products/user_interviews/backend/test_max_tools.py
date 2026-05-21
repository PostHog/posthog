import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from products.user_interviews.backend.models import UserInterviewTopic

from .max_tools import CreateUserInterviewTopicTool


class TestCreateUserInterviewTopicTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _tool(self) -> CreateUserInterviewTopicTool:
        return CreateUserInterviewTopicTool(team=self.team, user=self.user, config=self._config)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success_with_emails(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="Onboarding experience",
            interviewee_emails=["alex@example.com", "Sam <sam@example.com>"],
            questions=[
                "What were you hoping to achieve when you signed up?",
                "Where did you get stuck during onboarding?",
                "What would have made the first 5 minutes easier?",
            ],
            agent_context="Focus on emotional friction, not feature requests.",
        )

        assert "Created interview topic" in content
        assert artifact["topic"] == "Onboarding experience"
        assert artifact["interviewee_email_count"] == 2
        assert artifact["interviewee_distinct_id_count"] == 0
        assert artifact["question_count"] == 3

        topic = await sync_to_async(
            lambda: UserInterviewTopic.objects.select_related("team", "created_by").get(
                team=self.team, id=artifact["topic_id"]
            )
        )()
        assert topic.team == self.team
        assert topic.created_by == self.user
        assert topic.interviewee_emails == ["alex@example.com", "Sam <sam@example.com>"]
        assert topic.interviewee_distinct_ids == []
        assert len(topic.questions) == 3
        assert topic.agent_context == "Focus on emotional friction, not feature requests."

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success_with_distinct_ids_only(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="Power user dashboard usage",
            interviewee_distinct_ids=["user_123", "user_456"],
            questions=["How do you currently use dashboards?"],
        )

        assert "Created interview topic" in content
        assert artifact["interviewee_email_count"] == 0
        assert artifact["interviewee_distinct_id_count"] == 2

    @pytest.mark.django_db
    @pytest.mark.asyncio
    @parameterized.expand(
        [
            (
                "empty_topic",
                {"topic": "   ", "interviewee_emails": ["alex@example.com"]},
                "topic is required",
            ),
            (
                "no_interviewees",
                {"topic": "Some topic", "interviewee_emails": [], "interviewee_distinct_ids": []},
                "interviewee",
            ),
            (
                "invalid_emails",
                {
                    "topic": "Some topic",
                    "interviewee_emails": ["not-an-email", "also bad"],
                    "questions": ["A question?"],
                },
                "not-an-email",
            ),
            (
                "no_questions",
                {"topic": "Some topic", "interviewee_emails": ["alex@example.com"], "questions": []},
                "question",
            ),
        ]
    )
    async def test_arun_impl_rejects_invalid_input(self, _name, kwargs, expected_content_fragment):
        tool = self._tool()

        content, artifact = await tool._arun_impl(**kwargs)

        assert artifact["error"] == "validation_failed"
        assert expected_content_fragment in content.lower()
        assert not await sync_to_async(UserInterviewTopic.objects.filter(team=self.team).exists)()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_strips_blank_entries(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="Some topic",
            interviewee_emails=["alex@example.com", "  ", ""],
            interviewee_distinct_ids=["", "user_1"],
            questions=["A real question?", "  ", ""],
        )

        assert artifact["interviewee_email_count"] == 1
        assert artifact["interviewee_distinct_id_count"] == 1
        assert artifact["question_count"] == 1

        topic = await sync_to_async(lambda: UserInterviewTopic.objects.get(team=self.team, id=artifact["topic_id"]))()
        assert topic.interviewee_emails == ["alex@example.com"]
        assert topic.interviewee_distinct_ids == ["user_1"]
        assert topic.questions == ["A real question?"]
