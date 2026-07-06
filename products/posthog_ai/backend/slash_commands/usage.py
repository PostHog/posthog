from django.utils import timezone

from asgiref.sync import sync_to_async
from posthoganalytics import capture_exception

from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.slash_commands.base import BaseSlashCommand
from products.posthog_ai.backend.slash_commands.usage_queries import (
    format_usage_message,
    get_ai_credits_for_conversation,
    get_ai_credits_for_team,
    get_ai_free_tier_credits,
    get_ai_usage_period,
    get_conversation_start_time,
)


class UsageCommand(BaseSlashCommand):
    """Shows PostHog AI credit usage for the current conversation and billing period."""

    name = "/usage"

    async def execute(self, arg: str) -> str:
        try:
            conversation_id = self._context.conversation_id

            conversation_start = await database_sync_to_async(get_conversation_start_time)(conversation_id)
            if not conversation_start:
                return "Unable to retrieve conversation start time."

            usage_period = await database_sync_to_async(get_ai_usage_period)(
                self._context.team, self._context.billing_context
            )

            # The sandbox runtime never stamps $ai_session_id, so per-conversation attribution is
            # structurally 0 — skip the query and omit the line rather than showing a misleading 0.
            conversation_credits = 0
            if self._context.conversation_attribution_available:
                conversation_credits = await sync_to_async(get_ai_credits_for_conversation, thread_sensitive=False)(
                    team_id=self._context.team.id,
                    conversation_id=conversation_id,
                    begin=conversation_start,
                    end=timezone.now(),
                )

            period_credits = (
                await sync_to_async(get_ai_credits_for_team, thread_sensitive=False)(
                    team_id=self._context.team.id,
                    begin=usage_period.query_start,
                    end=usage_period.end,
                )
                if usage_period.query_start < usage_period.end
                else 0
            )

            free_tier_credits = get_ai_free_tier_credits(self._context.team.id)

            return format_usage_message(
                conversation_credits=conversation_credits,
                period_credits=period_credits,
                free_tier_credits=free_tier_credits,
                conversation_start=conversation_start,
                usage_period=usage_period,
                include_conversation_line=self._context.conversation_attribution_available,
            )
        except Exception as e:
            capture_exception(e)
            raise Exception("PostHog AI usage information query failed. Please try again later.") from e
