import pytest

from products.slack_app.backend.providers import ChatProviderError, SlackChatProvider, get_chat_provider


def test_registry_resolves_slack_provider():
    assert get_chat_provider("slack") is SlackChatProvider


def test_registry_rejects_unknown_kind():
    with pytest.raises(ChatProviderError):
        get_chat_provider("carrier-pigeon")
