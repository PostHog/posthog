"""Backwards-compat re-export. The real implementation now lives in
`posthog.security.llm_prompt_sanitization` so it can be shared across products
(marketing analytics, subscriptions, future Max tools).

Keep these imports stable — `llm_change_summary.py` and any external pins
import from here.
"""

from posthog.security.llm_prompt_sanitization import (
    CORE_MEMORY_MAX_LEN,
    GENERIC_VALUE_MAX_LEN,
    INSIGHT_DESCRIPTION_MAX_LEN,
    INSIGHT_NAME_MAX_LEN,
    PROMPT_GUIDE_MAX_LEN,
    SERIES_LABEL_MAX_LEN,
    SUBSCRIPTION_TITLE_MAX_LEN,
    sanitize_core_memory_text,
    sanitize_user_text,
)

__all__ = [
    "CORE_MEMORY_MAX_LEN",
    "GENERIC_VALUE_MAX_LEN",
    "INSIGHT_DESCRIPTION_MAX_LEN",
    "INSIGHT_NAME_MAX_LEN",
    "PROMPT_GUIDE_MAX_LEN",
    "SERIES_LABEL_MAX_LEN",
    "SUBSCRIPTION_TITLE_MAX_LEN",
    "sanitize_core_memory_text",
    "sanitize_user_text",
]
