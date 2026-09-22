"""The line under a PostHog-authored Slack message that invites the reader to ask a follow-up.

What the line says depends on the install: a workspace whose bot can answer a mention is invited to
send one, and a workspace whose bot cannot is offered the setup link instead. Other products reach
these through ``facade.api``.
"""

from typing import Any

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_scopes import bot_is_ready

BOT_SETUP_DOCS_URL = "https://posthog.com/docs/slack-app"


def build_followup_invite_text(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> str | None:
    """mrkdwn nudging the channel to @PostHog this report (or to set the bot up).

    Returns ``None`` when there's no Slack install or the org hasn't approved AI data processing —
    we don't nudge people toward the AI bot when their org hasn't opted into AI. Plain-text variant
    used where Slack only accepts mrkdwn (e.g. a gallery upload's ``initial_comment``).

    The caller resolves ``ai_enabled`` rather than this function reading it off the integration,
    for two reasons. Reading it costs two foreign-key traversals, which would raise
    ``SynchronousOnlyOperation`` on the async delivery path in products/exports. And a caller that
    enforces the consent earlier can say so instead of paying the lookup again.

    ``utm_tags`` attributes an install that starts from the setup link, so each caller passes the
    campaign that names its own surface.
    """
    if integration is None or not ai_enabled:
        return None
    if bot_is_ready(integration):
        return "💬 Reply in this thread and mention *@PostHog* with a question to dig into this report."
    return f"💬 <{BOT_SETUP_DOCS_URL}?{utm_tags}|Set up the @PostHog bot> to ask follow-up questions about your reports here."


def build_followup_invite(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> dict[str, Any] | None:
    """Slack context block nudging the channel to @PostHog this report (or to set the bot up).

    Returns ``None`` in the same cases as ``build_followup_invite_text``.
    """
    text = build_followup_invite_text(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)
    if text is None:
        return None
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
