"""
Mastra provider transformer.

Handles Mastra's OTEL format which wraps messages in custom structures:
- Input: {"messages": [{"role": "user", "content": [...]}]}
- Output: {"files": [], "text": "...", "warnings": [], ...}

Provider Behavior Notes:
------------------------
Mastra uses the @mastra/otel instrumentation scope and sends OTEL data in v1 pattern
(all data in span attributes, no separate log events).

Key characteristic: Mastra does NOT accumulate conversation history across calls.
Each `agent.generate()` call creates a separate, independent trace containing only
that turn's input (system message + current user message) and output. This means:

- A 4-turn conversation produces 4 separate traces
- Turn 4's trace only shows "Thanks, bye!" as input, not previous turns
- To see full conversation context, users must look at the sequence of traces

This is expected Mastra behavior, not a limitation of our ingestion. The framework
treats each generate() call as an independent operation.
"""

import json
from typing import Any

from .base import OtelInstrumentationPattern, ProviderTransformer


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

    def get_instrumentation_pattern(self) -> OtelInstrumentationPattern:
        """Mastra uses v1 pattern - all data in span attributes."""
        return OtelInstrumentationPattern.V1_ATTRIBUTES

    def transform_prompt(self, prompt: Any) -> Any:
        """
        Transform Mastra's wrapped input format.

        Mastra wraps messages as: {"messages": [{"role": "user", "content": [...]}]}
        where content can be an array of objects like [{"type": "text", "text": "..."}]
        """
        if not isinstance(prompt, str):
            return None  # No transformation needed

        try:
            parsed = json.loads(prompt)

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
