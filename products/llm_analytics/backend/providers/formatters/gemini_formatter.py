import base64
from typing import TYPE_CHECKING, Any, cast

from anthropic.types import MessageParam

from posthog.api.wizard.genai_types import get_genai_types

from products.llm_analytics.backend.providers.formatters.anthropic_typeguards import (
    is_base64_image_param,
    is_image_block_param,
    is_text_block_param,
)

if TYPE_CHECKING:
    from google.genai.types import ContentListUnion


def convert_anthropic_messages_to_gemini(messages: list[MessageParam]) -> "ContentListUnion":
    # Dynamically import genai types to avoid loading heavy dependencies at module import time
    BlobType, ContentType, PartType = get_genai_types("Blob", "Content", "Part")

    contents: list[Any] = []  # Sticking to Content, as we don't support other formats yet
    for message in messages:
        parts: list[Any] = []
        if isinstance(message["content"], str):
            parts.append(PartType(text=message["content"]))
        elif isinstance(message["content"], list):
            for block in message["content"]:
                if is_text_block_param(block):
                    parts.append(PartType(text=block["text"]))
                elif is_image_block_param(block):
                    if not is_base64_image_param(block["source"]):
                        raise ValueError("Unsupported image source type")
                    parts.append(
                        PartType(
                            inline_data=BlobType(
                                data=base64.b64decode(cast(str, block["source"]["data"])),
                                mime_type=block["source"]["media_type"],
                            )
                        )
                    )
                else:
                    raise ValueError(f"Unsupported content block type: {type(block)}")

        contents.append(ContentType(role="model" if message["role"] == "assistant" else "user", parts=parts))

    return contents
