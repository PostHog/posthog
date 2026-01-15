from __future__ import annotations

from typing import Any

import litellm
import structlog

logger = structlog.get_logger(__name__)


class TokenCounter:
    """Counts tokens using litellm's built-in tokenizers."""

    def count(self, model: str, messages: list[dict[str, Any]]) -> int:
        """Count input tokens for messages."""
        try:
            return litellm.token_counter(model=model, messages=messages)
        except Exception as e:
            logger.warning("token_counter_fallback", model=model, error=str(e))
            text = self._messages_to_text(messages)
            return len(text) // 4

    def _messages_to_text(self, messages: list[dict[str, Any]]) -> str:
        """Convert messages array to text for fallback counting."""
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
        return "\n".join(parts)
