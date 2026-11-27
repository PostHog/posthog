"""The Slack card that asks people to review a pull request that stamphog did not approve.

One card is posted per Broadcast request and edited in place as the pull request changes. The card
never decides anything: ``logic/broadcast_requests.py`` decides the state, and this module only renders
it and talks to Slack.

The title, logins, note and reviewer findings come from the pull request or from model output over
it, so every one of them goes through ``escape_slack_mrkdwn`` and is clipped. That stops a pull
request from mentioning a channel, breaking out of a link, or making Slack refuse the post.
"""

from __future__ import annotations

import re
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from slack_sdk.errors import SlackApiError

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
from posthog.utils import get_instance_region, ordinal

from ..facade.enums import BroadcastRequestStatus

logger = structlog.get_logger(__name__)

# The click handler routes every action id with this prefix to stamphog.
ACTION_ID_PREFIX = "stamphog_broadcast."
LOOK_ACTION_ID = f"{ACTION_ID_PREFIX}look"
STOP_LOOKING_ACTION_ID = f"{ACTION_ID_PREFIX}stop_looking"
# No colon: the Slack app's interactivity handler reads a block id with a colon as a picker context token.
ACTIONS_BLOCK_ID = "stamphog_broadcast_actions"

_SOURCE = "stamphog"
ALLOW_BROADCAST_HINT = (
    "Next time, comment `@posthog stamp --allow-broadcast` on the pull request, or set `allow_broadcast` "
    "in the MCP review request. Stamphog reviews it first and posts in this channel only if it doesn't approve."
)
# Enough findings to say why stamphog did not approve. The full review is on the pull request.
_MAX_FINDINGS = 5
_MAX_FINDING_CHARS = 300
_MAX_TITLE_CHARS = 200
# The length of BroadcastRequestDelivery.permalink.
_MAX_PERMALINK_CHARS = 512
# Slack renders a mention only for an id of this shape, so any other stored value is shown as text.
_SLACK_USER_ID = re.compile(r"^[UW][A-Z0-9]{2,}$")

_STATUS_LINES: dict[BroadcastRequestStatus, str] = {
    # A new run can start at the same head, for example after new evidence, so this line names no commits.
    BroadcastRequestStatus.PENDING: "Stamphog is reviewing again.",
    BroadcastRequestStatus.STAMPHOG_APPROVED: "✅ Stamphog approved the new commits. No review needed.",
    BroadcastRequestStatus.MERGED: "Merged.",
    BroadcastRequestStatus.CLOSED: "Closed without merging.",
}
# People can still say they will look while stamphog reviews new commits.
_STATUSES_WITH_BUTTONS = frozenset({BroadcastRequestStatus.OPEN, BroadcastRequestStatus.PENDING})


# Slack errors that a retry cannot fix: the card or the channel is gone, or the integration lost access.
_PERMANENT_SLACK_ERRORS = frozenset(
    {
        "account_inactive",
        "cant_update_message",
        "channel_not_found",
        "invalid_auth",
        "invalid_blocks",
        "is_archived",
        "message_not_found",
        "not_authed",
        "token_revoked",
    }
)


class BroadcastRequestSlackError(Exception):
    """The card could not be posted or edited, and a retry would fail the same way."""


def _raise_if_permanent(e: SlackApiError) -> None:
    error = str(e.response.get("error") or "")
    if error in _PERMANENT_SLACK_ERRORS:
        raise BroadcastRequestSlackError(f"Slack refused the card: {error}") from e


@frozen
class CardLooker:
    slack_user_id: str
    display_name: str


@frozen
class BroadcastRequestCard:
    """Everything the card shows. Strings are raw here and escaped when rendered."""

    request_id: str
    team_id: int
    integration_id: int
    status: BroadcastRequestStatus
    repository: str
    pr_number: int
    pr_url: str
    title: str
    additions: int
    deletions: int
    changed_files: int
    requested_on_github: tuple[str, ...]
    # Only from a run whose verdict GitHub already shows. Empty otherwise.
    findings: tuple[str, ...]
    stamphog_failed: bool
    note: str
    requester_slack_user_id: str
    requester_name: str
    lookers: tuple[CardLooker, ...]
    approved_by_login: str
    requester_card_count: int | None = None
    # A card that a pull request link opened, whose poster may not know the command that asks Stamphog first.
    from_link_post: bool = False


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


def _heading(card: BroadcastRequestCard) -> str:
    title = escape_slack_mrkdwn(clip_text(card.title, _MAX_TITLE_CHARS))
    return clip_text(f"*{_link(card.pr_url, f'{card.repository}#{card.pr_number}')}* · {title}", MAX_SECTION_CHARS)


def _status_line(card: BroadcastRequestCard) -> str:
    if card.status == BroadcastRequestStatus.APPROVED:
        return f"✅ Approved by {escape_slack_mrkdwn(card.approved_by_login)}"
    return _STATUS_LINES.get(card.status, "")


def _size(card: BroadcastRequestCard) -> str:
    files = "file" if card.changed_files == 1 else "files"
    return f"+{card.additions} −{card.deletions} · {card.changed_files} {files}"


def _requested(card: BroadcastRequestCard) -> str:
    if not card.requested_on_github:
        return "No one"
    return clip_text(", ".join(escape_slack_mrkdwn(name) for name in card.requested_on_github), 1900)


def _notes(card: BroadcastRequestCard) -> str:
    if card.stamphog_failed:
        return "*Stamphog's notes*\nStamphog couldn't finish its review."
    if not card.findings:
        return ""
    lines = [
        f"• {escape_slack_mrkdwn(clip_text(finding, _MAX_FINDING_CHARS))}" for finding in card.findings[:_MAX_FINDINGS]
    ]
    return clip_text("*Stamphog's notes*\n" + "\n".join(lines), MAX_SECTION_CHARS)


def _asked_by(card: BroadcastRequestCard) -> str:
    if not (card.requester_slack_user_id or card.requester_name):
        return ""
    line = f"Asked by {_mention_or_name(card.requester_slack_user_id, card.requester_name)}"
    # A first card says nothing, so the count shows only for a person who asks again.
    if card.requester_card_count is not None and card.requester_card_count >= 2:
        line += f" · {ordinal(card.requester_card_count)} this week"
    return line


def _looking(card: BroadcastRequestCard) -> str:
    if not card.lookers:
        return ""
    names = [_mention_or_name(looker.slack_user_id, looker.display_name) for looker in card.lookers]
    verb = "is" if len(names) == 1 else "are"
    return clip_text(f"👀 {_join_names(names)} {verb} looking", MAX_SECTION_CHARS)


def button_value(card: BroadcastRequestCard) -> str:
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


def _verbatim(block: dict[str, Any]) -> dict[str, Any]:
    """Mark every mrkdwn text object of ``block`` verbatim.

    Escaping stops `<!here>`, but Slack also turns a bare `@here`, `@channel` or `@everyone` into a broadcast
    unless the text is verbatim. The title, the findings and the note can carry one. Links and `<@U...>`
    mentions that the card writes itself still render.
    """
    for text in [block.get("text"), *block.get("fields", []), *block.get("elements", [])]:
        if isinstance(text, dict) and text.get("type") == "mrkdwn":
            text["verbatim"] = True
    return block


def card_blocks(card: BroadcastRequestCard) -> list[dict[str, Any]]:
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
    if card.from_link_post:
        blocks.append(context_block(ALLOW_BROADCAST_HINT))
    return [_verbatim(block) for block in blocks]


def card_text(card: BroadcastRequestCard) -> str:
    """The notification preview and the text for clients that ignore blocks.

    It leaves out the title, because this text cannot be marked verbatim and Slack parses it for mentions too.
    """
    return clip_text(escape_slack_mrkdwn(f"Review requested: {card.repository}#{card.pr_number}"), MAX_TEXT_CHARS)


@frozen
class LookClick:
    """A click on a card's look or stop-looking button, as Slack describes it."""

    team_id: int
    broadcast_request_id: str
    integration_id: int
    # The workspace the click came from, and the clicker's own workspace. They differ for a person from
    # another workspace in a Slack Connect channel.
    slack_team_id: str
    slack_user_team_id: str
    channel_id: str
    message_ts: str
    slack_user_id: str
    display_name: str
    looking: bool


def parse_look_click(payload: Mapping[str, Any], action: Mapping[str, Any]) -> LookClick | None:
    """Read a click on the card's buttons, or None when it is not one or a field is missing or malformed."""
    action_id = action.get("action_id")
    if action_id not in (LOOK_ACTION_ID, STOP_LOOKING_ACTION_ID):
        return None
    try:
        value = json.loads(action.get("value") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    integration_id, team_id, request_id = value.get("integration_id"), value.get("team_id"), value.get("request_id")
    if not isinstance(integration_id, int) or not isinstance(team_id, int) or not isinstance(request_id, str):
        return None
    try:
        uuid.UUID(request_id)
    except ValueError:
        return None
    user = payload.get("user") or {}
    slack_team_id = (payload.get("team") or {}).get("id") or ""
    container = payload.get("container") or {}
    channel_id = (payload.get("channel") or {}).get("id") or container.get("channel_id") or ""
    message_ts = (payload.get("message") or {}).get("ts") or container.get("message_ts") or ""
    slack_user_id = user.get("id") or ""
    if not (slack_team_id and channel_id and message_ts and slack_user_id):
        return None
    return LookClick(
        team_id=team_id,
        broadcast_request_id=request_id,
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        # Slack leaves the clicker's team out of some payloads, and then the clicker is in the click's workspace.
        slack_user_team_id=user.get("team_id") or slack_team_id,
        channel_id=channel_id,
        message_ts=message_ts,
        slack_user_id=slack_user_id,
        display_name=clip_text(user.get("name") or user.get("username") or "", 255),
        looking=action_id == LOOK_ACTION_ID,
    )


def card_workspace(team_id: int, integration_id: int) -> str | None:
    """The Slack workspace id of the integration that posted a card, or None when the integration is gone."""
    try:
        return IntegrationManager.slack.oauth.get(team_id, integration_id).integration_id
    except IntegrationNotFound:
        return None


def find_card_integration(team_id: int) -> int | None:
    """The id of the team's Slack integration that posts cards, the same one the digest uses."""
    integration = IntegrationManager.slack.oauth.find(team_id)
    return integration.id if integration is not None else None


def _slack(team_id: int, integration_id: int) -> SlackIntegration:
    try:
        integration = IntegrationManager.slack.oauth.get(team_id, integration_id)
    except IntegrationNotFound as e:
        raise BroadcastRequestSlackError(f"No Slack integration {integration_id} for team {team_id}") from e
    return SlackIntegration(integration, source=_SOURCE)


def post_card(card: BroadcastRequestCard, channel_id: str, channel_name: str, *, thread_ts: str = "") -> str:
    """Post the card and return its ts. With ``thread_ts``, the card is a reply in that post's thread.

    Raises ``BroadcastRequestSlackError`` when Slack cannot take it, and lets a transient Slack error through
    so the task retries.
    """
    slack = _slack(card.team_id, card.integration_id)
    try:
        if thread_ts:
            # Slack sent the app the post in this channel, so the app is a member and needs no join.
            response = post_message(slack, channel_id, card_blocks(card), card_text(card), thread_ts=thread_ts)
            ts = response.get("ts")
        else:
            ts = post_with_join(
                slack, channel_id, card_blocks(card), card_text(card), channel_name=channel_name or None
            )
    except SlackPostRefused as e:
        raise BroadcastRequestSlackError(str(e)) from e
    except SlackApiError as e:
        _raise_if_permanent(e)
        raise
    if not ts:
        raise BroadcastRequestSlackError(f"Slack returned no ts for the card in {channel_id}")
    return ts


def post_thread_reply(team_id: int, integration_id: int, channel_id: str, thread_ts: str, text: str) -> None:
    """Reply in a thread with fixed text.

    A permanent Slack error is logged. Any other error raises, so the caller's task retries: the reply is
    the only answer the person gets, and the post's claim stops Slack from delivering the post again.
    """
    try:
        post_message(_slack(team_id, integration_id), channel_id, [section_block(text)], text, thread_ts=thread_ts)
    except SlackApiError as e:
        if str(e.response.get("error") or "") not in _PERMANENT_SLACK_ERRORS:
            raise
        logger.warning("stamphog_broadcast_thread_reply_failed", slack_channel_id=channel_id, error=str(e))


def card_permalink(card: BroadcastRequestCard, channel_id: str, ts: str) -> str:
    """The link Slack gives for the posted card, or "" when Slack does not give one. Never raises.

    It runs after the post committed, and nothing retries it, so a card without a link stays without one.
    """
    try:
        response = _slack(card.team_id, card.integration_id).client.chat_getPermalink(channel=channel_id, message_ts=ts)
        permalink = response.get("permalink") if response.get("ok") else None
    except Exception:
        logger.warning("stamphog_broadcast_card_permalink_failed", broadcast_request_id=card.request_id, exc_info=True)
        return ""
    # The API returns this link as is, so only a plain https link is kept.
    if not isinstance(permalink, str) or not permalink.startswith("https://") or len(permalink) > _MAX_PERMALINK_CHARS:
        logger.warning("stamphog_broadcast_card_permalink_unusable", broadcast_request_id=card.request_id)
        return ""
    return permalink


def update_card(card: BroadcastRequestCard, channel_id: str, ts: str) -> None:
    """Edit the posted card in place. It must go through the integration that posted it.

    Raises ``BroadcastRequestSlackError`` when Slack cannot take the edit, and lets a transient Slack error
    through so the task retries.
    """
    slack = _slack(card.team_id, card.integration_id)
    try:
        update_message(slack, channel_id, ts, card_blocks(card), card_text(card))
    except SlackApiError as e:
        _raise_if_permanent(e)
        raise


def ping_lookers(card: BroadcastRequestCard, channel_id: str, ts: str, *, reviewing: bool) -> None:
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
        logger.warning("stamphog_broadcast_request_ping_failed", slack_channel_id=channel_id, error=str(e))
