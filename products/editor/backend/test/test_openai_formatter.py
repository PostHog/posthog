from typing import cast
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ImageBlockParam,
    ToolUseBlockParam,
    ToolResultBlockParam,
    Base64ImageSourceParam,
)
from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
)
from products.editor.backend.providers.formatters.openai_formatter import convert_to_openai_messages


def test_convert_simple_text_messages():
    anthropic_messages: list[MessageParam] = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    openai_messages = convert_to_openai_messages(anthropic_messages)

    assert len(openai_messages) == 2
    user_msg = cast(ChatCompletionUserMessageParam, openai_messages[0])
    assistant_msg = cast(ChatCompletionAssistantMessageParam, openai_messages[1])
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Hello"
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "Hi there!"  # type: ignore


def test_convert_user_message_with_image():
    text_block: TextBlockParam = {"type": "text", "text": "Check this image:"}
    image_block: ImageBlockParam = {
        "type": "image",
        "source": Base64ImageSourceParam({"type": "base64", "media_type": "image/jpeg", "data": "base64_data_here"}),
    }
    anthropic_messages: list[MessageParam] = [{"role": "user", "content": [text_block, image_block]}]

    openai_messages = convert_to_openai_messages(anthropic_messages)

    assert len(openai_messages) == 1
    user_msg = cast(ChatCompletionUserMessageParam, openai_messages[0])
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    content = user_msg["content"]
    assert len(content) == 2
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    image_url = cast(ChatCompletionContentPartImageParam, content[1])
    assert image_url["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_convert_tool_use_message():
    text_block: TextBlockParam = {"type": "text", "text": "Let me help you with that."}
    tool_block: ToolUseBlockParam = {"type": "tool_use", "id": "tool_1", "name": "search", "input": {"query": "test"}}
    anthropic_messages: list[MessageParam] = [{"role": "assistant", "content": [text_block, tool_block]}]

    openai_messages = convert_to_openai_messages(anthropic_messages)

    assert len(openai_messages) == 1
    assistant_msg = cast(ChatCompletionAssistantMessageParam, openai_messages[0])
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "Let me help you with that."  # type: ignore
    assert assistant_msg["tool_calls"] is not None  # type: ignore
    tool_calls = assistant_msg["tool_calls"]  # type: ignore
    assert len(list(tool_calls)) == 1
    tool_call = next(iter(tool_calls))
    assert tool_call["id"] == "tool_1"
    assert tool_call["function"]["name"] == "search"


def test_convert_tool_result_message():
    tool_result: ToolResultBlockParam = {
        "type": "tool_result",
        "tool_use_id": "tool_1",
        "content": "Search results here",
    }
    anthropic_messages: list[MessageParam] = [{"role": "user", "content": [tool_result]}]

    openai_messages = convert_to_openai_messages(anthropic_messages)

    assert len(openai_messages) == 1
    tool_msg = cast(ChatCompletionToolMessageParam, openai_messages[0])
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "tool_1"
    assert tool_msg["content"] == "Search results here"


def test_convert_complex_conversation():
    text_block1: TextBlockParam = {"type": "text", "text": "Let me search for that"}
    tool_block: ToolUseBlockParam = {"type": "tool_use", "id": "tool_1", "name": "search", "input": {"query": "test"}}
    tool_result: ToolResultBlockParam = {"type": "tool_result", "tool_use_id": "tool_1", "content": "Search results"}
    text_block2: TextBlockParam = {"type": "text", "text": "Thanks!"}

    anthropic_messages: list[MessageParam] = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": [text_block1, tool_block]},
        {"role": "user", "content": [tool_result, text_block2]},
    ]

    openai_messages = convert_to_openai_messages(anthropic_messages)

    assert len(openai_messages) == 4
    assert [msg["role"] for msg in openai_messages] == ["user", "assistant", "tool", "user"]

    user_msg1 = cast(ChatCompletionUserMessageParam, openai_messages[0])
    assistant_msg = cast(ChatCompletionAssistantMessageParam, openai_messages[1])
    tool_msg = cast(ChatCompletionToolMessageParam, openai_messages[2])
    user_msg2 = cast(ChatCompletionUserMessageParam, openai_messages[3])

    assert user_msg1["content"] == "Hello"
    assert assistant_msg["content"] == "Let me search for that"  # type: ignore
    assert assistant_msg["tool_calls"] is not None  # type: ignore
    assert len(list(assistant_msg["tool_calls"])) == 1  # type: ignore
    assert tool_msg["content"] == "Search results"
    assert isinstance(user_msg2["content"], list)
    text_content = cast(ChatCompletionContentPartTextParam, user_msg2["content"][0])
    assert text_content["text"] == "Thanks!"
