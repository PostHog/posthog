from collections.abc import Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from posthog.dataclasses import frozen
from posthog.slack.channels import (
    MAX_BUTTON_URL_CHARS,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    SlackButton,
    clip_text,
    context_block,
    fields_block,
    header_block,
    section_block,
)
from posthog.slack.formatting import escape_slack_mrkdwn

from ..facade import contracts
from .emails import email_domain

PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "aol.com",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "icloud.com",
        "live.com",
        "me.com",
        "msn.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "yahoo.com",
    }
)
MAX_TOUCH_LINES = 10
NO_TOUCHES_TEXT = "No prior research touches found."


@frozen
class SessionBrief:
    blocks: list[dict[str, Any]]
    text: str


def contact_checks_for(session: contracts.ResearchSessionDTO, team_id: int) -> list[contracts.ContactCheckInput]:
    """One check for the attendees' emails, and one per company domain among them."""
    if not session.external_emails:
        return []
    domains = sorted({email_domain(e) for e in session.external_emails} - PERSONAL_EMAIL_DOMAINS)
    return [
        contracts.ContactCheckInput(team_id=team_id, emails=tuple(session.external_emails)),
        *(contracts.ContactCheckInput(team_id=team_id, domain=domain) for domain in domains),
    ]


def _slack_date(moment: datetime, token: str) -> str:
    # The fallback after the pipe shows in clients that cannot localize the date.
    return f"<!date^{int(moment.timestamp())}^{token}|{moment:%Y-%m-%d %H:%M} UTC>"


def _prior_touches(
    session: contracts.ResearchSessionDTO, checks: Sequence[contracts.ContactCheckResult]
) -> list[contracts.ResearchTouch]:
    # The emails check and the domain check return the same touch twice, and the session being
    # briefed matches its own attendees, so it is not a prior touch.
    unique = {touch: None for check in checks for touch in check.touches if touch.session_id != session.id}
    return sorted(unique, key=lambda t: (t.occurred_at is not None, t.occurred_at or datetime.min), reverse=True)


def _touch_line(touch: contracts.ResearchTouch) -> str:
    when = _slack_date(touch.occurred_at, "{date_short}") if touch.occurred_at else "no date"
    owner = escape_slack_mrkdwn(touch.owner_email) or "unknown owner"
    source = escape_slack_mrkdwn(touch.source_label) or touch.channel.label
    return f"• {escape_slack_mrkdwn(touch.contact)}: {touch.channel.label.lower()} from {owner} ({source}), {when}"


def _touches_text(touches: list[contracts.ResearchTouch]) -> str:
    if not touches:
        return f"*Prior research touches*\n{NO_TOUCHES_TEXT}"
    lines = [_touch_line(touch) for touch in touches[:MAX_TOUCH_LINES]]
    if len(touches) > MAX_TOUCH_LINES:
        lines.append(f"…and {len(touches) - MAX_TOUCH_LINES} more")
    return clip_text("*Prior research touches*\n" + "\n".join(lines), MAX_SECTION_CHARS)


def _join_button(meeting_url: str) -> SlackButton | None:
    if urlparse(meeting_url).scheme != "https" or len(meeting_url) > MAX_BUTTON_URL_CHARS:
        return None
    return SlackButton(text="Join", url=meeting_url, primary=True)


def compose_brief(
    session: contracts.ResearchSessionDTO,
    checks: Sequence[contracts.ContactCheckResult],
    *,
    followup_invite: str | None = None,
) -> SessionBrief:
    title = session.title or "Customer research session"
    attendees = ", ".join(escape_slack_mrkdwn(e) for e in session.external_emails) or "None listed"
    touches = _prior_touches(session, checks)
    when = _slack_date(session.start_time, "{date_short_pretty} at {time}")

    blocks: list[dict[str, Any]] = [
        header_block(title),
        fields_block(
            [
                f"*When*\n{when}",
                f"*Organizer*\n{escape_slack_mrkdwn(session.organizer_email) or 'Unknown'}",
            ]
        ),
        section_block(
            clip_text(f"*Customer attendees*\n{attendees}", MAX_SECTION_CHARS),
            button=_join_button(session.meeting_url),
        ),
        section_block(_touches_text(touches)),
    ]
    if followup_invite:
        blocks.append(context_block(followup_invite))

    text = f"Research session: {escape_slack_mrkdwn(title)}, {when}"
    return SessionBrief(blocks=blocks, text=clip_text(text, MAX_TEXT_CHARS))
