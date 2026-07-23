"""Chat provider seam: the interface (``base``), implementations (``slack``), and the
registry that maps provider kinds and Integration rows onto implementations."""

from products.slack_app.backend.providers.base import (
    ChatProvider,
    ChatProviderError,
    ChatThreadHandler,
    ConversationRef,
)
from products.slack_app.backend.providers.registry import (
    chat_provider_for_integration,
    get_chat_provider,
    thread_handler_from_context,
)
from products.slack_app.backend.providers.slack import SlackChatProvider
from products.slack_app.backend.providers.telegram import TelegramChatProvider

__all__ = [
    "ChatProvider",
    "ChatProviderError",
    "ChatThreadHandler",
    "ConversationRef",
    "SlackChatProvider",
    "TelegramChatProvider",
    "chat_provider_for_integration",
    "get_chat_provider",
    "thread_handler_from_context",
]
