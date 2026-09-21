"""What PostHog says the first time someone meets it in Slack.

Three moments, one product to describe: the app is added to a channel, someone joins the
workspace, someone installs the app. The audiences differ in what they need next, so each
message leads somewhere different, but they draw on one list of things worth knowing.
Keeping them in one module is what stops that list from drifting apart per surface.

A builder takes the integration and returns the ``(fallback_text, blocks)`` pair
``chat_postMessage`` wants. The fallback text is what a notification and a screen reader
get, so it says the one thing the message is for rather than repeating the whole of it.

The install DM is sent from here too, because nothing else owns it: it answers an OAuth
callback rather than a Slack event, so it has no dedupe key and no region to route to. The
channel and workspace-join messages are welded to both, and their delivery stays in
``api.py`` with the event router.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled
from products.slack_app.backend.services.slack_messages import app_home_url, context_block

logger = structlog.get_logger(__name__)

DOCS_URL = "https://posthog.com/docs/slack-app"

# One analytics question and one code change in each "try this" list, so nobody reads the
# app as only the half they happened to see first.
_CHANNEL_EXAMPLES = (
    "`@PostHog why did signups drop in the EU last week?`",
    "`@PostHog open a PR that adds a unit test for src/utils.py`",
)
_DM_EXAMPLES = (
    "`why did signups drop in the EU last week?`",
    "`fix the flaky billing CI job`",
)


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _bullets(title: str, lines: tuple[str, ...]) -> dict[str, Any]:
    return _section("*{}*\n{}".format(title, "\n".join(f"• {line}" for line in lines)))


def _docs_button_block() -> dict[str, Any]:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Read the docs"},
                "url": DOCS_URL,
            }
        ],
    }


def _feedback_block() -> dict[str, Any]:
    """The ask for a rating, in the one wording all three messages share.

    Every welcome carries it because the thumbs are the only channel a Slack reader has
    back to us, and nothing else in the product points at them.
    """
    return _section(
        "*Tell me when I get it wrong*\nHit the thumbs under my replies, or react with :thumbsup: or "
        ":thumbsdown:. A thumbs down asks what went wrong, and that goes straight to the team building me."
    )


def _home_tab(integration: Integration, label: str = "my Home tab") -> str:
    """``label``, linked to this install's Home tab where there is one to link to.

    An install that predates the app id on its config has no deep link, and the tab is
    still there to be opened by hand, so the sentence around this has to read the same
    either way. A link rather than a button: Slack renders ``slack://`` in mrkdwn, and the
    reader is already in Slack, so the tab opens in place.
    """
    url = app_home_url(integration)
    return f"<{url}|{label}>" if url else label


def build_channel_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """Posted in a channel the moment the app is added to it.

    Written for everyone in the channel rather than for whoever did the adding, so it
    opens with what a mention gets you and only then covers the things people otherwise
    never find: steering a run, naming a model, pointing mentions at another project,
    rating a reply.
    """
    blocks: list[dict[str, Any]] = [
        _section(
            ":wave: Hey, I'm PostHog. Tag me with `@PostHog` and I'll dig into your product data, poke "
            "around your codebase, or open a pull request to fix something."
        ),
        _bullets("Try asking me", _CHANNEL_EXAMPLES),
        _bullets(
            "A few things worth knowing",
            (
                "Tag me again in the thread while I'm working and I'll pick up what you say.",
                "Want a different model? Say so: `@PostHog use fable for this one`, or "
                "`@PostHog run this on opus 5 at high effort`.",
                "Answering for the wrong project? `@PostHog project 12345` sends your mentions elsewhere.",
                "You can DM me instead of tagging me here.",
            ),
        ),
        _feedback_block(),
        context_block(
            "I also unfurl PostHog links shared in this channel. Your default model and thread "
            f"follow-ups live in {_home_tab(integration)}."
        ),
        _docs_button_block(),
    ]
    return "Hey, I'm PostHog. Tag me with @PostHog to get started.", blocks


def build_team_join_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """DM'd to someone who just joined a workspace that already has the app.

    They inherited a tool nobody introduced them to, so this says what it is before it
    says what it can do, and the examples drop the `@PostHog` prefix because a DM needs
    none.
    """
    blocks: list[dict[str, Any]] = [
        _section(
            ":wave: Hey, welcome! I'm PostHog, an AI agent your team already uses here. Message me, or tag "
            "`@PostHog` in any channel, and I'll dig into your product data or open a pull request in a "
            "connected repo."
        ),
        _bullets("Try asking me", _DM_EXAMPLES),
        _bullets(
            "A few things worth knowing",
            (
                "Keep replying in the thread while I'm working and I'll pick up what you say. "
                "In a channel, tag me in the reply.",
                "Want a different model? Say so: `use fable for this one`.",
            ),
        ),
        _feedback_block(),
        context_block(f"Your default model, thread follow-ups and linked accounts live in {_home_tab(integration)}."),
        _docs_button_block(),
    ]
    return "Hey, welcome! I'm PostHog. Message me to get started.", blocks


def build_install_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """DM'd to whoever installed the app, right after the install lands.

    The one reader set up to act for the whole workspace, so this is the only welcome that
    covers routing other people's mentions and connecting a GitHub account.
    """
    blocks: list[dict[str, Any]] = [
        _section(
            ":tada: Thanks for installing PostHog! I'm an AI agent. I dig into your product data, poke "
            "around your codebase, and open pull requests in your connected repos."
        ),
        _bullets(
            "Start here",
            (
                "Invite me to a channel with `/invite @PostHog`, then tag me with whatever you need.",
                "Or just message me right here.",
            ),
        ),
        _bullets(
            "Set it up for the team",
            (
                "`@PostHog project 12345` sends your mentions to a particular PostHog project. Slack admins "
                "can set the default for everyone with `@PostHog project workspace 12345`.",
                f"{_home_tab(integration, 'My Home tab')} has the default AI model, thread follow-ups and "
                "the tasks your workspace has started. Connect your GitHub there so pull requests open "
                "under your own account.",
            ),
        ),
        _feedback_block(),
        _docs_button_block(),
    ]
    return "Thanks for installing PostHog! Tag me with @PostHog, or message me here.", blocks


def send_install_welcome(integration: Integration) -> None:
    """DM the installing user, when the assistant surface is available to their workspace.

    Called from the install signal's Celery task, which fires once per first install, so
    this needs no dedupe of its own.
    """
    if not is_slack_app_assistant_enabled(integration):
        return
    slack_user_id = ((integration.config or {}).get("authed_user") or {}).get("id")
    if not slack_user_id:
        return
    text, blocks = build_install_welcome(integration)
    try:
        SlackIntegration(integration).client.chat_postMessage(
            channel=slack_user_id, text=text, blocks=blocks, unfurl_links=False, unfurl_media=False
        )
    except Exception:
        logger.warning("slack_app_install_welcome_failed", integration_id=integration.id, exc_info=True)
