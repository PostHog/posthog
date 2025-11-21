"""
Tests for Mastra provider transformer.
"""

import json

import pytest

from products.llm_analytics.backend.api.otel.conventions.providers.mastra import MastraTransformer


class TestMastraTransformer:
    """Test Mastra-specific format transformations."""

    def setup_method(self):
        """Setup test instance."""
        self.transformer = MastraTransformer()

    def test_can_handle_mastra_scope(self):
        """Test detection by @mastra/otel scope name."""
        span = {"attributes": {}}
        scope = {"name": "@mastra/otel", "version": "1.0.0"}

        assert self.transformer.can_handle(span, scope) is True

    def test_can_handle_mastra_attributes(self):
        """Test detection by mastra.* attributes."""
        span = {
            "attributes": {
                "mastra.trace_id": "abc123",
                "mastra.span_id": "def456",
            }
        }
        scope = {"name": "other"}

        assert self.transformer.can_handle(span, scope) is True

    def test_cannot_handle_non_mastra(self):
        """Test that non-Mastra spans are not handled."""
        span = {"attributes": {"gen_ai.system": "openai"}}
        scope = {"name": "opentelemetry-instrumentation-openai"}

        assert self.transformer.can_handle(span, scope) is False

    def test_transform_prompt_simple_messages(self):
        """Test transforming Mastra's wrapped messages format."""
        mastra_input = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant"},
                    {"role": "user", "content": "Hello"},
                ]
            }
        )

        result = self.transformer.transform_prompt(mastra_input)

        assert result is not None
        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "You are a helpful assistant"}
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_transform_prompt_with_content_array(self):
        """Test transforming Mastra's content array format."""
        mastra_input = json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What's the weather"},
                            {"type": "text", "text": " in Paris?"},
                        ],
                    }
                ]
            }
        )

        result = self.transformer.transform_prompt(mastra_input)

        assert result is not None
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "What's the weather  in Paris?"

    def test_transform_prompt_non_mastra_format(self):
        """Test that non-Mastra formats return None."""
        # Standard GenAI format (already correct)
        standard_input = json.dumps([{"role": "user", "content": "Hello"}])

        result = self.transformer.transform_prompt(standard_input)

        assert result is None  # No transformation needed

    def test_transform_prompt_invalid_json(self):
        """Test handling of invalid JSON."""
        result = self.transformer.transform_prompt("not valid json")

        assert result is None

    def test_transform_prompt_non_string(self):
        """Test handling of non-string input."""
        result = self.transformer.transform_prompt(["already", "a", "list"])

        assert result is None

    def test_transform_completion_text_format(self):
        """Test transforming Mastra's output format."""
        mastra_output = json.dumps(
            {"files": [], "text": "The weather in Paris is sunny.", "warnings": [], "reasoning": [], "sources": []}
        )

        result = self.transformer.transform_completion(mastra_output)

        assert result is not None
        assert len(result) == 1
        assert result[0] == {"role": "assistant", "content": "The weather in Paris is sunny."}

    def test_transform_completion_non_mastra_format(self):
        """Test that non-Mastra output formats return None."""
        standard_output = json.dumps([{"role": "assistant", "content": "Hello"}])

        result = self.transformer.transform_completion(standard_output)

        assert result is None  # No transformation needed

    def test_transform_completion_invalid_json(self):
        """Test handling of invalid JSON in completion."""
        result = self.transformer.transform_completion("not valid json")

        assert result is None

    def test_transform_completion_non_string(self):
        """Test handling of non-string completion."""
        result = self.transformer.transform_completion({"already": "dict"})

        assert result is None

    def test_end_to_end_conversation(self):
        """Test a full conversation flow with Mastra format."""
        # Simulate what Mastra sends
        prompt = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": [{"type": "text", "text": "Hi there!"}]},
                ]
            }
        )

        completion = json.dumps({"text": "Hello! How can I help you?", "files": [], "warnings": []})

        # Transform
        prompt_result = self.transformer.transform_prompt(prompt)
        completion_result = self.transformer.transform_completion(completion)

        # Verify
        assert prompt_result == [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi there!"},
        ]
        assert completion_result == [{"role": "assistant", "content": "Hello! How can I help you?"}]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
