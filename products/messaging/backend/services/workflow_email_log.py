"""Emails that workflow and broadcast steps sent.

A send comes from the run's "Email sent" log line, which only the CDP email worker writes. Anyone with the project
token can capture a `$workflows_email_*` event, so those events only add a subject, the recipient's person, and
delivery and engagement to a send the logs already show. They exist only while the team records engagement events.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
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
from products.workflows.backend.facade.api import get_batch_job_workflow_ids, get_workflow_batch_job_ids
from products.workflows.backend.facade.contracts import WorkflowViewAccess

FOLLOW_UP_EVENTS = {
    "$workflows_email_delivered": EmailLogEventKind.DELIVERED,
    "$workflows_email_bounced": EmailLogEventKind.BOUNCED,
    "$workflows_email_opened": EmailLogEventKind.OPENED,
    "$workflows_email_link_clicked": EmailLogEventKind.CLICKED,
}
SENT_EVENT = "$workflows_email_sent"
# Opens and clicks after this aren't shown, the same week the recipient's activity covers.
FOLLOW_UP_WINDOW = timedelta(days=ACTIVITY_WINDOW_DAYS)
# How far back a lookup reaches when the run id carries no usable start time.
FALLBACK_LOOKBACK_DAYS = 90
_OLDEST_RUN = timedelta(days=365 * 5)
DEFAULT_LIST_DAYS = 7
_CLOCK_SKEW = timedelta(minutes=5)
# Most runs send soon after they start, so a send is looked for there before the rest of the run.
_FIRST_SEARCH = timedelta(days=7)
# The email worker logs `[Action:<step>] Email sent to <address> from <sender>` for each send.
_SENT_LINE = "[Action:%] Email sent to % from %"
_SENT_ACTION = r"^\[Action:([^\]]+)\] Email sent to "
_SENT_TO = r"^\[Action:[^\]]+\] Email sent to (.+?) from "


@frozen
class _SendKey:
    invocation_id: str
    action_id: str


@frozen
class _Window:
    start: datetime
    end: datetime


@frozen
class _LoggedSend:
    invocation_id: str
    action_id: str
    workflow_id: str
    recipient: str
    sent_at: datetime


@frozen
class _SendEvents:
    distinct_id: str
    subject: str
    follow_ups: dict[EmailLogEventKind, datetime]


def engagement_events_enabled(team: Team) -> bool:
    return team.workflows_config.capture_workflows_engagement_events


def _query(team: Team, user: User | None, query: str, placeholders: dict[str, ast.Expr], query_type: str) -> list:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    response = execute_hogql_query(
        query, team=team, user=user, placeholders=placeholders, query_type=query_type, workload=Workload.ONLINE
    )
    return response.results or []


def _logged_sends(
    team: Team,
    user: User | None,
    where: str,
    placeholders: dict[str, ast.Expr],
    order: str,
    limit: int,
    offset: int,
    query_type: str,
) -> list[_LoggedSend]:
    # A retried step can log its send twice, so each run and step is one send, at its first log line.
    rows = _query(
        team,
        user,
        f"""
        SELECT instance_id, extract(message, {{action_pattern}}) AS action_id, any(log_source_id),
            argMin(extract(message, {{to_pattern}}), timestamp), min(timestamp) AS sent_at
        FROM log_entries
        WHERE log_source = 'hog_flow' AND message LIKE {{sent_line}} AND {where}
        GROUP BY instance_id, action_id
        ORDER BY sent_at {order}, instance_id {order}, action_id {order}
        LIMIT {{limit}} OFFSET {{offset}}
        """,
        {
            **placeholders,
            "action_pattern": ast.Constant(value=_SENT_ACTION),
            "to_pattern": ast.Constant(value=_SENT_TO),
            "sent_line": ast.Constant(value=_SENT_LINE),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
        },
        query_type,
    )
    return [
        _LoggedSend(
            invocation_id=str(inv),
            action_id=str(action_id),
            workflow_id=str(workflow_id),
            recipient=str(recipient),
            sent_at=sent_at.astimezone(UTC),
        )
        for inv, action_id, workflow_id, recipient, sent_at in rows
    ]


def _send_events(
    team: Team, user: User | None, invocation_ids: list[str], start: datetime, end: datetime
) -> dict[_SendKey, _SendEvents]:
    """The person, subject and first follow-up of each kind that the events add to each logged send."""
    if not invocation_ids:
        return {}
    # Broadcast engagement names the batch job as its workflow, so events are matched by run, not workflow.
    rows = _query(
        team,
        user,
        """
        SELECT properties.$workflow_invocation_id, properties.$workflow_action_id, event, min(timestamp),
            argMin(distinct_id, timestamp), argMin(properties.$email_subject, timestamp)
        FROM events
        WHERE event IN {events}
          AND timestamp >= {start} AND timestamp < {end}
          AND properties.$workflow_invocation_id IN {invocation_ids}
        GROUP BY properties.$workflow_invocation_id, properties.$workflow_action_id, event
        LIMIT {limit}
        """,
        {
            "limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
            "events": ast.Constant(value=[SENT_EVENT, *FOLLOW_UP_EVENTS]),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "invocation_ids": ast.Constant(value=invocation_ids),
        },
        "workflow_email_events",
    )
    found: dict[_SendKey, _SendEvents] = {}
    for inv, act, event, first_at, distinct_id, subject in rows:
        key = _SendKey(invocation_id=str(inv), action_id=str(act or ""))
        current = found.get(key, _SendEvents(distinct_id="", subject="", follow_ups={}))
        if event == SENT_EVENT:
            found[key] = _SendEvents(
                distinct_id=distinct_id or "", subject=subject or "", follow_ups=current.follow_ups
            )
        else:
            found[key] = _SendEvents(
                distinct_id=current.distinct_id,
                subject=current.subject,
                follow_ups={**current.follow_ups, FOLLOW_UP_EVENTS[event]: first_at},
            )
    return found


def _status(follow_ups: set[EmailLogEventKind]) -> EmailDeliveryStatus:
    if EmailLogEventKind.BOUNCED in follow_ups:
        return EmailDeliveryStatus.BOUNCED
    if EmailLogEventKind.DELIVERED in follow_ups:
        return EmailDeliveryStatus.DELIVERED
    return EmailDeliveryStatus.SENT


def _send(logged: _LoggedSend, events: _SendEvents | None) -> WorkflowEmailSend:
    follow_ups = (
        {kind for kind, at in events.follow_ups.items() if at < logged.sent_at + FOLLOW_UP_WINDOW} if events else set()
    )
    return WorkflowEmailSend(
        invocation_id=logged.invocation_id,
        action_id=logged.action_id,
        workflow_id=logged.workflow_id,
        distinct_id=events.distinct_id if events else "",
        recipient=logged.recipient,
        subject=events.subject if events else "",
        sent_at=logged.sent_at,
        status=_status(follow_ups),
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
    # A broadcast's runs log under their batch job, not the workflow.
    sources = [workflow_id, *get_workflow_batch_job_ids(team_id=team.id, workflow_id=workflow_id)]
    logged = _logged_sends(
        team,
        user,
        "log_source_id IN {sources} AND timestamp >= {start} AND timestamp < {end}",
        {
            "sources": ast.Constant(value=sources),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
        "DESC",
        limit + 1,
        offset,
        "workflow_email_list",
    )
    shown = logged[:limit]
    events = (
        _send_events(
            team,
            user,
            sorted({send.invocation_id for send in shown}),
            min(send.sent_at for send in shown) - _CLOCK_SKEW,
            min(max(send.sent_at for send in shown) + FOLLOW_UP_WINDOW, now + _CLOCK_SKEW),
        )
        if shown
        else {}
    )
    return WorkflowEmailPage(
        sends=[
            _send(
                replace(send, workflow_id=workflow_id),
                events.get(_SendKey(invocation_id=send.invocation_id, action_id=send.action_id)),
            )
            for send in shown
        ],
        has_more=len(logged) > limit,
        engagement_events_enabled=engagement_events_enabled(team),
    )


def _run_window(invocation_id: UUID, now: datetime) -> _Window:
    # Run ids are UUIDT or UUIDv7, both of which start with the creation time in milliseconds.
    # A run can wait on delay steps for longer than a year, so the window runs until now.
    started_ms = invocation_id.int >> 80
    if not (now - _OLDEST_RUN).timestamp() * 1000 < started_ms < (now + _CLOCK_SKEW).timestamp() * 1000:
        return _Window(start=now - timedelta(days=FALLBACK_LOOKBACK_DAYS), end=now + _CLOCK_SKEW)
    started = datetime.fromtimestamp(started_ms / 1000, tz=UTC)
    return _Window(start=started - _CLOCK_SKEW, end=now + _CLOCK_SKEW)


def _find_send(
    team: Team, user: User | None, invocation_id: UUID, action_id: str, start: datetime, end: datetime
) -> _LoggedSend | None:
    sends = _logged_sends(
        team,
        user,
        "instance_id = {invocation_id} AND startsWith(message, {prefix}) AND timestamp >= {start} AND timestamp < {end}",
        {
            "invocation_id": ast.Constant(value=str(invocation_id)),
            "prefix": ast.Constant(value=f"[Action:{action_id}] "),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
        "ASC",
        1,
        0,
        "workflow_email_send",
    )
    return sends[0] if sends else None


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
    send = _find_send(team, user, invocation_id, action_id, window.start, min(window.start + _FIRST_SEARCH, window.end))
    if send is None and window.start + _FIRST_SEARCH < window.end:
        send = _find_send(team, user, invocation_id, action_id, window.start + _FIRST_SEARCH, window.end)
    if send is None:
        return None
    workflow_id = get_batch_job_workflow_ids(team_id=team.id, batch_job_ids=[send.workflow_id]).get(
        send.workflow_id, send.workflow_id
    )
    send = replace(send, workflow_id=workflow_id)
    # Fails closed: a send whose workflow is gone, or never resolved, has no workflow to check access against.
    if access is not None and send.workflow_id not in access.viewable_ids:
        return None
    follow_ups_end = min(send.sent_at + FOLLOW_UP_WINDOW, now + _CLOCK_SKEW)
    key = _SendKey(invocation_id=send.invocation_id, action_id=action_id)
    events = _send_events(team, user, [send.invocation_id], send.sent_at - _CLOCK_SKEW, follow_ups_end).get(key)
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
            "invocation_id": ast.Constant(value=send.invocation_id),
            "action_id": ast.Constant(value=action_id),
            "events": ast.Constant(value=list(FOLLOW_UP_EVENTS)),
            "start": ast.Constant(value=send.sent_at),
            "end": ast.Constant(value=follow_ups_end),
        },
        "workflow_email_timeline",
    )
    timeline = [
        TransactionalEmailLogEvent(kind=EmailLogEventKind.SENT, at=send.sent_at, reason=None),
        *(
            TransactionalEmailLogEvent(
                kind=FOLLOW_UP_EVENTS[event],
                at=timestamp.astimezone(UTC),
                reason=(bounce_type or None) if FOLLOW_UP_EVENTS[event] == EmailLogEventKind.BOUNCED else None,
            )
            for event, timestamp, bounce_type in follow_ups
        ),
    ]
    return WorkflowEmailDetail(send=_send(send, events), timeline=timeline)


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
