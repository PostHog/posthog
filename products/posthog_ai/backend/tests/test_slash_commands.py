from datetime import UTC, datetime
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.slash_commands.base import SlashCommandContext, TranscriptMessage
from products.posthog_ai.backend.slash_commands.feedback import FeedbackCommand
from products.posthog_ai.backend.slash_commands.registry import (
    FeedbackCommand as RegistryFeedbackCommand,
    TicketCommand as RegistryTicketCommand,
    UsageCommand as RegistryUsageCommand,
    match_slash_command,
)
from products.posthog_ai.backend.slash_commands.transcripts import RunLogTranscriptSource
from products.posthog_ai.backend.slash_commands.usage import UsageCommand
from products.posthog_ai.backend.slash_commands.usage_queries import AiUsagePeriod

USAGE_MOD = "products.posthog_ai.backend.slash_commands.usage"
TRANSCRIPTS_MOD = "products.posthog_ai.backend.slash_commands.transcripts"


class TestSlashCommandRegistry(BaseTest):
    @parameterized.expand(
        [
            ("exact_usage", "/usage", RegistryUsageCommand, ""),
            ("usage_ignores_trailing", "  /usage  ", RegistryUsageCommand, ""),
            ("feedback_with_arg", "/feedback great stuff", RegistryFeedbackCommand, "great stuff"),
            ("ticket_with_arg", "/ticket my printer broke", RegistryTicketCommand, "my printer broke"),
            ("ticket_exact", "/ticket", RegistryTicketCommand, ""),
        ]
    )
    def test_match_returns_handler_and_arg(self, _name, content, expected_cls, expected_arg):
        match = match_slash_command(content)
        assert match is not None
        handler, arg = match
        self.assertIs(handler, expected_cls)
        self.assertEqual(arg, expected_arg)

    @parameterized.expand(
        [
            ("unknown_command", "/foo bar"),
            ("prefix_without_space", "/usagex"),
            ("plain_text", "how do I create an insight"),
            ("empty", "   "),
        ]
    )
    def test_match_falls_through(self, _name, content):
        self.assertIsNone(match_slash_command(content))


class TestUsageCommandCore(BaseTest):
    def _run(self, attribution_available: bool) -> str:
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        context = SlashCommandContext(
            team=self.team,
            user=self.user,
            conversation_id=conversation.id,
            conversation_attribution_available=attribution_available,
        )
        period = AiUsagePeriod(
            label="Past 30 days",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, tzinfo=UTC),
            query_start=datetime(2026, 5, 1, tzinfo=UTC),
        )
        with (
            patch(f"{USAGE_MOD}.get_ai_usage_period", return_value=period),
            patch(f"{USAGE_MOD}.get_ai_credits_for_conversation", return_value=25) as mock_conversation_credits,
            patch(f"{USAGE_MOD}.get_ai_credits_for_team", return_value=300),
            patch(f"{USAGE_MOD}.get_ai_free_tier_credits", return_value=2000),
        ):
            content = async_to_sync(UsageCommand(context).execute)("")
        self._mock_conversation_credits = mock_conversation_credits
        return content

    def test_omits_conversation_line_and_skips_query_when_attribution_unavailable(self):
        content = self._run(attribution_available=False)
        # The bolded credit line is gone; the footer's "Current conversation resets…" note stays.
        self.assertNotIn("**Current conversation**", content)
        self.assertIn("Past 30 days", content)
        self._mock_conversation_credits.assert_not_called()

    def test_includes_conversation_line_and_runs_query_when_attribution_available(self):
        content = self._run(attribution_available=True)
        self.assertIn("**Current conversation**: 25 credits", content)
        self._mock_conversation_credits.assert_called_once()


class TestFeedbackCommandCore(BaseTest):
    @patch("products.posthog_ai.backend.slash_commands.feedback.posthoganalytics.capture")
    def test_captures_feedback_with_conversation_and_trace_ids(self, mock_capture):
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        context = SlashCommandContext(
            team=self.team,
            user=self.user,
            conversation_id=conversation.id,
            trace_id="trace-xyz",
            conversation_attribution_available=False,
        )
        content = async_to_sync(FeedbackCommand(context).execute)("this is great")

        self.assertEqual(content, "Thanks for making PostHog AI better!")
        mock_capture.assert_called_once_with(
            distinct_id=str(self.user.distinct_id),
            event="$ai_feedback",
            properties={
                "$ai_feedback_text": "this is great",
                "$ai_session_id": str(conversation.id),
                "$ai_trace_id": "trace-xyz",
                "ai_product": "posthog_ai",
            },
        )

    @patch("products.posthog_ai.backend.slash_commands.feedback.posthoganalytics.capture")
    def test_empty_feedback_returns_usage_prompt_without_capturing(self, mock_capture):
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        context = SlashCommandContext(team=self.team, user=self.user, conversation_id=conversation.id)
        content = async_to_sync(FeedbackCommand(context).execute)("")

        self.assertIn("Please provide your feedback", content)
        mock_capture.assert_not_called()


class _FakeRun:
    """Single-run resume chain over an in-memory log — avoids standing up a Task + S3 object."""

    def __init__(self, log_url: str) -> None:
        self.log_url = log_url

    def get_resume_chain(self) -> list["_FakeRun"]:
        return [self]


class TestRunLogTranscriptSource(BaseTest):
    def _fetch(self, log_content: str) -> list[TranscriptMessage]:
        run = _FakeRun("logs/run.ndjson")
        with patch(f"{TRANSCRIPTS_MOD}.object_storage.read", return_value=log_content):
            return async_to_sync(RunLogTranscriptSource(cast(Any, run)).fetch)()

    def test_reads_user_and_assistant_turns_stripping_context_wrapper(self):
        log = "\n".join(
            [
                '{"notification": {"method": "_posthog/user_message", "params": {"content": "<posthog_context>ctx</posthog_context>\\nHow do funnels work?"}}}',
                '{"notification": {"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message", "content": {"text": "Funnels track conversion."}}}}}',
                '{"notification": {"method": "_posthog/console", "params": {"message": "debug noise"}}}',
            ]
        )
        transcript = self._fetch(log)

        self.assertEqual(
            transcript,
            [
                TranscriptMessage(role="user", content="How do funnels work?"),
                TranscriptMessage(role="assistant", content="Funnels track conversion."),
            ],
        )

    def test_empty_log_yields_empty_transcript(self):
        self.assertEqual(self._fetch(""), [])
