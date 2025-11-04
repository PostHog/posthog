import base64
from typing import cast

from anthropic.types import MessageParam
from google.genai.types import Blob, Content, ContentListUnion, Part

from products.llm_analytics.backend.providers.formatters.anthropic_typeguards import (
    is_base64_image_param,
    is_image_block_param,
    is_text_block_param,
)


def convert_anthropic_messages_to_gemini(messages: list[MessageParam]) -> ContentListUnion:
    contents: ContentListUnion = []
    for message in messages:
        parts: list[Part] = []
        if isinstance(message["content"], str):
            parts.append(Part(text=message["content"]))
        elif isinstance(message["content"], list):
            for block in message["content"]:
                if is_text_block_param(block):
                    parts.append(Part(text=block["text"]))
                elif is_image_block_param(block):
                    if not is_base64_image_param(block["source"]):
                        raise ValueError("Unsupported image source type")
                    parts.append(
                        Part(
                            inline_data=Blob(
                                data=base64.b64decode(cast(str, block["source"]["data"])),
                                mime_type=block["source"]["media_type"],
                            )
                        )
                    )
                else:
                    raise ValueError(f"Unsupported content block type: {type(block)}")

        contents.append(Content(role="model" if message["role"] == "assistant" else "user", parts=parts))  # type: ignore

    return contents
