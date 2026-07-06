from collections.abc import Sequence

from django.conf import settings
from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.messages import (
    AIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)

from products.posthog_ai.backend.slash_commands.base import BaseSlashCommand, TranscriptMessage
from products.posthog_ai.backend.slash_commands.ticket_prompts import (
    SUPPORT_SUMMARIZER_SYSTEM_PROMPT,
    SUPPORT_SUMMARIZER_USER_PROMPT,
)

from ee.hogai.llm import MaxChatAnthropic


class TicketCommand(BaseSlashCommand):
    """Summarizes the conversation for the frontend to use when creating a support ticket."""

    name = "/ticket"

    async def _is_organization_new(self) -> bool:
        """Check if the organization was created less than 3 months ago."""
        # `organization` is an FK access that hits the DB when not prefetched, so it must be wrapped
        # to be safe inside this async context.
        org_created_at = await sync_to_async(lambda: self._context.team.organization.created_at)()
        if not org_created_at:
            return False
        months_since_creation = (timezone.now() - org_created_at).days / 30
        return months_since_creation < 3

    async def _can_create_ticket(self) -> bool:
        """Check if the organization's subscription allows ticket creation."""
        # Enable ticket creation in local dev
        if settings.DEBUG:
            return True

        if await self._is_organization_new():
            return True

        return await self._has_paid_plan_or_active_trial()

    async def _has_paid_plan_or_active_trial(self) -> bool:
        """
        Check the plan tier derived from the organization's synced billing entitlements.

        `available_product_features` is kept up to date by every billing load, and active
        trials grant the trial plan's features, so a non-free tier means a paid or custom
        subscription or an active trial. Reading it locally keeps the slow billing service
        API out of the conversation turn. Organizations with no synced entitlements are
        denied, so missing data fails closed.
        """
        # `organization` is an FK access that hits the DB when not prefetched, so it must be wrapped
        # to be safe inside this async context.
        return await sync_to_async(lambda: self._context.team.organization.get_plan_tier() != "free")()

    async def execute(self, arg: str) -> str:
        if not await self._can_create_ticket():
            return "The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help. If your issue is about billing, you can always contact our support team through the in-app help panel."

        transcript = await self._transcript_source.fetch() if self._transcript_source is not None else []

        if not transcript:
            return "I'll help you create a support ticket. Please describe your issue below."

        return await self._summarize_conversation(transcript)

    def _get_model(self) -> MaxChatAnthropic:
        # We are not billing for conversation summary since we would be billing per-ticket creation.
        return MaxChatAnthropic(
            model="claude-haiku-4-5",
            streaming=True,
            stream_usage=True,
            user=self._context.user,
            team=self._context.team,
            max_tokens=2048,
            billable=False,
        )

    async def _summarize_conversation(self, transcript: Sequence[TranscriptMessage]) -> str:
        """Summarize the conversation for the support ticket."""
        summarization_header = "PostHog AI Support Ticket Summary"
        messages_list: list[SystemMessage | LangchainHumanMessage | AIMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT)
        ]

        for msg in transcript:
            if msg.role == "user":
                messages_list.append(LangchainHumanMessage(content=msg.content))
            elif msg.role == "assistant" and msg.content:
                messages_list.append(AIMessage(content=msg.content))

        messages_list.append(LangchainHumanMessage(content=SUPPORT_SUMMARIZER_USER_PROMPT))

        response = await self._get_model().ainvoke(messages_list)
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        return f"{summarization_header}:\n\n{content}"
