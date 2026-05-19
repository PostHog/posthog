from unittest.mock import patch

import pytest
from django.test import override_settings

import anthropic

from products.signals.backend.temporal.llm import get_async_anthropic_client


class TestGetAsyncAnthropicClient:
    @override_settings(ANTHROPIC_API_KEY="sk-test-key")
    def test_returns_raw_anthropic_client_not_posthog_wrapped(self):
        """The signals product must use the raw `anthropic.AsyncAnthropic` client rather
        than `posthoganalytics.ai.anthropic.AsyncAnthropic`. Capturing `$ai_generation`
        events on these grouping / summarization calls created a feedback loop where the
        "Unhappy User" LLM judge evaluated the signals product's own meta-content (candidate
        signal descriptions, eval reasoning) and fired fabricated signal reports back into
        the inbox. Don't regress this by switching back to the captured wrapper."""
        client = get_async_anthropic_client()

        # Must be the raw upstream class — not a subclass from posthoganalytics.
        assert client.__class__ is anthropic.AsyncAnthropic
        # No PostHog client attached.
        assert not hasattr(client, "_ph_client")

    @override_settings(ANTHROPIC_API_KEY=None)
    def test_raises_when_api_key_missing(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not configured"):
            get_async_anthropic_client()

    @override_settings(ANTHROPIC_API_KEY="sk-test-key")
    def test_does_not_require_posthog_default_client(self):
        """The previous implementation refused to construct the client unless
        `posthoganalytics.default_client` was set. After the loop-fix this dependency
        is gone — the signals LLM no longer talks to the analytics backend at all."""
        with patch("posthoganalytics.default_client", None):
            # Must not raise.
            client = get_async_anthropic_client()
            assert client.__class__ is anthropic.AsyncAnthropic
