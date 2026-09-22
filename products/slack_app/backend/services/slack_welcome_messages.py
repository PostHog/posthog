"""What PostHog says the first time someone meets it in Slack.

Four moments: a fresh install, the app is added to a channel, someone joins a workspace
that already has it, or someone opens the assistant pane. Keeping them in one module is
what stops the list of things worth knowing from drifting apart per surface.

A builder takes the integration and returns the ``(fallback_text, blocks)`` pair
``chat_postMessage`` wants. The fallback text is what a notification and a screen reader
get, so it says the one thing the message is for rather than repeating the whole of it.
Delivery stays in ``api.py`` with the event router, welded to region routing and the
dedupe claim.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings

from posthog.helpers.slack_subscription_explore import BOT_SETUP_DOCS_URL
from posthog.models.integration import Integration, SlackIntegration
from posthog.utils import absolute_uri

from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled
from products.slack_app.backend.inbox_channel import (
    INBOX_CHANNEL_REQUIRED_SCOPES,
    _channel_exists,
    _get_team_channel,
    channel_id_from_target,
    channel_name_from_target,
)
from products.slack_app.backend.services.slack_messages import app_home_url, context_block, section_block

# Block Kit action ids for the onboarding DM, kept in sync with the interactivity router.
INBOX_CREATE_ACTION_ID = "slack_inbox_create"
INBOX_JOIN_ACTION_ID = "slack_inbox_join"
# The block_id carries the integration id so the checkbox interaction can be region-routed.
INBOX_SOURCES_CHECKBOXES_ACTION = "slack_inbox_sources_select"
INBOX_SOURCES_BLOCK_PREFIX = "slack_inbox_sources_block"
# AI approval is a hard prerequisite — without it no signals are emitted. block_id carries the integration id.
INBOX_AI_APPROVAL_ACTION_ID = "slack_inbox_ai_approval"
INBOX_AI_APPROVAL_BLOCK_PREFIX = "slack_inbox_ai_approval_block"


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
    mention workflow, so the model and project classifiers answer in it as well. No
    ``/posthog``: the slash commands are not reachable from a DM.
    """
    return (
        "Hi! I'm PostHog, an AI agent. Ask me about your product data, or tell me what to fix and "
        "I'll open a pull request in a connected repo.\n"
        "• Keep replying here while I'm working and I'll pick up what you say.\n"
        "• Want a different model? Say so: `use fable for this one`.\n"
        "• Answering from the wrong project? Name the one you want: `give me DAU for Staging please`.\n"
        "• Hit the thumbs under my replies when I get something wrong."
    )


def build_channel_welcome(integration: Integration) -> tuple[str, list[dict[str, Any]]]:
    """Posted in a channel the moment the app is added to it.

    Written for everyone in the channel rather than for whoever did the adding.
    """
    worth_knowing = [
        "Tag me again in the thread while I'm working and I'll pick up what you say.",
        "Want a different model? Say so: `@PostHog use fable for this one`, or "
        "`@PostHog run this on opus 5 at high effort`.",
        "Answering from the wrong project? Name the one you want: `@PostHog give me DAU for "
        "Staging please`. `/posthog project` shows your default.",
    ]
    # Unlike the DM welcome, this path posts to whichever install serves the workspace, so the
    # scopes are unchecked until here. An install without them never receives the `message.im`
    # event, so the DM would go unanswered with nothing to tell the reader why.
    if is_slack_app_assistant_enabled(integration):
        worth_knowing.append("You can DM me instead of tagging me here.")
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
        _bullets("A few things worth knowing", tuple(worth_knowing)),
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
            "In a channel, `/posthog` lists my commands. Your default model, thread follow-ups and "
            f"linked accounts live in {_home_tab(integration)}."
        ),
        _docs_button_block(),
    ]
    return "Hey, welcome! I'm PostHog. Message me to get started.", blocks


# The install onboarding DM. `onboarding.py` owns what the reader's answers do: the status
# queries, the click handlers and the install flow.


def _button(label: str, action_id: str, value: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": value,
        "style": "primary",
    }


def _public_url(path: str) -> str:
    """Public base URL for links delivered to Slack. In local dev, prefer the ngrok tunnel so the link
    is reachable from outside (mirrors ``OauthIntegration.redirect_uri``)."""
    if settings.DEBUG and settings.NGROK_URL:
        return f"{settings.NGROK_URL.rstrip('/')}{path}"
    return absolute_uri(path)


def _done(text: str) -> dict:
    return context_block(f":white_check_mark: {text}")


def _github_connect_url(team_id: int) -> str:
    """GitHub OAuth entry that returns to Slack — one flow connects the team install and the user's personal GitHub."""
    return _public_url(f"/integrations/connect/github/?project_id={team_id}&connect_from=slack")


def _github_blocks(integration: Integration, *, done: bool) -> list[dict]:
    blocks: list[dict] = [
        section_block(
            "*1. Connect your codebase* :wrench:\nConnect GitHub so I can fix things, not just flag them - "
            "when I spot a problem in your product I'll proactively open a pull request with the fix for you to review."
        )
    ]
    if done:
        blocks.append(_done("Connected"))
        return blocks
    # Pure URL button (no action_id): clicking just opens OAuth in the browser and fires no
    # interaction. The callback returns to Slack; the message updates next time it's rebuilt.
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": "Connect GitHub"},
        "url": _github_connect_url(integration.team_id),
        "style": "primary",
    }
    blocks.append({"type": "actions", "elements": [button]})
    return blocks


def _sources_blocks(integration: Integration) -> list[dict]:
    """Inline checkboxes (current state pre-checked) — ticking sets a source up immediately, unticking turns it off."""
    from products.signals.backend.facade.api import (
        onboarding_sources,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    sources = onboarding_sources(integration.team_id)
    tickable = [source for source in sources if source.togglable]
    options = [
        {
            "text": {"type": "mrkdwn", "text": f"*{source.label}*: {source.description}"},
            "value": source.key,
        }
        for source in tickable
    ]
    checkboxes: dict = {"type": "checkboxes", "action_id": INBOX_SOURCES_CHECKBOXES_ACTION, "options": options}
    initial = [option for option, source in zip(options, tickable) if source.enabled]
    if initial:
        checkboxes["initial_options"] = initial
    blocks = [
        section_block("*2. Choose what I watch* :eyes:\nTick the signals I should monitor and investigate."),
        {"type": "actions", "block_id": f"{INBOX_SOURCES_BLOCK_PREFIX}:{integration.id}", "elements": [checkboxes]},
    ]
    # Sources set up elsewhere have no checkbox, so say what's already watching. Without this the
    # step reads as done with nothing ticked.
    elsewhere = [source.label for source in sources if not source.togglable and source.enabled]
    if elsewhere:
        blocks.append(context_block(f"Already watching: {', '.join(elsewhere)}"))
    return blocks


def _channel_blocks(integration: Integration, slack: SlackIntegration, *, done: bool) -> list[dict]:
    blocks: list[dict] = [
        section_block(
            "*3. Where I report* :inbox_tray:\nEverything I find lands in one shared channel so the team stays in the loop."
        )
    ]
    if done:
        blocks.append(_done("Posting to #posthog-inbox"))
        return blocks
    configured = _get_team_channel(integration.team_id)
    channel_exists = configured is not None and _channel_exists(slack, channel_id_from_target(configured))
    has_scope = not slack.missing_scopes(INBOX_CHANNEL_REQUIRED_SCOPES)
    value = json.dumps({"integration_id": integration.id})
    name = channel_name_from_target(configured or "") if channel_exists else "#posthog-inbox"
    if channel_exists and has_scope:
        blocks.append({"type": "actions", "elements": [_button(f"Join {name}", INBOX_JOIN_ACTION_ID, value)]})
    elif channel_exists:
        blocks.append(context_block(f"Join {name} in your workspace."))
    elif has_scope:
        blocks.append(
            {"type": "actions", "elements": [_button("Create #posthog-inbox", INBOX_CREATE_ACTION_ID, value)]}
        )
    else:
        blocks.append(
            context_block(f"Create a #posthog-inbox channel, then set it in your <{_public_url('/inbox')}|inbox>.")
        )
    return blocks


def _ai_approval_blocks(integration: Integration, *, is_admin: bool) -> list[dict]:
    """The approval prompt — only rendered when not yet approved. Admins tick a checkbox to approve;
    non-admins get an 'ask an admin' note, since only ADMIN+ can toggle org settings."""
    blocks: list[dict] = [
        section_block(
            "*4. Approve AI data processing*\nTo investigate your product I use external AI "
            "providers (Anthropic, OpenAI, Google, Microsoft). This can involve transferring identifying user data, "
            "and is never used to train third-party models. FYI it's not HIPAA-compliant yet, and any BAA you have "
            "with PostHog won't cover these features."
        )
    ]
    if not is_admin:
        blocks.append(context_block(":warning: Ask an org admin to approve. Until then I can't get started."))
        return blocks
    blocks.append(
        {
            "type": "actions",
            "block_id": f"{INBOX_AI_APPROVAL_BLOCK_PREFIX}:{integration.id}",
            "elements": [
                {
                    "type": "checkboxes",
                    "action_id": INBOX_AI_APPROVAL_ACTION_ID,
                    "options": [
                        {"text": {"type": "plain_text", "text": "Approve AI data processing"}, "value": "approve"}
                    ],
                }
            ],
        }
    )
    return blocks


def build_onboarding_dm(
    integration: Integration,
    slack: SlackIntegration,
    *,
    needs_ai_approval: bool = False,
    ai_approval_is_admin: bool = True,
    needs_github: bool = False,
    already_in_channel: bool = False,
) -> tuple[str, list[dict]]:
    """Return (fallback_text, Block Kit blocks) for the inbox onboarding DM.

    Every step is always shown with its state (done steps render a '✅' line). AI approval is the one
    exception: omitted once approved. Always returns a full message — the DM is posted unconditionally.
    """
    intro = section_block(
        "👋 *Hi, I'm PostHog - self-driving for your product*\nI'm an AI agent on autopilot: I watch your product "
        "for problems, investigate them myself, and open pull requests to fix them - so issues get handled before "
        "they reach your backlog."
    )
    # Above the steps because it is the half of the product the steps never describe, and a reader
    # who stops at the setup checklist would otherwise never learn the agent answers questions.
    interactive = section_block(
        "💬 *You can also just talk to me*\nTag `@PostHog` in any channel, or message me here, to dig into your "
        "product data or open a pull request. Name a project to route one question: `@PostHog give me DAU for "
        "Staging please`. In a channel, `/posthog` lists my commands."
    )
    blocks: list[dict] = [intro, interactive, {"type": "divider"}]
    blocks += _github_blocks(integration, done=not needs_github)
    blocks += _sources_blocks(integration)
    blocks += _channel_blocks(integration, slack, done=already_in_channel)
    if needs_ai_approval:
        blocks += _ai_approval_blocks(integration, is_admin=ai_approval_is_admin)
    blocks.append(
        context_block(
            "🎉 Once you're set up, I'll start watching your product and send your first report to "
            "#posthog-inbox as soon as I spot something."
        )
    )
    blocks.append(
        context_block(
            "👍 Hit the thumbs under my replies when I get something wrong. Your default model and linked "
            f"accounts live in {_home_tab(integration)}."
        )
    )
    return "Set up PostHog - self-driving for your product", blocks
