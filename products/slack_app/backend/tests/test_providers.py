import pytest

from products.slack_app.backend.providers import (
    ChatProviderError,
    SlackChatProvider,
    get_chat_provider,
    thread_handler_from_context,
)
from products.slack_app.backend.slack_thread import SlackThreadHandler


def test_registry_resolves_slack_provider():
    assert get_chat_provider("slack") is SlackChatProvider


def test_registry_rejects_unknown_kind():
    with pytest.raises(ChatProviderError):
        get_chat_provider("carrier-pigeon")


def test_thread_handler_context_without_provider_key_dispatches_to_slack():
    # Contexts persisted before the provider key existed are Slack's; future providers
    # rely on this default staying in place when they start stamping their own key.
    handler = thread_handler_from_context({"integration_id": 1, "channel": "C1", "thread_ts": "1.0"})
    assert isinstance(handler, SlackThreadHandler)


def test_thread_handler_unknown_provider_raises():
    with pytest.raises(ChatProviderError):
        thread_handler_from_context(
            {"provider": "carrier-pigeon", "integration_id": 1, "channel": "C1", "thread_ts": "1.0"}
        )
