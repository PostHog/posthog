import pytest
from django.test import TestCase
from google.genai.types import Content, Blob
from anthropic.types import MessageParam
from typing import cast
from products.editor.backend.providers.formatters.gemini_formatter import convert_anthropic_messages_to_gemini


class TestGeminiFormatter(TestCase):
    def test_convert_simple_text_message(self):
        messages: list[MessageParam] = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        result = cast(list[Content], convert_anthropic_messages_to_gemini(messages))

        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].parts is not None
        assert result[0].parts[0].text == "Hello"
        assert result[1].role == "model"
        assert result[1].parts is not None
        assert result[1].parts[0].text == "Hi there"

    def test_convert_message_with_list_content(self):
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "First part"}, {"type": "text", "text": "Second part"}],
            }
        ]

        result = cast(list[Content], convert_anthropic_messages_to_gemini(messages))

        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].parts is not None
        assert len(result[0].parts) == 2
        assert result[0].parts[0].text == "First part"
        assert result[0].parts[1].text == "Second part"

    def test_convert_message_with_image(self):
        base64_data = "SGVsbG8gV29ybGQ="  # "Hello World" in base64
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Check this image:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64_data}},
                ],
            }
        ]

        result = cast(list[Content], convert_anthropic_messages_to_gemini(messages))

        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].parts is not None
        assert len(result[0].parts) == 2
        assert result[0].parts[0].text == "Check this image:"
        assert isinstance(result[0].parts[1].inline_data, Blob)
        assert result[0].parts[1].inline_data.mime_type == "image/jpeg"
        assert result[0].parts[1].inline_data.data == b"Hello World"

    def test_invalid_image_source(self):
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "url",  # Invalid source type
                            "url": "http://example.com/image.jpg",
                        },
                    }
                ],
            }
        ]

        with pytest.raises(ValueError, match="Unsupported image source type"):
            convert_anthropic_messages_to_gemini(messages)

    def test_invalid_content_block(self):
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "unknown",  # type: ignore
                        "data": "something",
                    }
                ],
            }
        ]

        with pytest.raises(ValueError, match="Unsupported content block type"):
            convert_anthropic_messages_to_gemini(messages)
