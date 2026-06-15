"""Slack message text processing helpers.

Transforms applied to raw Slack message text on its way to the agent —
resolving `<@U…>` mentions to readable `@display_name`, stripping the bot's
self-mention, and so on. Kept separate from the HTTP-facing code in
`api.py` so the text logic stays testable in isolation.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models.integration import Integration, SlackIntegration


def resolve_user_mentions_text(
    slack: "SlackIntegration",
    integration: "Integration",
    text: str,
    *,
    strip_bot_user_id: str | None = None,
    user_cache: dict[str, str] | None = None,
) -> str:
    """Resolve Slack `<@U…>` mentions to readable `@display_name` text.

    Keeps real user mentions — so the agent sees who was explicitly tagged —
    while dropping the bot's own self-mention, which is just the trigger and
    carries no information. Whitespace left where the bot mention was removed
    is collapsed.
    """
    # Deferred import: ``_get_slack_user_info`` lives in ``api.py`` alongside a
    # chain of caching helpers; importing it at module load would create a
    # circular import via ``api.py -> services.slack_messages -> api.py``.
    from products.slack_app.backend.api import _get_slack_user_info  # noqa: PLC0415

    cache = user_cache if user_cache is not None else {}

    def resolve_user(uid: str) -> str:
        if uid not in cache:
            try:
                user_info = _get_slack_user_info(slack, integration, uid)
                profile = user_info.get("user", {}).get("profile", {})
                cache[uid] = profile.get("display_name") or profile.get("real_name") or "Unknown"
            except Exception:
                cache[uid] = "Unknown"
        return cache[uid]

    def replace_mention(match: re.Match) -> str:
        uid = match.group(1)
        if strip_bot_user_id and uid == strip_bot_user_id:
            return ""
        return f"@{resolve_user(uid)}"

    resolved = re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)
    if strip_bot_user_id:
        # Tidy the gap left where the bot's own mention was removed.
        resolved = re.sub(r"[ \t]{2,}", " ", resolved).strip()
    return resolved
