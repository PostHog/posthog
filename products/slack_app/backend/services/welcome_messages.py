"""What PostHog says the first time someone meets it in Slack.

Three moments, one product to describe: the app is added to a channel, someone joins the
workspace, someone installs the app. The audiences differ in what they need next, so each
message leads somewhere different, but they draw on one list of things worth knowing.
Keeping them in one module is what stops that list from drifting apart per surface.

Builders only. Delivery, dedupe and region routing stay in ``api.py``; a builder takes the
integration and returns the ``(fallback_text, blocks)`` pair ``chat_postMessage`` wants.
The fallback text is what a notification and a screen reader get, so it says the one thing
the message is for rather than repeating the whole of it.
"""

from __future__ import annotations

from typing import Any

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_messages import app_home_url, context_block

DOCS_URL = "https://posthog.com/docs/slack-app"

# One analytics question and one code change in every "try this" list, so nobody reads the
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
            ":wave: I'm PostHog, an AI agent. Mention me with `@PostHog` and I'll answer questions about "
            "your product data, dig through your codebase, or open a pull request with a fix."
        ),
        _bullets("Try one of these", _CHANNEL_EXAMPLES),
        _bullets(
            "Worth knowing",
            (
                "Mention me again in the thread to steer a run that's already going.",
                "Ask for a specific model: `@PostHog use fable for this one`, or "
                "`@PostHog run this on opus 5 at high effort`.",
                "`@PostHog project 12345` points your mentions at a different PostHog project.",
                "Rate my replies with the thumbs under them, or react with :thumbsup: or :thumbsdown:.",
                "You can DM me instead of mentioning me here.",
            ),
        ),
        context_block(
            "I also unfurl PostHog links shared in this channel. Your default model and thread "
            f"follow-ups live in {_home_tab(integration)}."
        ),
        _docs_button_block(),
    ]
    return "I'm PostHog. Mention me with @PostHog to get started.", blocks


def build_team_join_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """DM'd to someone who just joined a workspace that already has the app.

    They inherited a tool nobody introduced them to, so this says what it is before it
    says what it can do, and the examples drop the `@PostHog` prefix because a DM needs
    none.
    """
    blocks: list[dict[str, Any]] = [
        _section(
            ":wave: Welcome! I'm PostHog, an AI agent your team uses here. Message me, or mention `@PostHog` "
            "in any channel, and I'll answer questions about your product data or open a pull request in a "
            "connected repo."
        ),
        _bullets("Try one of these", _DM_EXAMPLES),
        _bullets(
            "Worth knowing",
            (
                "Keep replying in the thread to steer a run that's already going. "
                "In a channel, mention me in the reply.",
                "Ask for a specific model: `use fable for this one`.",
                "Rate my replies with the thumbs under them, or react with :thumbsup: or :thumbsdown:.",
            ),
        ),
        context_block(f"Your default model, thread follow-ups and linked accounts live in {_home_tab(integration)}."),
        _docs_button_block(),
    ]
    return "Welcome! I'm PostHog. Message me to get started.", blocks


def build_install_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """DM'd to whoever installed the app, right after the install lands.

    The one reader set up to act for the whole workspace, so this is the only welcome that
    covers routing other people's mentions and connecting a GitHub account.
    """
    blocks: list[dict[str, Any]] = [
        _section(
            ":tada: Thanks for installing PostHog! I'm an AI agent: I answer questions about your product "
            "data, dig through your codebase, and open pull requests in your connected repos."
        ),
        _bullets(
            "Start here",
            (
                "Invite me to a channel with `/invite @PostHog`, then mention me with a request.",
                "Or send me a message right here.",
            ),
        ),
        _bullets(
            "Set it up for the team",
            (
                "`@PostHog project 12345` points your mentions at a PostHog project. Slack admins can set "
                "the workspace default with `@PostHog project workspace 12345`.",
                f"{_home_tab(integration, 'My Home tab')} holds the default AI model, thread follow-ups and "
                "the tasks your workspace has started. Connect your GitHub there so pull requests open "
                "under your own account.",
            ),
        ),
        _docs_button_block(),
    ]
    return "Thanks for installing PostHog! Mention me with @PostHog, or message me here.", blocks
