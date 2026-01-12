import pytest

from llm_gateway.rate_limiting.tokenizer import TokenCounter


class TestTokenCounter:
    @pytest.fixture
    def counter(self) -> TokenCounter:
        return TokenCounter()

    def test_counts_simple_messages(self, counter: TokenCounter) -> None:
        messages = [
            {"role": "user", "content": "Hello, world!"},
        ]
        tokens = counter.count("gpt-4o", messages)
        # Should be a reasonable number > 0
        assert tokens > 0
        assert tokens < 100  # Simple message shouldn't be that long

    def test_handles_empty_messages(self, counter: TokenCounter) -> None:
        messages: list[dict] = []
        tokens = counter.count("gpt-4o", messages)
        # litellm may add a few tokens for prompt formatting
        assert tokens < 10

    def test_handles_multiple_messages(self, counter: TokenCounter) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        tokens = counter.count("gpt-4o", messages)
        assert tokens > 0

    def test_handles_array_content(self, counter: TokenCounter) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                ],
            },
        ]
        # Should handle without error and return estimate
        tokens = counter.count("gpt-4o", messages)
        assert tokens >= 0

    def test_fallback_on_unknown_model(self, counter: TokenCounter) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        # Should not raise, uses fallback
        tokens = counter.count("some-unknown-model-xyz", messages)
        assert tokens > 0
