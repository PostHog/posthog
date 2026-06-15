"""Slack message text processing helpers.

The bot strips its own self-mention and enriches every other `<@U…>` reference
with a `|displayname` label before handing the text to the agent. Slack accepts
the labeled form `<@U_ID|displayname>` on both inbound and outbound messages —
the agent gets a human-readable name to reason about *and* a wire-format token
it can echo verbatim to ping the user back, so no outbound transformation is
needed.

Kept separate from the HTTP-facing code in `api.py` so the text logic stays
testable in isolation.
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
    """Label `<@U…>` mentions with display names so the agent can echo them back.

    Slack delivers events with bare `<@U_ID>` references — opaque to an LLM,
    and easily paraphrased away into plain prose. Enriching to Slack's labeled
    form `<@U_ID|displayname>` gives the agent both a human-readable handle to
    reason about *and* the exact wire-format token it can echo verbatim to ping
    the user back; Slack accepts the labeled form on the way out, so no
    outbound transformation is needed.

    The bot's own self-mention is removed — it's just the trigger and carries
    no information for the agent. Whitespace left where it sat is collapsed.
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
        return f"<@{uid}|{resolve_user(uid)}>"

    resolved = re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)
    if strip_bot_user_id:
        # Tidy the gap left where the bot's own mention was removed.
        resolved = re.sub(r"[ \t]{2,}", " ", resolved).strip()
    return resolved


def decode_slack_event_text(slack: "SlackIntegration", integration: "Integration", text: str) -> str:
    """Strip the bot's own self-mention from a Slack event and label the rest for the agent.

    Trigger sites all want the same thing: drop the bot's self-ping (it's just
    the activation, no information for the agent) and enrich every other
    `<@U…>` reference with a `|displayname` label so the agent can echo the
    token verbatim to ping the user back. Centralised here so a new trigger
    handler can't drift back into the original mention-eating bug.
    """
    # Deferred to break the circular dep between this module and slack_app api.py.
    from products.slack_app.backend.api import _get_cached_bot_user_id  # noqa: PLC0415

    bot_user_id = _get_cached_bot_user_id(slack, integration)
    return resolve_user_mentions_text(slack, integration, text, strip_bot_user_id=bot_user_id).strip()


def labeled_mentions_to_display_names(text: str) -> str:
    """Render labeled `<@U…|name>` mentions as plain `@name` for human-facing display.

    The labeled wire format is what we feed the agent so its replies round-trip as
    real Slack pings, but in human-facing contexts — task titles, PR titles, anywhere
    a UI surfaces the string without Slack rendering — the angle-bracket form shows
    up as literal noise. This unwraps it back to the readable form.
    """
    return re.sub(r"<@[A-Z0-9]+\|([^>]+)>", r"@\1", text)
