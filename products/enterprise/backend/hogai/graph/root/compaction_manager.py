import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, HumanMessage

from posthog.sync import database_sync_to_async

from products.enterprise.backend.hogai.utils.helpers import (
    find_start_message,
    find_start_message_idx,
    insert_messages_before_start,
)
from products.enterprise.backend.hogai.utils.types import AssistantMessageUnion

if TYPE_CHECKING:
    pass

T = TypeVar("T", bound=AssistantMessageUnion)

LangchainTools = Sequence[dict[str, Any] | type | Callable | BaseTool]


class InsertionResult(BaseModel):
    messages: Sequence[AssistantMessageUnion]
    updated_start_id: str
    updated_window_start_id: str


class ConversationCompactionManager(ABC):
    """
    Manages conversation window boundaries, message filtering, and summarization decisions.
    """

    CONVERSATION_WINDOW_SIZE = 64000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """
    APPROXIMATE_TOKEN_LENGTH = 4
    """
    Determines the approximate number of characters per token.
    """

    def find_window_boundary(self, messages: Sequence[T], max_messages: int = 10, max_tokens: int = 1000) -> str | None:
        """
        Find the optimal window start ID based on message count and token limits.
        Ensures the window starts at a human or assistant message.
        """

        new_window_id: str | None = None
        for message in reversed(messages):
            # Handle limits before assigning the window ID.
            max_tokens -= self._get_estimated_tokens(message)
            max_messages -= 1
            if max_tokens < 0 or max_messages < 0:
                break

            # Assign the new new window ID.
            if message.id is not None:
                if isinstance(message, HumanMessage):
                    new_window_id = message.id
                if isinstance(message, AssistantMessage):
                    new_window_id = message.id

        return new_window_id

    def get_messages_in_window(self, messages: Sequence[T], window_start_id: str | None = None) -> Sequence[T]:
        """
        Filter messages to only those within the conversation window.
        """
        if window_start_id is not None:
            return self._get_conversation_window(messages, window_start_id)
        return messages

    async def should_compact_conversation(
        self, model: BaseChatModel, messages: list[BaseMessage], tools: LangchainTools | None = None, **kwargs
    ) -> bool:
        """
        Determine if the conversation should be summarized based on token count.
        Avoids summarizing if there are only two human messages or fewer.
        """
        # Avoid summarizing the conversation if there is only two human messages.
        human_messages = [message for message in messages if isinstance(message, LangchainHumanMessage)]
        if len(human_messages) <= 2:
            return False
        token_count = await self._get_token_count(model, messages, tools, **kwargs)
        return token_count > self.CONVERSATION_WINDOW_SIZE

    def update_window(
        self, messages: Sequence[T], summary_message: ContextMessage, start_id: str | None = None
    ) -> InsertionResult:
        """Finds the optimal position to insert the summary message in the conversation window."""
        window_start_id_candidate = self.find_window_boundary(messages, max_messages=16, max_tokens=2048)
        start_message = find_start_message(messages, start_id)
        if not start_message:
            raise ValueError("Start message not found")

        start_message_copy = start_message.model_copy(deep=True)
        start_message_copy.id = str(uuid4())

        # The last messages were too large to fit into the window. Copy the last human message to the start of the window.
        if not window_start_id_candidate:
            return InsertionResult(
                messages=[*messages, summary_message, start_message_copy],
                updated_start_id=start_message_copy.id,
                updated_window_start_id=summary_message.id,
            )

        # Find the updated window
        start_message_idx = find_start_message_idx(messages, window_start_id_candidate)
        new_window = messages[start_message_idx:]

        # If the start human message is in the window, insert the summary message before it
        # and update the window start.
        if next((m for m in new_window if m.id == start_id), None):
            updated_messages = insert_messages_before_start(messages, [summary_message], start_id=start_id)
            return InsertionResult(
                messages=updated_messages,
                updated_start_id=start_id,
                updated_window_start_id=window_start_id_candidate,
            )

        # If the start message is not in the window, insert the summary message and human message at the start of the window.
        updated_messages = insert_messages_before_start(
            new_window, [summary_message, start_message_copy], start_id=window_start_id_candidate
        )
        return InsertionResult(
            messages=updated_messages,
            updated_start_id=start_message_copy.id,
            updated_window_start_id=window_start_id_candidate,
        )

    def _get_estimated_tokens(self, message: AssistantMessageUnion) -> int:
        """
        Estimate token count for a message using character/4 heuristic.
        """
        char_count = 0
        if isinstance(message, HumanMessage):
            char_count = len(message.content)
        elif isinstance(message, AssistantMessage):
            char_count = len(message.content) + sum(
                len(json.dumps(m.args, separators=(",", ":"))) for m in message.tool_calls or []
            )
        elif isinstance(message, AssistantToolCallMessage):
            char_count = len(message.content)
        return round(char_count / self.APPROXIMATE_TOKEN_LENGTH)

    def _get_conversation_window(self, messages: Sequence[T], start_id: str) -> Sequence[T]:
        """
        Get messages from the start_id onwards.
        """
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages

    @abstractmethod
    async def _get_token_count(
        self,
        model: Any,
        messages: list[BaseMessage],
        tools: LangchainTools | None = None,
        thinking_config: dict[str, Any] | None = None,
        **kwargs,
    ) -> int:
        raise NotImplementedError


class AnthropicConversationCompactionManager(ConversationCompactionManager):
    async def _get_token_count(
        self,
        model: ChatAnthropic,
        messages: list[BaseMessage],
        tools: LangchainTools | None = None,
        thinking_config: dict[str, Any] | None = None,
        **kwargs,
    ) -> int:
        return await database_sync_to_async(model.get_num_tokens_from_messages, thread_sensitive=False)(
            messages, thinking=thinking_config, tools=tools
        )
