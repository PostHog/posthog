import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

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

        topic = await sync_to_async(UserInterviewTopic.objects.get)(id=artifact["topic_id"])
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
    async def test_arun_impl_rejects_empty_topic(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="   ",
            interviewee_emails=["alex@example.com"],
        )

        assert "Topic is required" in content
        assert artifact["error"] == "validation_failed"
        assert not await sync_to_async(UserInterviewTopic.objects.filter(team=self.team).exists)()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_rejects_no_interviewees(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="Some topic",
            interviewee_emails=[],
            interviewee_distinct_ids=[],
        )

        assert "interviewee" in content.lower()
        assert artifact["error"] == "validation_failed"
        assert not await sync_to_async(UserInterviewTopic.objects.filter(team=self.team).exists)()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_rejects_invalid_emails(self):
        tool = self._tool()

        content, artifact = await tool._arun_impl(
            topic="Some topic",
            interviewee_emails=["not-an-email", "also bad"],
        )

        assert artifact["error"] == "validation_failed"
        assert "not-an-email" in content
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

        topic = await sync_to_async(UserInterviewTopic.objects.get)(id=artifact["topic_id"])
        assert topic.interviewee_emails == ["alex@example.com"]
        assert topic.interviewee_distinct_ids == ["user_1"]
        assert topic.questions == ["A real question?"]
