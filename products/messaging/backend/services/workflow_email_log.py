"""Emails that workflow and broadcast steps sent, read from the `$workflows_email_*` events.

Only transactional sends reach the email_status tables, so the other sends are found through the engagement events
the CDP email worker captures. Those exist only while the team records engagement events.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.messaging.backend.facade.contracts import (
    EmailDeliveryStatus,
    EmailLogEventKind,
    TransactionalEmailActivity,
    TransactionalEmailLogEvent,
    WorkflowEmailDetail,
    WorkflowEmailPage,
    WorkflowEmailSend,
)
from products.messaging.backend.services.transactional_email_activity import ACTIVITY_WINDOW_DAYS, get_email_activity
from products.workflows.backend.facade.contracts import WorkflowViewAccess

SEND_EVENTS = {
    "$workflows_email_sent": EmailLogEventKind.SENT,
    "$workflows_email_failed": EmailLogEventKind.FAILED,
}
FOLLOW_UP_EVENTS = {
    "$workflows_email_delivered": EmailLogEventKind.DELIVERED,
    "$workflows_email_bounced": EmailLogEventKind.BOUNCED,
    "$workflows_email_opened": EmailLogEventKind.OPENED,
    "$workflows_email_link_clicked": EmailLogEventKind.CLICKED,
}
EVENT_KINDS = {**SEND_EVENTS, **FOLLOW_UP_EVENTS}
# Opens and clicks after this aren't shown, the same week the recipient's activity covers.
FOLLOW_UP_WINDOW = timedelta(days=ACTIVITY_WINDOW_DAYS)
# How long after a run starts it may still send an email, so how far a lookup by run reaches.
MAX_RUN_DAYS = 90
DEFAULT_LIST_DAYS = 7
_CLOCK_SKEW = timedelta(minutes=5)


@frozen
class _SendKey:
    invocation_id: str
    action_id: str


@frozen
class _Window:
    start: datetime
    end: datetime


def engagement_events_enabled(team: Team) -> bool:
    return team.workflows_config.capture_workflows_engagement_events


def _query(team: Team, user: User | None, query: str, placeholders: dict[str, ast.Expr], query_type: str) -> list:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    response = execute_hogql_query(
        query, team=team, user=user, placeholders=placeholders, query_type=query_type, workload=Workload.ONLINE
    )
    return response.results or []


def _follow_ups(
    team: Team, user: User | None, invocation_ids: list[str], start: datetime, end: datetime
) -> dict[_SendKey, set[EmailLogEventKind]]:
    if not invocation_ids:
        return {}
    # Broadcast engagement names the batch job as its workflow, so follow-ups are matched by run, not workflow.
    rows = _query(
        team,
        user,
        """
        SELECT properties.$workflow_invocation_id, properties.$workflow_action_id, groupUniqArray(event)
        FROM events
        WHERE event IN {events}
          AND timestamp >= {start} AND timestamp < {end}
          AND properties.$workflow_invocation_id IN {invocation_ids}
        GROUP BY properties.$workflow_invocation_id, properties.$workflow_action_id
        """,
        {
            "events": ast.Constant(value=list(FOLLOW_UP_EVENTS)),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "invocation_ids": ast.Constant(value=invocation_ids),
        },
        "workflow_email_follow_ups",
    )
    return {
        _SendKey(invocation_id=str(inv), action_id=str(act or "")): {FOLLOW_UP_EVENTS[event] for event in events}
        for inv, act, events in rows
    }


def _status(send_kind: EmailLogEventKind, follow_ups: set[EmailLogEventKind]) -> EmailDeliveryStatus:
    if send_kind == EmailLogEventKind.FAILED:
        return EmailDeliveryStatus.FAILED
    if EmailLogEventKind.BOUNCED in follow_ups:
        return EmailDeliveryStatus.BOUNCED
    if EmailLogEventKind.DELIVERED in follow_ups:
        return EmailDeliveryStatus.DELIVERED
    return EmailDeliveryStatus.SENT


_SEND_COLUMNS = """
    properties.$workflow_invocation_id, properties.$workflow_action_id, properties.$workflow_id, distinct_id,
    properties.$email_to, properties.$email_subject, timestamp, event
"""


def _send(row: tuple, follow_ups: set[EmailLogEventKind]) -> WorkflowEmailSend:
    invocation_id, action_id, workflow_id, distinct_id, recipient, subject, timestamp, event = row
    return WorkflowEmailSend(
        invocation_id=str(invocation_id),
        action_id=str(action_id or ""),
        workflow_id=str(workflow_id or ""),
        distinct_id=distinct_id or "",
        recipient=recipient or "",
        subject=subject or "",
        sent_at=timestamp.astimezone(UTC),
        status=_status(SEND_EVENTS[event], follow_ups),
        opened=EmailLogEventKind.OPENED in follow_ups or EmailLogEventKind.CLICKED in follow_ups,
        clicked=EmailLogEventKind.CLICKED in follow_ups,
    )


def list_workflow_emails(
    team: Team,
    user: User | None,
    workflow_id: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    access: WorkflowViewAccess | None = None,
) -> WorkflowEmailPage | None:
    """A page of one workflow's sends, newest first, or None when the reader can't see the workflow."""
    if access is not None and workflow_id not in access.viewable_ids:
        return None
    now = datetime.now(UTC)
    start = date_from or now - timedelta(days=DEFAULT_LIST_DAYS)
    end = min(date_to, now + _CLOCK_SKEW) if date_to else now + _CLOCK_SKEW
    rows = _query(
        team,
        user,
        f"""
        SELECT {_SEND_COLUMNS}
        FROM events
        WHERE event IN {{events}}
          AND timestamp >= {{start}} AND timestamp < {{end}}
          AND properties.$workflow_id = {{workflow_id}}
        ORDER BY timestamp DESC
        LIMIT {{limit}} OFFSET {{offset}}
        """,
        {
            "events": ast.Constant(value=list(SEND_EVENTS)),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "workflow_id": ast.Constant(value=workflow_id),
            "limit": ast.Constant(value=limit + 1),
            "offset": ast.Constant(value=offset),
        },
        "workflow_email_list",
    )
    shown = rows[:limit]
    follow_ups = (
        _follow_ups(
            team,
            user,
            sorted({str(row[0]) for row in shown}),
            min(row[6] for row in shown),
            min(max(row[6] for row in shown) + FOLLOW_UP_WINDOW, now + _CLOCK_SKEW),
        )
        if shown
        else {}
    )
    return WorkflowEmailPage(
        sends=[
            _send(row, follow_ups.get(_SendKey(invocation_id=str(row[0]), action_id=str(row[1] or "")), set()))
            for row in shown
        ],
        has_more=len(rows) > limit,
        engagement_events_enabled=engagement_events_enabled(team),
    )


def _run_window(invocation_id: UUID, now: datetime) -> _Window:
    # Run ids are UUIDT or UUIDv7, both of which start with the creation time in milliseconds.
    started = datetime.fromtimestamp((invocation_id.int >> 80) / 1000, tz=UTC)
    if not now - timedelta(days=365 * 5) < started < now + _CLOCK_SKEW:
        started = now - timedelta(days=MAX_RUN_DAYS)
    return _Window(start=started - _CLOCK_SKEW, end=min(started + timedelta(days=MAX_RUN_DAYS), now + _CLOCK_SKEW))


def get_workflow_email(
    team: Team,
    user: User | None,
    invocation_id: UUID,
    action_id: str,
    *,
    access: WorkflowViewAccess | None = None,
) -> WorkflowEmailDetail | None:
    """One send with its timeline, or None when the project has no such send or the reader can't see its workflow."""
    now = datetime.now(UTC)
    window = _run_window(invocation_id, now)
    placeholders: dict[str, ast.Expr] = {
        "invocation_id": ast.Constant(value=str(invocation_id)),
        "action_id": ast.Constant(value=action_id),
    }
    sends = _query(
        team,
        user,
        f"""
        SELECT {_SEND_COLUMNS}
        FROM events
        WHERE event IN {{events}}
          AND timestamp >= {{start}} AND timestamp < {{end}}
          AND properties.$workflow_invocation_id = {{invocation_id}}
          AND properties.$workflow_action_id = {{action_id}}
        ORDER BY timestamp ASC
        LIMIT 1
        """,
        {
            **placeholders,
            "events": ast.Constant(value=list(SEND_EVENTS)),
            "start": ast.Constant(value=window.start),
            "end": ast.Constant(value=window.end),
        },
        "workflow_email_send",
    )
    if not sends:
        return None
    row = sends[0]
    if access is not None and not access.allows(str(row[2] or "")):
        return None
    sent_at = row[6]
    follow_ups = _query(
        team,
        user,
        """
        SELECT event, timestamp, properties.$bounce_type
        FROM events
        WHERE event IN {events}
          AND timestamp >= {start} AND timestamp < {end}
          AND properties.$workflow_invocation_id = {invocation_id}
          AND properties.$workflow_action_id = {action_id}
        ORDER BY timestamp ASC
        LIMIT 100
        """,
        {
            **placeholders,
            "events": ast.Constant(value=list(FOLLOW_UP_EVENTS)),
            "start": ast.Constant(value=sent_at),
            "end": ast.Constant(value=min(sent_at + FOLLOW_UP_WINDOW, now + _CLOCK_SKEW)),
        },
        "workflow_email_timeline",
    )
    timeline = [
        TransactionalEmailLogEvent(kind=SEND_EVENTS[row[7]], at=sent_at.astimezone(UTC), reason=None),
        *(
            TransactionalEmailLogEvent(
                kind=FOLLOW_UP_EVENTS[event],
                at=timestamp.astimezone(UTC),
                reason=(bounce_type or None) if FOLLOW_UP_EVENTS[event] == EmailLogEventKind.BOUNCED else None,
            )
            for event, timestamp, bounce_type in follow_ups
        ),
    ]
    return WorkflowEmailDetail(send=_send(row, {event.kind for event in timeline[1:]}), timeline=timeline)


def get_workflow_email_activity(
    team: Team,
    user: User | None,
    invocation_id: UUID,
    action_id: str,
    *,
    access: WorkflowViewAccess | None = None,
) -> TransactionalEmailActivity | None:
    """The recipient's events in the week before and after one send, or None when the reader can't see the send."""
    detail = get_workflow_email(team, user, invocation_id, action_id, access=access)
    if detail is None:
        return None
    return get_email_activity(team, user, detail.send.distinct_id, detail.send.sent_at)
