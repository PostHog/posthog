"""Explicit chat-provider registry.

Kept as a literal dict on purpose — the provider set is small, PostHog-owned, and a new
entry should be a reviewed, deliberate addition rather than dynamic discovery.
"""

from posthog.models.integration import Integration

from products.slack_app.backend.providers.base import ChatProvider, ChatProviderError
from products.slack_app.backend.providers.slack import SlackChatProvider

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
