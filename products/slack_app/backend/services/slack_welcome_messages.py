"""What PostHog says the first time someone meets it in Slack.

Three moments: the app is added to a channel, someone joins a workspace that already has
it, or someone opens the assistant pane. Keeping them in one module is what stops the list
of things worth knowing from drifting apart per surface. A fresh install is the fourth,
and it gets the onboarding DM in ``onboarding.py`` instead, which carries the same
material around its setup steps.

A builder takes the integration and returns the ``(fallback_text, blocks)`` pair
``chat_postMessage`` wants. The fallback text is what a notification and a screen reader
get, so it says the one thing the message is for rather than repeating the whole of it.
Delivery stays in ``api.py`` with the event router, welded to region routing and the
dedupe claim.
"""

from __future__ import annotations

from typing import Any

from posthog.helpers.slack_subscription_explore import BOT_SETUP_DOCS_URL
from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_messages import app_home_url, context_block, section_block


def _bullets(title: str, lines: tuple[str, ...]) -> dict[str, Any]:
    return section_block("*{}*\n{}".format(title, "\n".join(f"• {line}" for line in lines)))


def _docs_button_block() -> dict[str, Any]:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Read the docs"},
                "url": BOT_SETUP_DOCS_URL,
            }
        ],
    }


def _feedback_block() -> dict[str, Any]:
    """The ask for a rating, in the one wording all three messages share.

    Every welcome carries it because the thumbs are the only channel a Slack reader has
    back to us, and nothing else in the product points at them. Only the clicked thumbs
    asks for a reason, so the reaction is named after it rather than beside it.
    """
    return section_block(
        "*Tell me when I get it wrong*\nHit the thumbs under my replies. A thumbs down asks what went "
        "wrong, and that goes straight to the team building me. You can also react with :thumbsup: or "
        ":thumbsdown:."
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


def build_assistant_pane_welcome() -> str:
    """Greets someone opening Slack's assistant container, beside the suggested prompts.

    Plain text and no blocks, because the container takes a ``text`` payload, so none of the
    section and button structure the other two share transfers here. The pane runs the same
    mention workflow, so the model and project classifiers answer in it as well.
    """
    return (
        "Hi! I'm PostHog, an AI agent. Ask me about your product data, or tell me what to fix and "
        "I'll open a pull request in a connected repo.\n"
        "• Keep replying here while I'm working and I'll pick up what you say.\n"
        "• Want a different model? Say so: `use fable for this one`.\n"
        "• Answering from the wrong project? Name the one you want: `give me DAU for Staging please`.\n"
        "• `/posthog` lists my commands, and the thumbs under my replies tell me when I get it wrong."
    )


def build_channel_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """Posted in a channel the moment the app is added to it.

    Written for everyone in the channel rather than for whoever did the adding.
    """
    blocks: list[dict[str, Any]] = [
        section_block(
            ":wave: Hey, I'm PostHog. Tag me with `@PostHog` and I'll dig into your product data, poke "
            "around your codebase, or open a pull request to fix something."
        ),
        # One analytics question and one code change, so nobody reads the app as only the
        # half they happened to see first.
        _bullets(
            "Try asking me",
            (
                "`@PostHog why did signups drop in the EU last week?`",
                "`@PostHog open a PR that adds a unit test for src/utils.py`",
            ),
        ),
        _bullets(
            "A few things worth knowing",
            (
                "Tag me again in the thread while I'm working and I'll pick up what you say.",
                "Want a different model? Say so: `@PostHog use fable for this one`, or "
                "`@PostHog run this on opus 5 at high effort`.",
                "Answering from the wrong project? Name the one you want: `@PostHog give me DAU for "
                "Staging please`. `/posthog project` shows your default.",
                "You can DM me instead of tagging me here.",
            ),
        ),
        _feedback_block(),
        context_block(
            "I also unfurl PostHog links shared in this channel. `/posthog` lists my commands, and your "
            f"default model and thread follow-ups live in {_home_tab(integration)}."
        ),
        _docs_button_block(),
    ]
    return "Hey, I'm PostHog. Tag me with @PostHog to get started.", blocks


def build_team_join_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """DM'd to someone who just joined a workspace that already has the app.

    They inherited a tool nobody introduced them to, so this says what it is before it
    says what it can do. The examples drop the `@PostHog` prefix because a DM needs none.
    """
    blocks: list[dict[str, Any]] = [
        section_block(
            ":wave: Hey, welcome! I'm PostHog, an AI agent your team already uses here. Message me, or tag "
            "`@PostHog` in any channel, and I'll dig into your product data or open a pull request in a "
            "connected repo."
        ),
        _bullets(
            "Try asking me",
            (
                "`why did signups drop in the EU last week?`",
                "`fix the flaky billing CI job`",
            ),
        ),
        _bullets(
            "A few things worth knowing",
            (
                "Keep replying in the thread while I'm working and I'll pick up what you say. "
                "In a channel, tag me in the reply.",
                "Want a different model? Say so: `use fable for this one`.",
            ),
        ),
        _feedback_block(),
        context_block(
            "`/posthog` lists my commands. Your default model, thread follow-ups and linked accounts "
            f"live in {_home_tab(integration)}."
        ),
        _docs_button_block(),
    ]
    return "Hey, welcome! I'm PostHog. Message me to get started.", blocks
