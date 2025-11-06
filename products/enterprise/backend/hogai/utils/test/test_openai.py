from posthog.test.base import BaseTest

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, FailureMessage, HumanMessage

from products.enterprise.backend.hogai.utils.openai import convert_to_openai_message, convert_to_openai_messages


class TestOpenAIUtils(BaseTest):
    def test_convert_context_message_to_openai_message(self):
        message = ContextMessage(content="Context information")

        result = convert_to_openai_message(message, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "Context information")

    def test_convert_assistant_message_to_openai_message_without_tool_calls(self):
        message = AssistantMessage(content="Assistant response", id="asst_123", tool_calls=[])

        result = convert_to_openai_message(message, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "Assistant response")
        self.assertEqual(result[0].id, "asst_123")

    def test_convert_assistant_message_to_openai_message_with_tool_calls(self):
        message = AssistantMessage(
            content="Let me search for that",
            id="asst_456",
            tool_calls=[
                {"id": "tool_1", "name": "search", "args": {"query": "test"}},
                {"id": "tool_2", "name": "read_data", "args": {"id": 123}},
            ],
        )
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search result", id="result_1", tool_call_id="tool_1"),
            "tool_2": AssistantToolCallMessage(content="Data content", id="result_2", tool_call_id="tool_2"),
        }

        result = convert_to_openai_message(message, tool_result_map)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].content, "Let me search for that")
        self.assertEqual(len(result[0].tool_calls), 2)  # type: ignore
        self.assertEqual(result[1].content, "Search result")
        self.assertEqual(result[1].tool_call_id, "tool_1")  # type: ignore
        self.assertEqual(result[2].content, "Data content")
        self.assertEqual(result[2].tool_call_id, "tool_2")  # type: ignore

    def test_convert_assistant_message_filters_missing_tool_results(self):
        message = AssistantMessage(
            content="Processing",
            id="asst_789",
            tool_calls=[
                {"id": "tool_1", "name": "search", "args": {"query": "test"}},
                {"id": "tool_2", "name": "missing_tool", "args": {}},
            ],
        )
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search result", id="result_1", tool_call_id="tool_1"),
        }

        result = convert_to_openai_message(message, tool_result_map)

        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0].tool_calls), 1)  # type: ignore
        self.assertEqual(result[0].tool_calls[0]["id"], "tool_1")  # type: ignore

    def test_convert_failure_message_to_openai_message(self):
        message = FailureMessage(content="Error occurred", id="fail_123")

        result = convert_to_openai_message(message, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "Error occurred")
        self.assertEqual(result[0].id, "fail_123")

    def test_convert_failure_message_with_no_content(self):
        message = FailureMessage(content=None, id="fail_456")

        result = convert_to_openai_message(message, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "An unknown failure occurred.")
        self.assertEqual(result[0].id, "fail_456")

    def test_convert_to_openai_messages_with_mixed_conversation(self):
        conversation = [
            HumanMessage(content="Hello", id="human_1"),
            AssistantMessage(
                content="Hi there",
                id="asst_1",
                tool_calls=[{"id": "tool_1", "name": "search", "args": {"query": "greeting"}}],
            ),
            HumanMessage(content="Follow up", id="human_2"),
            AssistantMessage(content="Response", id="asst_2", tool_calls=[]),
            FailureMessage(content="Error", id="fail_1"),
        ]
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search done", id="result_1", tool_call_id="tool_1"),
        }

        result = convert_to_openai_messages(conversation, tool_result_map)  # type: ignore

        self.assertEqual(len(result), 6)
        self.assertEqual(result[0].content, "Hello")
        self.assertEqual(result[1].content, "Hi there")
        self.assertEqual(result[2].content, "Search done")
        self.assertEqual(result[3].content, "Follow up")
        self.assertEqual(result[4].content, "Response")
        self.assertEqual(result[5].content, "Error")

    def test_convert_to_openai_messages_handles_context_messages(self):
        conversation = [
            ContextMessage(content="System context"),
            HumanMessage(content="User question", id="human_1"),
            AssistantMessage(content="Answer", id="asst_1", tool_calls=[]),
        ]

        result = convert_to_openai_messages(conversation, {})  # type: ignore

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].content, "System context")
        self.assertEqual(result[1].content, "User question")
        self.assertEqual(result[2].content, "Answer")

    def test_convert_to_openai_messages_skips_unknown_message_types(self):
        conversation = [
            HumanMessage(content="Hello", id="human_1"),
            AssistantMessage(content="Response", id="asst_1", tool_calls=[]),
        ]

        result = convert_to_openai_messages(conversation, {})  # type: ignore

        self.assertEqual(len(result), 2)
