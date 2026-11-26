"""The Slack card that asks people to review a pull request that stamphog did not approve.

One card is posted per human request and edited in place as the pull request changes. The card
never decides anything: ``logic/human_requests.py`` decides the state, and this module only renders
it and talks to Slack.

The title, logins, note and reviewer findings come from the pull request or from model output over
it, so every one of them goes through ``escape_slack_mrkdwn`` and is clipped. That stops a pull
request from mentioning a channel, breaking out of a link, or making Slack refuse the post.
"""

from __future__ import annotations

import re
import json
from collections.abc import Sequence
from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import SlackIntegration
from posthog.slack.channels import (
    MAX_BUTTON_TEXT_CHARS,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    SlackPostRefused,
    clip_text,
    context_block,
    fields_block,
    post_message,
    post_with_join,
    section_block,
    update_message,
)
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.utils import get_instance_region

from ..facade.enums import HumanRequestStatus

logger = structlog.get_logger(__name__)

# The click handler routes every action id with this prefix to stamphog.
ACTION_ID_PREFIX = "stamphog_human."
LOOK_ACTION_ID = f"{ACTION_ID_PREFIX}look"
STOP_LOOKING_ACTION_ID = f"{ACTION_ID_PREFIX}stop_looking"
# No colon: the Slack app's interactivity handler reads a block id with a colon as a picker context token.
ACTIONS_BLOCK_ID = "stamphog_human_actions"

_SOURCE = "stamphog"
# Enough findings to say why stamphog did not approve. The full review is on the pull request.
_MAX_FINDINGS = 5
_MAX_FINDING_CHARS = 300
_MAX_TITLE_CHARS = 200
# Slack renders a mention only for an id of this shape, so any other stored value is shown as text.
_SLACK_USER_ID = re.compile(r"^[UW][A-Z0-9]{2,}$")

_STATUS_LINES: dict[HumanRequestStatus, str] = {
    HumanRequestStatus.PENDING: "Stamphog is reviewing the new commits.",
    HumanRequestStatus.STAMPHOG_APPROVED: "✅ Stamphog approved the new commits. No review needed.",
    HumanRequestStatus.MERGED: "Merged.",
    HumanRequestStatus.CLOSED: "Closed without merging.",
}
# People can still say they will look while stamphog reviews new commits.
_STATUSES_WITH_BUTTONS = frozenset({HumanRequestStatus.OPEN, HumanRequestStatus.PENDING})


class HumanRequestSlackError(Exception):
    """The card could not be posted: no Slack integration, or the app cannot reach the channel."""


@frozen
class CardLooker:
    slack_user_id: str
    display_name: str


@frozen
class HumanRequestCard:
    """Everything the card shows. Strings are raw here and escaped when rendered."""

    request_id: str
    team_id: int
    integration_id: int
    status: HumanRequestStatus
    repository: str
    pr_number: int
    pr_url: str
    title: str
    additions: int
    deletions: int
    changed_files: int
    # Logins and team slugs that GitHub lists as requested reviewers now.
    requested_on_github: tuple[str, ...]
    # Only from a run whose verdict GitHub already shows. Empty otherwise.
    findings: tuple[str, ...]
    stamphog_failed: bool
    note: str
    requester_slack_user_id: str
    requester_name: str
    lookers: tuple[CardLooker, ...]
    approved_by_login: str


def _mention_or_name(slack_user_id: str, name: str) -> str:
    if _SLACK_USER_ID.match(slack_user_id):
        return f"<@{slack_user_id}>"
    return escape_slack_mrkdwn(name or slack_user_id)


def _join_names(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _link(url: str, label: str) -> str:
    # The label is escaped, and a `|` would end it early. The URL is GitHub's own html_url.
    return f"<{url}|{escape_slack_mrkdwn(label).replace('|', '/')}>"


def _heading(card: HumanRequestCard) -> str:
    title = escape_slack_mrkdwn(clip_text(card.title, _MAX_TITLE_CHARS))
    return clip_text(f"*{_link(card.pr_url, f'{card.repository}#{card.pr_number}')}* · {title}", MAX_SECTION_CHARS)


def _status_line(card: HumanRequestCard) -> str:
    if card.status == HumanRequestStatus.APPROVED:
        return f"✅ Approved by {escape_slack_mrkdwn(card.approved_by_login)}"
    return _STATUS_LINES.get(card.status, "")


def _size(card: HumanRequestCard) -> str:
    files = "file" if card.changed_files == 1 else "files"
    return f"+{card.additions} −{card.deletions} · {card.changed_files} {files}"


def _requested(card: HumanRequestCard) -> str:
    if not card.requested_on_github:
        return "No one"
    return clip_text(", ".join(escape_slack_mrkdwn(name) for name in card.requested_on_github), 1900)


def _notes(card: HumanRequestCard) -> str:
    if card.stamphog_failed:
        return "*Stamphog's notes*\nStamphog couldn't finish its review."
    if not card.findings:
        return ""
    lines = [
        f"• {escape_slack_mrkdwn(clip_text(finding, _MAX_FINDING_CHARS))}" for finding in card.findings[:_MAX_FINDINGS]
    ]
    return clip_text("*Stamphog's notes*\n" + "\n".join(lines), MAX_SECTION_CHARS)


def _asked_by(card: HumanRequestCard) -> str:
    if card.requester_slack_user_id or card.requester_name:
        return f"Asked by {_mention_or_name(card.requester_slack_user_id, card.requester_name)}"
    return ""


def _looking(card: HumanRequestCard) -> str:
    if not card.lookers:
        return ""
    names = [_mention_or_name(looker.slack_user_id, looker.display_name) for looker in card.lookers]
    verb = "is" if len(names) == 1 else "are"
    return clip_text(f"👀 {_join_names(names)} {verb} looking", MAX_SECTION_CHARS)


def button_value(card: HumanRequestCard) -> str:
    """What a click carries back. The integration and region let the click handler find the region that owns the request."""
    return json.dumps(
        {
            "integration_id": card.integration_id,
            "team_id": card.team_id,
            "request_id": card.request_id,
            "region": get_instance_region() or "",
        }
    )


def _button(text: str, action_id: str, value: str, *, primary: bool = False) -> dict[str, Any]:
    # posthog.slack.channels builds link buttons only, and these carry an action id and a value instead.
    element: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": clip_text(text, MAX_BUTTON_TEXT_CHARS), "emoji": True},
        "action_id": action_id,
        "value": value,
    }
    if primary:
        element["style"] = "primary"
    return element


def card_blocks(card: HumanRequestCard) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [section_block(_heading(card))]
    if status_line := _status_line(card):
        blocks.append(section_block(status_line))
    blocks.append(fields_block([f"*Size*\n{_size(card)}", f"*Requested on GitHub*\n{_requested(card)}"]))
    if notes := _notes(card):
        blocks.append(section_block(notes))
    if card.note:
        blocks.append(section_block(clip_text(f"*Note*\n{escape_slack_mrkdwn(card.note)}", MAX_SECTION_CHARS)))
    context = [line for line in (_asked_by(card), _looking(card)) if line]
    blocks.extend(context_block(line) for line in context)
    if card.status in _STATUSES_WITH_BUTTONS:
        value = button_value(card)
        buttons = [_button("I'll take a look", LOOK_ACTION_ID, value, primary=True)]
        if card.lookers:
            buttons.append(_button("Stop looking", STOP_LOOKING_ACTION_ID, value))
        blocks.append({"type": "actions", "block_id": ACTIONS_BLOCK_ID, "elements": buttons})
    return blocks


def card_text(card: HumanRequestCard) -> str:
    """The notification preview and the text for clients that ignore blocks. Slack parses it for mentions too."""
    title = clip_text(card.title, _MAX_TITLE_CHARS)
    return clip_text(
        escape_slack_mrkdwn(f"Review requested: {card.repository}#{card.pr_number} {title}"), MAX_TEXT_CHARS
    )


def find_card_integration(team_id: int) -> int | None:
    """The id of the team's Slack integration that posts cards, the same one the digest uses."""
    integration = IntegrationManager.slack.oauth.find(team_id)
    return integration.id if integration is not None else None


def _slack(team_id: int, integration_id: int) -> SlackIntegration:
    try:
        integration = IntegrationManager.slack.oauth.get(team_id, integration_id)
    except IntegrationNotFound as e:
        raise HumanRequestSlackError(f"No Slack integration {integration_id} for team {team_id}") from e
    return SlackIntegration(integration, source=_SOURCE)


def post_card(card: HumanRequestCard, channel_id: str, channel_name: str) -> str:
    """Post the card and return its ts. Raises ``HumanRequestSlackError`` when Slack cannot take it."""
    slack = _slack(card.team_id, card.integration_id)
    try:
        ts = post_with_join(slack, channel_id, card_blocks(card), card_text(card), channel_name=channel_name or None)
    except SlackPostRefused as e:
        raise HumanRequestSlackError(str(e)) from e
    if not ts:
        raise HumanRequestSlackError(f"Slack returned no ts for the card in {channel_id}")
    return ts


def update_card(card: HumanRequestCard, channel_id: str, ts: str) -> None:
    """Edit the posted card in place. It must go through the integration that posted it."""
    update_message(_slack(card.team_id, card.integration_id), channel_id, ts, card_blocks(card), card_text(card))


def ping_lookers(card: HumanRequestCard, channel_id: str, ts: str, *, reviewing: bool) -> None:
    """Tell the people looking, in the card's thread, that new commits arrived. Never raises.

    The caller records the head before it calls this, so a failed reply is lost rather than sent twice.
    """
    mentions = [f"<@{looker.slack_user_id}>" for looker in card.lookers if _SLACK_USER_ID.match(looker.slack_user_id)]
    if not mentions:
        return
    text = f"{' '.join(mentions)} new commits were pushed."
    if reviewing:
        text += " Stamphog is reviewing them."
    try:
        post_message(_slack(card.team_id, card.integration_id), channel_id, [section_block(text)], text, thread_ts=ts)
    except Exception as e:
        logger.warning("stamphog_human_request_ping_failed", slack_channel_id=channel_id, error=str(e))
