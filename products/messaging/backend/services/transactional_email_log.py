"""The transactional email log: every send of a project, read from the email_status_events table.

A send writes one row per status change. The queued row carries the recipient and the workflow, the sent row the
sending domain, and opens and clicks add rows of their own. The delivery status of a send is its highest-ranked
delivery row, so an open never hides a bounce.
"""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.messaging.backend.facade.contracts import (
    EmailDeliveryStatus,
    EmailLogEventKind,
    EmailStatsGroupBy,
    TransactionalEmailLogDetail,
    TransactionalEmailLogEntry,
    TransactionalEmailLogEvent,
    TransactionalEmailResults,
    TransactionalEmailStatsRow,
)
from products.messaging.backend.models.email_status_sql import (
    EMAIL_ENGAGEMENT_STATUSES,
    EMAIL_STATUS_EVENTS_TABLE,
    EMAIL_STATUS_RETENTION_DAYS,
)
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.facade.message_assets import (
    fetch_first_email_sends,
    fetch_message_assets_for_invocations,
)

RETENTION = timedelta(days=EMAIL_STATUS_RETENTION_DAYS)
# The send API stamps a message id with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
# A conversion window longer than this would reach past what the log keeps.
MAX_CONVERSION_WINDOW_DAYS = 30
# The results read at most this many recipients, newest sends first.
MAX_RESULTS_RECIPIENTS = 10_000
# A person's later events still count toward revenue, up to this many.
MAX_EVENTS_PER_PERSON = 1_000

_ENGAGEMENT = "(" + ", ".join(f"'{status}'" for status in EMAIL_ENGAGEMENT_STATUSES) + ")"

# One row per message. `argMaxIf` keeps the delivery status, and the `anyIf` columns read the one row that sets each.
_MESSAGE_COLUMNS = f"""
    message_id,
    min(created_at) AS queued_at,
    argMaxIf(status, version, status NOT IN {_ENGAGEMENT}) AS delivery_status,
    argMaxIf(status_at, version, status NOT IN {_ENGAGEMENT}) AS delivery_status_at,
    argMaxIf(reason, version, status NOT IN {_ENGAGEMENT}) AS delivery_reason,
    anyIf(recipient, recipient != '') AS message_recipient,
    anyIf(function_id, function_id != '') AS message_function_id,
    anyIf(sending_domain, sending_domain != '') AS message_sending_domain,
    countIf(status = 'opened') > 0 AS was_opened,
    countIf(status = 'clicked') > 0 AS was_clicked
""".strip()


@frozen
class _Period:
    start: datetime
    end: datetime


def _window(date_from: datetime | None, date_to: datetime | None) -> _Period:
    now = datetime.now(UTC)
    start = max(date_from or now - timedelta(days=7), now - RETENTION)
    # The send API stamps a message with its own clock, so "now" reaches a little ahead. A given end stays exact.
    end = min(date_to, now + _CLOCK_SKEW) if date_to else now + _CLOCK_SKEW
    return _Period(start=start, end=end)


def _execute(team_id: int, query: str, params: dict[str, Any]) -> list[tuple]:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    # The log is read by a person looking at the page, or by an agent answering one.
    return cast(list, sync_execute(query, {"team_id": team_id, **params}, workload=Workload.ONLINE, team_id=team_id))


def _templates_by_workflow(team_id: int, workflow_ids: Sequence[str]) -> dict[str, MessageTemplate]:
    ids = [UUID(workflow_id) for workflow_id in set(workflow_ids) if _is_uuid(workflow_id)]
    if not ids:
        return {}
    templates = MessageTemplate.objects.filter(team_id=team_id, transactional_hog_flow_id__in=ids)
    return {str(template.transactional_hog_flow_id): template for template in templates}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _build_entries(team_id: int, rows: list[tuple]) -> list[TransactionalEmailLogEntry]:
    templates = _templates_by_workflow(team_id, [row[6] for row in rows])
    entries = []
    for row in rows:
        (message_id, queued_at, status, status_at, reason, recipient, workflow_id, domain, opened, clicked) = row
        if status not in EmailDeliveryStatus.values:
            continue
        template = templates.get(workflow_id)
        if template and template.deleted:
            template = None
        entries.append(
            TransactionalEmailLogEntry(
                message_id=str(message_id),
                created_at=queued_at,
                status=EmailDeliveryStatus(status),
                status_at=status_at,
                reason=reason or None,
                recipient=recipient,
                workflow_id=workflow_id,
                template_id=str(template.id) if template else None,
                template_name=template.name if template else "",
                sending_domain=domain,
                opened=bool(opened),
                clicked=bool(clicked),
            )
        )
    return entries


def list_transactional_emails(
    team_id: int,
    *,
    search: str | None = None,
    status: EmailDeliveryStatus | None = None,
    workflow_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    workflow_ids: Collection[str] | None = None,
) -> tuple[list[TransactionalEmailLogEntry], bool]:
    """A page of the project's sends, newest first, and whether more follow. `workflow_ids` limits the sends to the
    workflows the reader may view, and None reads them all."""
    if workflow_ids is not None and not workflow_ids:
        return [], False
    period = _window(date_from, date_to)
    start, end = period.start, period.end
    where = ["team_id = %(team_id)s", "created_at >= %(start)s", "created_at < %(end)s"]
    having = ["delivery_status != ''"]
    params: dict[str, Any] = {"start": start, "end": end, "limit": limit + 1, "offset": offset}

    search = (search or "").strip()
    if search and _is_uuid(search):
        where.append("message_id = %(message_id)s")
        params["message_id"] = str(UUID(search))
    elif search:
        # Only the queued row names the recipient, so match on it and keep every row of the matching messages.
        where.append(
            f"message_id IN (SELECT message_id FROM {EMAIL_STATUS_EVENTS_TABLE} WHERE team_id = %(team_id)s"
            " AND created_at >= %(start)s AND created_at < %(end)s AND positionCaseInsensitive(recipient, %(search)s) > 0)"
        )
        params["search"] = search
    if status:
        having.append("delivery_status = %(status)s")
        params["status"] = status.value
    if workflow_id:
        having.append("message_function_id = %(workflow_id)s")
        params["workflow_id"] = workflow_id
    if workflow_ids is not None:
        having.append("message_function_id IN %(workflow_ids)s")
        params["workflow_ids"] = list(workflow_ids)

    rows = _execute(
        team_id,
        f"""
        SELECT {_MESSAGE_COLUMNS}
        FROM {EMAIL_STATUS_EVENTS_TABLE}
        WHERE {" AND ".join(where)}
        GROUP BY message_id
        HAVING {" AND ".join(having)}
        ORDER BY queued_at DESC, toString(message_id) DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    )
    has_more = len(rows) > limit
    return _build_entries(team_id, rows[:limit]), has_more


def get_transactional_email(
    team_id: int, message_id: UUID, *, workflow_ids: Collection[str] | None = None
) -> TransactionalEmailLogDetail | None:
    """One send with every status it went through, or None when the project has no send with this id, or the reader
    may not view its workflow."""
    # A message id starts with the time it was queued, so the partition scan stays to that day.
    queued_ms = int.from_bytes(message_id.bytes[:6], "big")
    now = datetime.now(UTC)
    if not (now - RETENTION).timestamp() * 1000 <= queued_ms <= (now + _CLOCK_SKEW).timestamp() * 1000:
        return None
    queued = datetime.fromtimestamp(queued_ms / 1000, tz=UTC)
    params = {"message_id": str(message_id), "start": queued - _CLOCK_SKEW, "end": queued + _CLOCK_SKEW}
    where = "team_id = %(team_id)s AND message_id = %(message_id)s AND created_at >= %(start)s AND created_at < %(end)s"

    rows = _execute(
        team_id,
        f"SELECT {_MESSAGE_COLUMNS} FROM {EMAIL_STATUS_EVENTS_TABLE} WHERE {where} GROUP BY message_id",
        params,
    )
    entries = _build_entries(team_id, rows)
    if not entries or (workflow_ids is not None and entries[0].workflow_id not in workflow_ids):
        return None
    entry = entries[0]

    events = _execute(
        team_id,
        f"SELECT status, status_at, reason FROM {EMAIL_STATUS_EVENTS_TABLE} WHERE {where} ORDER BY status_at, version",
        params,
    )
    timeline: list[TransactionalEmailLogEvent] = []
    for kind, at, reason in events:
        if kind not in EmailLogEventKind.values:
            continue
        # A failed email step also fails its run, and the run writes a second, vaguer failure. Show the first only.
        if kind == EmailLogEventKind.FAILED and timeline and timeline[-1].kind == EmailLogEventKind.FAILED:
            continue
        timeline.append(TransactionalEmailLogEvent(kind=EmailLogEventKind(kind), at=at, reason=reason or None))

    assets = fetch_message_assets_for_invocations(team_id, [entry.message_id], after=queued - _CLOCK_SKEW)
    asset = assets[0] if assets else None
    template = _templates_by_workflow(team_id, [entry.workflow_id]).get(entry.workflow_id)
    return TransactionalEmailLogDetail(
        entry=entry,
        timeline=timeline,
        subject=asset.subject if asset else "",
        distinct_id=asset.distinct_id if asset else "",
        action_id=asset.action_id if asset else "",
        sensitive=bool(template and template.sensitive),
    )


def transactional_email_stats(
    team_id: int,
    group_by: EmailStatsGroupBy,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    workflow_ids: Collection[str] | None = None,
) -> list[TransactionalEmailStatsRow]:
    """How many sends reached each status, per template or per sending domain, busiest first."""
    if workflow_ids is not None and not workflow_ids:
        return []
    period = _window(date_from, date_to)
    start, end = period.start, period.end
    params: dict[str, Any] = {"start": start, "end": end}
    access = ""
    if workflow_ids is not None:
        access = "AND message_function_id IN %(workflow_ids)s"
        params["workflow_ids"] = list(workflow_ids)
    group_column = "message_function_id" if group_by == EmailStatsGroupBy.TEMPLATE else "message_sending_domain"
    rows = _execute(
        team_id,
        f"""
        SELECT
            {group_column} AS group_key,
            countIf(delivery_status IN ('sent', 'delivered', 'bounced', 'complained')) AS sent,
            countIf(delivery_status IN ('delivered', 'complained')) AS delivered,
            countIf(delivery_status = 'bounced') AS bounced,
            countIf(delivery_status = 'complained') AS complained,
            countIf(was_opened) AS opened,
            countIf(was_clicked) AS clicked,
            countIf(delivery_status = 'failed') AS failed
        FROM (
            SELECT {_MESSAGE_COLUMNS}
            FROM {EMAIL_STATUS_EVENTS_TABLE}
            WHERE team_id = %(team_id)s AND created_at >= %(start)s AND created_at < %(end)s
            GROUP BY message_id
        )
        WHERE delivery_status != '' AND group_key != '' {access}
        GROUP BY group_key
        ORDER BY sent + failed DESC, group_key
        LIMIT 200
        """,
        params,
    )
    templates = (
        _templates_by_workflow(team_id, [row[0] for row in rows]) if group_by == EmailStatsGroupBy.TEMPLATE else {}
    )
    stats = []
    for key, sent, delivered, bounced, complained, opened, clicked, failed in rows:
        template = templates.get(key)
        if group_by == EmailStatsGroupBy.TEMPLATE:
            key = str(template.id) if template else key
            label = template.name if template and not template.deleted else ""
        else:
            label = key
        stats.append(
            TransactionalEmailStatsRow(
                key=key,
                label=label,
                sent=sent,
                delivered=delivered,
                bounced=bounced,
                complained=complained,
                opened=opened,
                clicked=clicked,
                failed=failed,
            )
        )
    return stats


def transactional_email_results(
    team: Team,
    user: User | None,
    workflow_id: str,
    event: str,
    *,
    window_days: int = 7,
    revenue_property: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> TransactionalEmailResults:
    """Of the people a transactional email was sent to, how many did `event` within `window_days` of their first send,
    and the revenue those events carried."""
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    period = _window(date_from, date_to)
    start, end = period.start, period.end
    window = timedelta(days=min(max(window_days, 1), MAX_CONVERSION_WINDOW_DAYS))
    sends = fetch_first_email_sends(team.id, workflow_id, start, end, limit=MAX_RESULTS_RECIPIENTS)
    if not sends:
        return TransactionalEmailResults(recipients=0, converted=0, revenue=0.0, median_hours_to_convert=None)

    # The same person can be reached under several distinct ids, so the send and the conversion meet on the person.
    person_by_distinct_id = _persons_for_distinct_ids(team, user, list(sends))
    first_send: dict[str, datetime] = {}
    for distinct_id, sent_at in sends.items():
        person = person_by_distinct_id.get(distinct_id, f"distinct:{distinct_id}")
        first_send[person] = min(first_send.get(person, sent_at), sent_at)

    conversions = _conversion_events(team, user, event, revenue_property, list(sends), start, end + window)
    converted_at: dict[str, datetime] = {}
    revenue = 0.0
    for person, events in conversions.items():
        first_sent_at = first_send.get(person)
        if first_sent_at is None:
            continue
        for timestamp, value in events:
            if not (first_sent_at <= timestamp <= first_sent_at + window):
                continue
            converted_at[person] = min(converted_at.get(person, timestamp), timestamp)
            revenue += value or 0.0

    hours = [(converted_at[person] - first_send[person]).total_seconds() / 3600 for person in converted_at]
    return TransactionalEmailResults(
        recipients=len(first_send),
        converted=len(converted_at),
        revenue=round(revenue, 2),
        median_hours_to_convert=round(median(hours), 2) if hours else None,
    )


def _persons_for_distinct_ids(team: Team, user: User | None, distinct_ids: list[str]) -> dict[str, str]:
    response = execute_hogql_query(
        """
        SELECT distinct_id, toString(person_id) FROM person_distinct_ids
        WHERE distinct_id IN {distinct_ids}
        LIMIT {limit}
        """,
        team=team,
        user=user,
        placeholders={"distinct_ids": ast.Constant(value=distinct_ids), "limit": ast.Constant(value=len(distinct_ids))},
        query_type="transactional_email_results_persons",
        workload=Workload.ONLINE,
    )
    return dict(response.results or [])


def _conversion_events(
    team: Team,
    user: User | None,
    event: str,
    revenue_property: str | None,
    distinct_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[tuple[datetime, float | None]]]:
    """The time and revenue of each person's conversion events, grouped per person so the row limit counts people.

    A recipient with no person profile is keyed by distinct ID, the same way `transactional_email_results` keys their send.
    """
    revenue: ast.Expr = (
        ast.Call(
            name="toFloatOrNull",
            args=[ast.Call(name="toString", args=[ast.Field(chain=["properties", revenue_property])])],
        )
        if revenue_property
        else ast.Constant(value=None)
    )
    response = execute_hogql_query(
        """
        SELECT
            if(person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id IN {distinct_ids}),
               toString(person_id), concat('distinct:', distinct_id)) AS recipient,
            groupArray({per_person})(tuple(timestamp, {revenue}))
        FROM events
        WHERE event = {event}
          AND timestamp >= {start} AND timestamp < {end}
          AND (distinct_id IN {distinct_ids}
               OR person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id IN {distinct_ids}))
        GROUP BY recipient
        LIMIT {limit}
        """,
        team=team,
        user=user,
        placeholders={
            "revenue": revenue,
            "event": ast.Constant(value=event),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "distinct_ids": ast.Constant(value=distinct_ids),
            "per_person": ast.Constant(value=MAX_EVENTS_PER_PERSON),
            "limit": ast.Constant(value=len(distinct_ids)),
        },
        query_type="transactional_email_results_conversions",
        workload=Workload.ONLINE,
    )
    return {
        person_id: [(timestamp.astimezone(UTC), value) for timestamp, value in events]
        for person_id, events in response.results or []
    }
