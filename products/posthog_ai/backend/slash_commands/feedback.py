import posthoganalytics

from products.posthog_ai.backend.slash_commands.base import BaseSlashCommand


class FeedbackCommand(BaseSlashCommand):
    """Captures user feedback about the PostHog AI experience as an `$ai_feedback` event."""

    name = "/feedback"

    async def execute(self, arg: str) -> str:
        feedback_content = arg.strip()

        if not feedback_content:
            return "Please provide your feedback for PostHog AI. Usage: `/feedback <your feedback>`"

        posthoganalytics.capture(
            distinct_id=str(self._context.user.distinct_id),
            event="$ai_feedback",
            properties={
                "$ai_feedback_text": feedback_content,
                "$ai_session_id": str(self._context.conversation_id),
                "$ai_trace_id": self._context.trace_id,
                "ai_product": "posthog_ai",
            },
        )

        return "Thanks for making PostHog AI better!"
