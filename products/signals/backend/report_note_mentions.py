"""@mentions in inbox report notes, and the notifications they send.

A note stores a mention inline as `@member:<user id>` or `@role:<role uuid>`, so the note stays a
plain string for the API, MCP, and scouts. The web renderer turns both tokens into chips.

Each mentioned person, and each valid member of a mentioned role, gets the mention on every channel
that is set up for them: in-app, email, mobile push, and Slack. Recipients resolve on a worker at
send time, so a person who lost Inbox access between the write and the send gets nothing. Each
channel is best effort, so one failed channel does not stop the others.
"""

from __future__ import annotations

import re
import uuid
import hashlib
from collections.abc import Collection

from django.db import transaction

import structlog
import posthoganalytics
from celery import shared_task

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, is_email_available
from posthog.event_usage import groups
from posthog.models import OrganizationMembership, Team, User
from posthog.models.scoping import with_team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.tasks.email import NotificationSetting, get_members_to_notify

from products.access_control.backend.facade.api import organization_role_names, valid_role_member_user_ids
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import parse_artefact_content
from products.signals.backend.inbox_push_notifications import notify_report_note_mention
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_urls import ReportLinkSource, build_report_url, report_path
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox
from products.signals.backend.slack_inbox_notifications import deliver_report_note_mention_to_slack

logger = structlog.get_logger(__name__)

FEATURE_FLAG_KEY = "signals-report-note-mentions"
# A role mention reaches every member of the role, so this caps how many people one note can ping.
MAX_MENTION_RECIPIENTS = 50
_EXCERPT_LIMIT = 280
# NotificationEvent.title is a varchar(255).
_TITLE_LIMIT = 255

# A token counts only at the start of the text or after whitespace, the same rule as the web renderer.
_MEMBER_TOKEN = re.compile(r"(?<!\S)@member:(\d+)")
_ROLE_TOKEN = re.compile(r"(?<!\S)@role:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")

_NOTE_ARTEFACT_TYPES = (SignalReportArtefact.ArtefactType.NOTE, SignalReportArtefact.ArtefactType.SCOUT_NOTE_LEFT)
_HIDDEN_STATUSES = (SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED)


@frozen
class NoteMentions:
    user_ids: frozenset[int]
    role_ids: frozenset[uuid.UUID]

    def __bool__(self) -> bool:
        return bool(self.user_ids or self.role_ids)

    def added_since(self, previous: NoteMentions) -> NoteMentions:
        return NoteMentions(user_ids=self.user_ids - previous.user_ids, role_ids=self.role_ids - previous.role_ids)


@frozen
class MentionRecipient:
    user: User
    # The role the recipient was reached through. None when the note names the person directly.
    role_name: str | None


def parse_note_mentions(text: str) -> NoteMentions:
    return NoteMentions(
        user_ids=frozenset(int(match) for match in _MEMBER_TOKEN.findall(text)),
        role_ids=frozenset(uuid.UUID(match) for match in _ROLE_TOKEN.findall(text)),
    )


def display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name or "", user.last_name or "") if part).strip()
    if name:
        return name
    return (user.email or "").split("@", 1)[0] or "Someone"


def render_note_text(text: str, *, names_by_user_id: dict[int, str], names_by_role_id: dict[uuid.UUID, str]) -> str:
    """Replace mention tokens with readable names, so no channel shows a raw token."""

    def member(match: re.Match[str]) -> str:
        return f"@{names_by_user_id.get(int(match.group(1)), 'someone')}"

    def role(match: re.Match[str]) -> str:
        return f"@{names_by_role_id.get(uuid.UUID(match.group(1)), 'a role')}"

    return _ROLE_TOKEN.sub(role, _MEMBER_TOKEN.sub(member, text))


def excerpt(text: str, limit: int = _EXCERPT_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def notification_title(*, author_name: str, role_name: str | None) -> str:
    target = f"@{role_name}" if role_name else "you"
    suffix = f" mentioned {target} on a report"
    # Cut by raw length so a long name cannot overflow the column and fail the write.
    room = _TITLE_LIMIT - len(suffix)
    if len(author_name) > room:
        author_name = author_name[: room - 1] + "…"
    return f"{author_name}{suffix}"[:_TITLE_LIMIT]


def resolve_note_mention_recipients(
    *, team: Team, author_id: int | None, mentions: NoteMentions, role_names: dict[uuid.UUID, str]
) -> list[MentionRecipient]:
    """The people to notify for `mentions`, in a stable order and capped at `MAX_MENTION_RECIPIENTS`.

    A direct mention comes before a role mention of the same person. The author, people outside the
    report's organization, and people without Inbox access are left out.
    """
    candidates: dict[int, str | None] = dict.fromkeys(sorted(mentions.user_ids))
    for role_id in sorted(role_names, key=str):
        for user_id in sorted(valid_role_member_user_ids(role_id=role_id)):
            candidates.setdefault(user_id, role_names[role_id])
    if author_id is not None:
        candidates.pop(author_id, None)
    if not candidates:
        return []

    member_ids = set(
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user_id__in=candidates, user__is_active=True
        ).values_list("user_id", flat=True)
    )
    users_by_id = User.objects.in_bulk([user_id for user_id in candidates if user_id in member_ids])
    recipients: list[MentionRecipient] = []
    for user_id, role_name in candidates.items():
        user = users_by_id.get(user_id)
        if user is None or not may_read_reports(user=user, team=team):
            continue
        recipients.append(MentionRecipient(user=user, role_name=role_name))
        if len(recipients) >= MAX_MENTION_RECIPIENTS:
            break
    return recipients


def schedule_note_mention_notifications(
    *, team_id: int, artefact_id: str, attribution: ArtefactAttribution, mentions: NoteMentions
) -> None:
    """Queue the mention notifications for a note after the write commits.

    Only a person can ping people. A note from an agent or a task never notifies, so an automated
    writer cannot fan out to the organization.
    """
    if not mentions or attribution.kind != "user" or attribution.user_id is None:
        return
    author_id = attribution.user_id
    user_ids = sorted(mentions.user_ids)
    role_ids = sorted(str(role_id) for role_id in mentions.role_ids)

    def enqueue() -> None:
        try:
            send_report_note_mention_notifications.delay(
                team_id=team_id, artefact_id=artefact_id, author_id=author_id, user_ids=user_ids, role_ids=role_ids
            )
        except Exception:
            logger.exception("signals.report_note_mentions.enqueue_failed", team_id=team_id, artefact_id=artefact_id)

    transaction.on_commit(enqueue)


def _mentions_enabled(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                FEATURE_FLAG_KEY,
                str(team.organization_id),
                groups={"organization": str(team.organization_id)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # Fail closed, so a flag service outage cannot turn mention fan-out on for every organization.
        logger.warning("signals.report_note_mentions.flag_check_failed", team_id=team.id, exc_info=True)
        return False


def note_text(artefact_type: str, content: str) -> str | None:
    try:
        parsed = parse_artefact_content(artefact_type, content)
    except Exception:
        return None
    note = getattr(parsed, "note", None)
    return note if isinstance(note, str) else None


@frozen
class _MentionMessage:
    report: SignalReport
    author_name: str
    text: str
    # Changes when the note text changes, so an edit that re-adds a person is a new delivery.
    digest: str


def _send_in_app(message: _MentionMessage, recipients: Collection[MentionRecipient], artefact_id: str) -> int:
    report = message.report
    sent = 0
    for recipient in recipients:
        try:
            event = create_notification(
                NotificationData(
                    team_id=report.team_id,
                    notification_type=NotificationType.COMMENT_MENTION,
                    title=notification_title(author_name=message.author_name, role_name=recipient.role_name),
                    body=message.text,
                    target_type=TargetType.USER,
                    target_id=str(recipient.user.id),
                    resource_id=str(report.id),
                    source_url=report_path(report.team_id, report.id, ReportLinkSource.NOTE_MENTION),
                    idempotency_key=f"report-note-mention:{artefact_id}:{recipient.user.id}:{message.digest}",
                )
            )
            sent += event is not None
        except Exception:
            logger.exception("signals.report_note_mentions.in_app_failed", report_id=str(report.id))
    return sent


def _send_email(message: _MentionMessage, recipients: Collection[MentionRecipient], artefact_id: str) -> int:
    if not recipients or not is_email_available(with_absolute_urls=True):
        return 0
    report = message.report
    try:
        recipient_ids = {recipient.user.id for recipient in recipients}
        # Honors each person's "discussions mentioned" email setting and project access.
        memberships = [
            membership
            for membership in get_members_to_notify(report.team, NotificationSetting.DISCUSSIONS_MENTIONED.value)
            if membership.user_id in recipient_ids
        ]
        if not memberships:
            return 0
        email = EmailMessage(
            # One campaign per note version, so a retry or a re-add after an edit does not send twice.
            campaign_key=f"signals_report_note_mention_{artefact_id}_{message.digest}",
            subject=f"{message.author_name} mentioned you on a report in {report.team.name}",
            template_name="report_note_mentioned",
            template_context={
                "author_name": message.author_name,
                "report_title": report.title or "Untitled report",
                "content": message.text,
                "team": report.team,
                "href": build_report_url(report.team_id, report.id, ReportLinkSource.NOTE_MENTION),
            },
        )
        for membership in memberships:
            email.add_user_recipient(membership.user)
        email.send()
        return len(memberships)
    except Exception:
        logger.exception("signals.report_note_mentions.email_failed", report_id=str(report.id))
        return 0


def _send_push(message: _MentionMessage, recipients: Collection[MentionRecipient], artefact_id: str) -> int:
    try:
        return len(
            notify_report_note_mention(
                message.report,
                [recipient.user for recipient in recipients],
                title=notification_title(author_name=message.author_name, role_name=None),
                body=message.text,
                dedupe_subject=f"{artefact_id}:{message.digest}",
            )
        )
    except Exception:
        logger.exception("signals.report_note_mentions.push_failed", report_id=str(message.report.id))
        return 0


def _send_slack(message: _MentionMessage, recipients: Collection[MentionRecipient]) -> int:
    try:
        return deliver_report_note_mention_to_slack(
            message.report,
            [recipient.user for recipient in recipients],
            author_name=message.author_name,
            text=message.text,
        )
    except Exception:
        logger.exception("signals.report_note_mentions.slack_failed", report_id=str(message.report.id))
        return 0


def _capture_notified(report: SignalReport, *, recipient_count: int, sent: dict[str, int]) -> None:
    try:
        team = report.team
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(team.uuid),
                event="signals_report_note_mention_notified",
                properties={
                    "team_id": report.team_id,
                    "report_id": str(report.id),
                    "recipient_count": recipient_count,
                    **{f"{channel}_sent": count for channel, count in sent.items()},
                },
                groups=groups(team.organization, team),
            )
    except Exception:
        logger.exception("signals.report_note_mentions.capture_failed", report_id=str(report.id))


def deliver_note_mentions(
    *, team_id: int, artefact_id: str, author_id: int, mentions: NoteMentions
) -> list[MentionRecipient]:
    """Send one note's mentions on every channel. Returns the people it resolved as recipients."""
    artefact = (
        SignalReportArtefact.objects.filter(team_id=team_id, id=artefact_id, type__in=_NOTE_ARTEFACT_TYPES)
        .select_related("report", "report__team", "report__team__organization")
        .first()
    )
    if artefact is None:
        return []
    report = artefact.report
    team = report.team
    if report.status in _HIDDEN_STATUSES or report_is_hidden_from_inbox(team_id, str(report.id)):
        return []
    text = note_text(artefact.type, artefact.content)
    author = User.objects.filter(id=author_id).first()
    if text is None or author is None or not _mentions_enabled(team):
        return []

    role_names = organization_role_names(organization_id=team.organization_id, role_ids=mentions.role_ids)
    recipients = resolve_note_mention_recipients(
        team=team, author_id=author_id, mentions=mentions, role_names=role_names
    )
    if not recipients:
        return []

    # Names come from every token in the note, not only the new ones, so an edit renders whole.
    all_mentions = parse_note_mentions(text)
    # Only members of this organization get a name, so a token cannot reveal who an outside user id is.
    names_by_user_id = {
        user.id: display_name(user)
        for user in User.objects.filter(
            id__in=all_mentions.user_ids, organization_membership__organization_id=team.organization_id
        )
    }
    names_by_role_id = organization_role_names(organization_id=team.organization_id, role_ids=all_mentions.role_ids)
    message = _MentionMessage(
        report=report,
        author_name=display_name(author),
        text=excerpt(render_note_text(text, names_by_user_id=names_by_user_id, names_by_role_id=names_by_role_id)),
        digest=hashlib.sha256(text.encode()).hexdigest()[:16],
    )
    sent = {
        "in_app": _send_in_app(message, recipients, artefact_id),
        "email": _send_email(message, recipients, artefact_id),
        "push": _send_push(message, recipients, artefact_id),
        "slack": _send_slack(message, recipients),
    }
    _capture_notified(report, recipient_count=len(recipients), sent=sent)
    return recipients


# No automatic retry: email, push, and Slack have no shared idempotency key, so a retry could ping
# the same person twice.
@shared_task(ignore_result=True)
@with_team_scope()
def send_report_note_mention_notifications(
    team_id: int, artefact_id: str, author_id: int, user_ids: list[int], role_ids: list[str]
) -> None:
    deliver_note_mentions(
        team_id=team_id,
        artefact_id=artefact_id,
        author_id=author_id,
        mentions=NoteMentions(
            user_ids=frozenset(user_ids), role_ids=frozenset(uuid.UUID(role_id) for role_id in role_ids)
        ),
    )
