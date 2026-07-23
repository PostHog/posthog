"""Explicit chat-provider registry.

Kept as a literal dict on purpose — the provider set is small, PostHog-owned, and a new
entry should be a reviewed, deliberate addition rather than dynamic discovery.
"""

from typing import Any

from posthog.models.integration import Integration

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError, ChatThreadHandler
from products.slack_app.backend.providers.slack import SlackChatProvider
from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

_PROVIDERS: dict[str, type[ChatProvider]] = {SlackChatProvider.kind: SlackChatProvider}


def get_chat_provider(kind: str) -> type[ChatProvider]:
    try:
        return _PROVIDERS[kind]
    except KeyError:
        raise ChatProviderError(f"Unknown chat provider: {kind}")


def chat_provider_for_integration(integration: Integration) -> ChatProvider:
    for provider_cls in _PROVIDERS.values():
        if integration.kind in provider_cls.integration_kinds:
            return provider_cls(integration)
    raise ChatProviderError(f"No chat provider for integration kind: {integration.kind}")


def thread_handler_from_context(context: dict[str, Any]) -> ChatThreadHandler:
    """Build the thread handler for a serialized conversation context.

    Contexts persisted before a ``provider`` key existed are all Slack's, so a missing
    key dispatches to Slack — the contract new providers rely on when they start
    stamping their own key.
    """
    provider = context.get("provider", SlackChatProvider.kind)
    if provider != SlackChatProvider.kind:
        raise ChatProviderError(f"Unknown chat provider in thread context: {provider}")
    return SlackThreadHandler(SlackThreadContext.from_dict(context))
