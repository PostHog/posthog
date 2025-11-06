from typing import Any, cast

from posthog.test.base import BaseTest

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from products.enterprise.backend.hogai.graph.conversation_summarizer.nodes import AnthropicConversationSummarizer


class TestAnthropicConversationSummarizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.summarizer = AnthropicConversationSummarizer(team=self.team, user=self.user)

    @parameterized.expand(
        [
            (
                "single_message_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [[{"type": "text", "text": "Hello"}]],
            ),
            (
                "multiple_items_with_cache_control",
                [
                    LangchainAIMessage(
                        content=[
                            {"type": "text", "text": "First", "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": "Second", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [[{"type": "text", "text": "First"}, {"type": "text", "text": "Second"}]],
            ),
            (
                "mixed_items_some_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "With cache", "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": "Without cache"},
                        ]
                    )
                ],
                [[{"type": "text", "text": "With cache"}, {"type": "text", "text": "Without cache"}]],
            ),
            (
                "multiple_messages_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "Message 1", "cache_control": {"type": "ephemeral"}},
                        ]
                    ),
                    LangchainAIMessage(
                        content=[
                            {"type": "text", "text": "Message 2", "cache_control": {"type": "ephemeral"}},
                        ]
                    ),
                ],
                [
                    [{"type": "text", "text": "Message 1"}],
                    [{"type": "text", "text": "Message 2"}],
                ],
            ),
        ]
    )
    def test_removes_cache_control(self, name, input_messages, expected_contents):
        result = self.summarizer._construct_messages(input_messages)

        # Extract the actual messages from the prompt template
        messages = result.messages[1:-1]  # Skip system prompt and user prompt

        self.assertEqual(len(messages), len(expected_contents), f"Wrong number of messages in test case: {name}")

        for i, (message, expected_content) in enumerate(zip(messages, expected_contents)):
            self.assertEqual(
                message.content,
                expected_content,
                f"Message {i} content mismatch in test case: {name}",
            )

    @parameterized.expand(
        [
            (
                "string_content",
                [LangchainHumanMessage(content="Simple string")],
            ),
            (
                "empty_list_content",
                [LangchainHumanMessage(content=[])],
            ),
            (
                "non_dict_items_in_list",
                [LangchainHumanMessage(content=["string_item", {"type": "text", "text": "dict_item"}])],
            ),
        ]
    )
    def test_handles_non_dict_content_without_errors(self, name, input_messages):
        result = self.summarizer._construct_messages(input_messages)
        self.assertIsNotNone(result)

    def test_original_message_not_modified(self):
        original_content: list[str | dict[Any, Any]] = [
            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
        ]
        message = LangchainHumanMessage(content=original_content)

        # Store the original cache_control to verify it's not modified
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertIn("cache_control", content_list[0])

        self.summarizer._construct_messages([message])

        # Verify original message still has cache_control
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertIn("cache_control", content_list[0])
        self.assertEqual(content_list[0]["cache_control"], {"type": "ephemeral"})

    def test_deep_copy_prevents_modification(self):
        original_content: list[str | dict[Any, Any]] = [
            {
                "type": "text",
                "text": "Test",
                "cache_control": {"type": "ephemeral"},
                "other_key": "value",
            },
        ]
        message = LangchainHumanMessage(content=original_content)

        content_list = cast(list[dict[str, Any]], message.content)
        original_keys = set(content_list[0].keys())

        self.summarizer._construct_messages([message])

        # Verify original message structure unchanged
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertEqual(set(content_list[0].keys()), original_keys)
        self.assertIn("cache_control", content_list[0])

    def test_preserves_other_content_properties(self):
        input_messages = [
            LangchainHumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "Hello",
                        "cache_control": {"type": "ephemeral"},
                        "custom_field": "custom_value",
                        "another_field": 123,
                    },
                ]
            )
        ]

        result = self.summarizer._construct_messages(input_messages)
        messages = result.messages[1:-1]

        # Verify other fields are preserved
        content = messages[0].content[0]
        self.assertEqual(content["custom_field"], "custom_value")
        self.assertEqual(content["another_field"], 123)
        self.assertNotIn("cache_control", content)

    def test_empty_messages_list(self):
        result = self.summarizer._construct_messages([])
        # Should return prompt template with just system and user prompts
        self.assertEqual(len(result.messages), 2)
