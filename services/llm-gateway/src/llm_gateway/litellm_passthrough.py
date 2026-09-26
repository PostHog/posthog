"""litellm drops unknown Messages body keys and `anthropic-beta` values outside its allowlist.
Claude Code's server-side classifier needs `safeguards` and its beta to reach Anthropic.
"""

from typing import Any

import litellm
from litellm.llms.anthropic.experimental_pass_through.messages.transformation import AnthropicMessagesConfig
from litellm.llms.anthropic.experimental_pass_through.messages.utils import _anthropic_messages_optional_param_keys
from litellm.types.llms.anthropic import AnthropicMessagesRequestOptionalParams
from litellm.utils import ProviderConfigManager

PASSTHROUGH_BODY_FIELDS: tuple[str, ...] = ("safeguards",)


class VerbatimBetaAnthropicMessagesConfig(AnthropicMessagesConfig):
    """Send caller betas to Anthropic unfiltered, as a direct connection does."""

    def should_filter_anthropic_beta_headers(self) -> bool:
        return False


def install() -> None:
    for field in PASSTHROUGH_BODY_FIELDS:
        AnthropicMessagesRequestOptionalParams.__annotations__.setdefault(field, Any)
    _anthropic_messages_optional_param_keys.cache_clear()

    litellm.AnthropicMessagesConfig = VerbatimBetaAnthropicMessagesConfig  # type: ignore[misc]
    ProviderConfigManager._get_provider_anthropic_messages_config_cached.cache_clear()


def caller_anthropic_beta(headers: Any) -> str | None:
    values = [value.strip() for line in headers.getlist("anthropic-beta") for value in line.split(",")]
    joined = ",".join(value for value in values if value)
    return joined or None


def with_caller_anthropic_beta(data: dict[str, Any], headers: Any) -> dict[str, Any]:
    beta = caller_anthropic_beta(headers)
    if beta is None:
        return data
    extra_headers = data.get("extra_headers")
    merged = dict(extra_headers) if isinstance(extra_headers, dict) else {}
    merged["anthropic-beta"] = beta
    return {**data, "extra_headers": merged}


def without_passthrough_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Non-Anthropic backends cannot run the classifier and can reject these fields."""
    return {key: value for key, value in data.items() if key not in PASSTHROUGH_BODY_FIELDS}
