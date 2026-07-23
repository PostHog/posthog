"""Chat provider seam: the interface (``base``), implementations (``slack``), and the
registry that maps provider kinds and Integration rows onto implementations."""

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError, ConversationRef
from products.slack_app.backend.providers.registry import chat_provider_for_integration, get_chat_provider
from products.slack_app.backend.providers.slack import SlackChatProvider

__all__ = [
    "ChatProvider",
    "ChatProviderError",
    "ConversationRef",
    "SlackChatProvider",
    "chat_provider_for_integration",
    "get_chat_provider",
]
