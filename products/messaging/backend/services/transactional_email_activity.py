"""What the recipient of one transactional email did in the product around the send."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team, User

from products.messaging.backend.facade.contracts import (
    EmailLogEventKind,
    TransactionalEmailActivity,
    TransactionalEmailActivityEvent,
    TransactionalEmailActivitySession,
)
from products.messaging.backend.services.transactional_email_log import get_transactional_email
from products.workflows.backend.facade.contracts import WorkflowViewAccess

ACTIVITY_WINDOW_DAYS = 7
ACTIVITY_BEFORE_LIMIT = 50
ACTIVITY_AFTER_LIMIT = 100

# Events that describe the SDK rather than something the person did.
HIDDEN_EVENTS = (
    "$feature_flag_called",
    "$identify",
    "$set",
    "$groupidentify",
    "$create_alias",
    "$pageleave",
    "$web_vitals",
    "$opt_in",
    "$autocapture_disabled",
    "$dead_click",
    "$exception",
    "$feature_view",
    "$feature_interaction",
    "$snapshot",
    # The send's own timeline already covers these.
    "$workflows_email_sent",
    "$workflows_email_failed",
    "$workflows_email_delivered",
    "$workflows_email_opened",
    "$workflows_email_link_clicked",
    "$workflows_email_bounced",
    "$workflows_email_blocked",
)


def get_transactional_email_activity(
    team: Team,
    user: User | None,
    message_id: UUID,
    *,
    access: WorkflowViewAccess | None = None,
) -> TransactionalEmailActivity | None:
    """The recipient's events in the week before and after one send, or None when the reader can't see the send."""
    detail = get_transactional_email(team.id, message_id, access=access)
    if detail is None:
        return None
    sent_at = next(
        (event.at for event in detail.timeline if event.kind == EmailLogEventKind.SENT), detail.entry.created_at
    )
    if not detail.distinct_id:
        return TransactionalEmailActivity(
            distinct_id="",
            sent_at=sent_at,
            before=[],
            after=[],
            has_more_before=False,
            has_more_after=False,
            sessions=[],
        )

    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    window = timedelta(days=ACTIVITY_WINDOW_DAYS)
    before = _events(
        team, user, detail.distinct_id, sent_at - window, sent_at, newest_first=True, limit=ACTIVITY_BEFORE_LIMIT
    )
    after = _events(
        team, user, detail.distinct_id, sent_at, sent_at + window, newest_first=False, limit=ACTIVITY_AFTER_LIMIT
    )
    shown_before = list(reversed(before[:ACTIVITY_BEFORE_LIMIT]))
    shown_after = after[:ACTIVITY_AFTER_LIMIT]
    return TransactionalEmailActivity(
        distinct_id=detail.distinct_id,
        sent_at=sent_at,
        before=shown_before,
        after=shown_after,
        has_more_before=len(before) > ACTIVITY_BEFORE_LIMIT,
        has_more_after=len(after) > ACTIVITY_AFTER_LIMIT,
        sessions=_sessions(shown_before, shown_after),
    )


def _events(
    team: Team,
    user: User | None,
    distinct_id: str,
    start: datetime,
    end: datetime,
    *,
    newest_first: bool,
    limit: int,
) -> list[TransactionalEmailActivityEvent]:
    # One row past the limit tells the caller there is more.
    response = execute_hogql_query(
        f"""
        SELECT uuid, event, timestamp, properties.$current_url, properties.$session_id
        FROM events
        WHERE person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id = {{distinct_id}})
          AND timestamp >= {{start}} AND timestamp < {{end}}
          AND event NOT IN {{hidden}}
        ORDER BY timestamp {"DESC" if newest_first else "ASC"}
        LIMIT {{limit}}
        """,
        team=team,
        user=user,
        placeholders={
            "distinct_id": ast.Constant(value=distinct_id),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "hidden": ast.Constant(value=list(HIDDEN_EVENTS)),
            "limit": ast.Constant(value=limit + 1),
        },
        query_type="transactional_email_activity",
        workload=Workload.ONLINE,
    )
    return [
        TransactionalEmailActivityEvent(
            uuid=str(uuid),
            event=event,
            timestamp=timestamp.astimezone(UTC),
            current_url=current_url or None,
            session_id=session_id or None,
        )
        for uuid, event, timestamp, current_url, session_id in response.results or []
    ]


def _sessions(
    before: list[TransactionalEmailActivityEvent], after: list[TransactionalEmailActivityEvent]
) -> list[TransactionalEmailActivitySession]:
    started_before = {event.session_id for event in before if event.session_id}
    events_by_session: dict[str, list[TransactionalEmailActivityEvent]] = {}
    for event in [*before, *after]:
        if event.session_id:
            events_by_session.setdefault(event.session_id, []).append(event)
    return [
        TransactionalEmailActivitySession(
            session_id=session_id,
            first_event_at=events[0].timestamp,
            last_event_at=events[-1].timestamp,
            event_count=len(events),
            started_after_send=session_id not in started_before,
        )
        for session_id, events in events_by_session.items()
    ]
