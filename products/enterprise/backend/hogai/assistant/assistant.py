from typing import Any, Optional
from uuid import UUID

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.models import Team, User

from products.enterprise.backend.hogai.assistant.base import BaseAssistant
from products.enterprise.backend.hogai.assistant.deep_research_assistant import DeepResearchAssistant
from products.enterprise.backend.hogai.assistant.insights_assistant import InsightsAssistant
from products.enterprise.backend.hogai.assistant.main_assistant import MainAssistant
from products.enterprise.backend.hogai.utils.types.base import AssistantMode
from products.enterprise.backend.hogai.utils.types.composed import AssistantMaxGraphState, AssistantMaxPartialGraphState
from products.enterprise.backend.models import Conversation


class Assistant:
    @classmethod
    def create(
        cls,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ) -> BaseAssistant:
        assistant_class: type[BaseAssistant]
        if mode == AssistantMode.ASSISTANT:
            assistant_class = MainAssistant
        elif mode == AssistantMode.INSIGHTS_TOOL:
            assistant_class = InsightsAssistant
        elif mode == AssistantMode.DEEP_RESEARCH:
            assistant_class = DeepResearchAssistant
        return assistant_class(
            team,
            conversation,
            new_message=new_message,
            user=user,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,  # type: ignore
        )
