"""The custom emoji of a Slack workspace, for the reaction picker on the settings page.

Slack's standard emoji ship with the frontend, so this lists only what the workspace added.
"""

from __future__ import annotations

from django.core.cache import cache

import structlog

from posthog.integrations import IntegrationRecord
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.facade.enums import SlackCustomEmojiStatus
from products.slack_app.backend.facade.types import SlackCustomEmoji, SlackEmojiCatalog
from products.slack_app.backend.services.slack_scopes import SLACK_EMOJI_SCOPE, has_scopes

logger = structlog.get_logger(__name__)

# The picker opens far more often than a workspace adds emoji, so one `emoji.list` call serves it for an hour.
CUSTOM_EMOJI_CACHE_SECONDS = 60 * 60
# After a failed call the picker shows the standard emoji, and the next open within this window does not ask again.
CUSTOM_EMOJI_FAILURE_CACHE_SECONDS = 60
ALIAS_PREFIX = "alias:"


def _cache_key(slack_workspace_id: str) -> str:
    return f"slack_app_custom_emoji:{slack_workspace_id}"


def _resolve(raw: dict[str, object]) -> tuple[SlackCustomEmoji, ...]:
    """Turn `emoji.list` output into picker entries. An alias takes the image of the emoji it points at."""
    emoji: list[SlackCustomEmoji] = []
    for name, value in raw.items():
        if not isinstance(value, str):
            continue
        if value.startswith(ALIAS_PREFIX):
            target = value.removeprefix(ALIAS_PREFIX)
            target_value = raw.get(target)
            # The target of an alias is either another custom emoji, which has a URL, or a standard emoji.
            image_url = (
                target_value
                if isinstance(target_value, str) and target_value and not target_value.startswith(ALIAS_PREFIX)
                else None
            )
            emoji.append(SlackCustomEmoji(name=name, image_url=image_url, alias_for=target))
        else:
            emoji.append(SlackCustomEmoji(name=name, image_url=value, alias_for=None))
    return tuple(sorted(emoji, key=lambda entry: entry.name))


def list_custom_emoji(integration: IntegrationRecord) -> SlackEmojiCatalog:
    if not has_scopes(integration, [SLACK_EMOJI_SCOPE]):
        return SlackEmojiCatalog(custom_emoji=(), custom_emoji_status=SlackCustomEmojiStatus.MISSING_SCOPE)

    key = _cache_key(integration.integration_id or "")
    cached = cache.get(key)
    if cached is not None:
        return SlackEmojiCatalog(
            custom_emoji=_resolve(cached["emoji"]), custom_emoji_status=SlackCustomEmojiStatus(cached["status"])
        )

    try:
        response = SlackIntegration(integration, source="slack_app_emoji_picker").client.emoji_list()
        raw = response.get("emoji") or {}
        status = SlackCustomEmojiStatus.LOADED
    except Exception:
        logger.warning("slack_app_emoji_list_failed", integration_id=integration.id, exc_info=True)
        raw, status = {}, SlackCustomEmojiStatus.UNAVAILABLE

    timeout = (
        CUSTOM_EMOJI_CACHE_SECONDS if status == SlackCustomEmojiStatus.LOADED else CUSTOM_EMOJI_FAILURE_CACHE_SECONDS
    )
    cache.set(key, {"emoji": dict(raw), "status": status.value}, timeout=timeout)
    return SlackEmojiCatalog(custom_emoji=_resolve(raw), custom_emoji_status=status)
