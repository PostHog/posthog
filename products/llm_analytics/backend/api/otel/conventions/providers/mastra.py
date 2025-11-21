"""
Mastra provider transformer.

Handles Mastra's OTEL format which wraps messages in custom structures:
- Input: {"messages": [{"role": "user", "content": [...]}]}
- Output: {"files": [], "text": "...", "warnings": [], ...}
"""

import json
from typing import Any

from .base import ProviderTransformer


class MastraTransformer(ProviderTransformer):
    """
    Transform Mastra's OTEL format to PostHog standard format.

    Mastra uses @mastra/otel instrumentation scope and wraps messages
    in custom structures that need unwrapping.
    """

    def can_handle(self, span: dict[str, Any], scope: dict[str, Any]) -> bool:
        """
        Detect Mastra by instrumentation scope name.

        Mastra sets scope.name to "@mastra/otel" in its span converter.
        """
        scope_name = scope.get("name", "")

        # Primary detection: instrumentation scope
        if scope_name == "@mastra/otel":
            return True

        # Fallback: check for mastra-prefixed attributes
        attributes = span.get("attributes", {})
        return any(key.startswith("mastra.") for key in attributes.keys())

    def transform_prompt(self, prompt: Any) -> Any:
        """
        Transform Mastra's wrapped input format.

        Mastra wraps messages as: {"messages": [{"role": "user", "content": [...]}]}
        where content can be an array of objects like [{"type": "text", "text": "..."}]
        """
        import structlog

        logger = structlog.get_logger(__name__)

        if not isinstance(prompt, str):
            logger.info("mastra_transform_prompt_skip_not_string", prompt_type=type(prompt).__name__)
            return None  # No transformation needed

        try:
            parsed = json.loads(prompt)
            logger.info(
                "mastra_transform_prompt_parsed",
                has_messages=("messages" in parsed) if isinstance(parsed, dict) else False,
                parsed_type=type(parsed).__name__,
            )

            # Check for Mastra input format: {"messages": [...]}
            if not isinstance(parsed, dict) or "messages" not in parsed:
                return None  # Not Mastra format

            messages = parsed["messages"]
            if not isinstance(messages, list):
                return None

            # Transform Mastra messages to standard format
            result = []
            for msg in messages:
                if not isinstance(msg, dict) or "role" not in msg:
                    continue

                # Handle Mastra's content array format: [{"type": "text", "text": "..."}]
                if "content" in msg and isinstance(msg["content"], list):
                    text_parts = []
                    for content_item in msg["content"]:
                        if isinstance(content_item, dict):
                            if content_item.get("type") == "text" and "text" in content_item:
                                text_parts.append(content_item["text"])

                    if text_parts:
                        result.append({"role": msg["role"], "content": " ".join(text_parts)})
                    else:
                        # Keep as-is if we can't extract text
                        result.append(msg)
                else:
                    # Standard format message
                    result.append(msg)

            return result if result else None

        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def transform_completion(self, completion: Any) -> Any:
        """
        Transform Mastra's wrapped output format.

        Mastra wraps output as: {"files": [], "text": "...", "warnings": [], ...}
        Extract just the text content.
        """
        if not isinstance(completion, str):
            return None  # No transformation needed

        try:
            parsed = json.loads(completion)

            # Check for Mastra output format: {"text": "...", ...}
            if not isinstance(parsed, dict) or "text" not in parsed:
                return None  # Not Mastra format

            # Extract text content as assistant message
            return [{"role": "assistant", "content": parsed["text"]}]

        except (json.JSONDecodeError, TypeError, KeyError):
            return None
