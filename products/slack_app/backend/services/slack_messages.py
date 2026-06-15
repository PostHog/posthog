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
) -> str:
    """Label human `<@U…>` mentions with display names; drop every bot mention.

    Slack delivers events with bare `<@U_ID>` references — opaque to an LLM,
    and easily paraphrased away into plain prose. For real users we enrich to
    Slack's labeled form `<@U_ID|displayname>`: the agent gets both a
    human-readable handle to reason about *and* the exact wire-format token it
    can echo verbatim to ping the user back. Slack accepts the labeled form on
    the way out, so no outbound transformation is needed.

    Bot users (our own, plus any other workspace bot — Grafana, GitHub, etc.)
    are stripped entirely. There's nothing useful for the agent to do with a
    bot mention, and echoing it would re-ping the bot. The `is_bot` flag comes
    from `users.info` via the cached profile; `strip_bot_user_id` is a fast
    path for the trigger's own self-mention that avoids the lookup.

    Wire format alone can't distinguish a bot user ID from a human's — both
    are `U…`-prefixed. The flag is the only authoritative signal.
    """
    # Deferred import: ``_get_slack_user_info`` lives in ``api.py`` alongside a
    # chain of caching helpers; importing it at module load would create a
    # circular import via ``api.py -> services.slack_messages -> api.py``.
    from products.slack_app.backend.api import _get_slack_user_info  # noqa: PLC0415

    cache: dict[str, tuple[str, bool]] = {}

    def resolve_user(uid: str) -> tuple[str, bool]:
        if uid not in cache:
            try:
                user_info = _get_slack_user_info(slack, integration, uid)
                user = user_info.get("user", {})
                profile = user.get("profile", {})
                display = profile.get("display_name") or profile.get("real_name") or "Unknown"
                cache[uid] = (display, bool(user.get("is_bot")))
            except Exception:
                # Lookup failed — degrade to a labeled mention so a ping still
                # works; treating an unknown user as a bot would silently drop
                # a real user's mention, which is the bug this module exists
                # to prevent.
                cache[uid] = ("Unknown", False)
        return cache[uid]

    def replace_mention(match: re.Match) -> str:
        uid = match.group(1)
        if strip_bot_user_id and uid == strip_bot_user_id:
            return ""
        display, is_bot = resolve_user(uid)
        if is_bot:
            return ""
        return f"<@{uid}|{display}>"

    resolved = re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)
    # Tidy gaps left where bot mentions were removed.
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
