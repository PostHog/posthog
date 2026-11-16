"""The transactional email log: every send of a project, read from the email_status_events table.

A send writes one row per status change. The queued row carries the recipient and the workflow, the sent row the
sending domain, and opens and clicks add rows of their own. The delivery status of a send is its highest-ranked
delivery row, so an open never hides a bounce.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

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
    EmailStatsInterval,
    TransactionalEmailLogDetail,
    TransactionalEmailLogEntry,
    TransactionalEmailLogEvent,
    TransactionalEmailResults,
    TransactionalEmailStatsBucket,
    TransactionalEmailStatsCounts,
    TransactionalEmailStatsOverTime,
    TransactionalEmailStatsRow,
)
from products.messaging.backend.models.email_status_sql import (
    EMAIL_ENGAGEMENT_STATUSES,
    EMAIL_STATUS_EVENTS_TABLE,
    EMAIL_STATUS_RETENTION_DAYS,
)
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.services.transactional_email_status import message_created_at
from products.workflows.backend.facade.contracts import WorkflowViewAccess
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

# A message's rows sit together in the table's sort key, so grouping can finish each message as it reads on.
_GROUP_AS_READ: dict[str, int] = {"optimize_aggregation_in_order": 1}
# Reading newest first is slow when few rows match, so a search reads in any order and sorts what it finds.
_SEARCH: dict[str, int] = {"optimize_read_in_order": 0}

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


def _message_created_at(team_id: int, message_id: UUID) -> datetime | None:
    # The log reads email_status_events, which its own consumer fills, so a send the email_status consumer has not
    # reached yet is still found.
    return message_created_at(team_id, message_id, Workload.ONLINE, lag_fallback_table=EMAIL_STATUS_EVENTS_TABLE)


def _execute(team_id: int, query: str, params: dict[str, Any], settings: dict[str, int] | None = None) -> list[tuple]:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    # The log is read by a person looking at the page, or by an agent answering one.
    return cast(
        list,
        sync_execute(
            query, {"team_id": team_id, **params}, settings=settings, workload=Workload.ONLINE, team_id=team_id
        ),
    )


def _templates_by_workflow(team_id: int, workflow_ids: Sequence[str]) -> dict[str, MessageTemplate]:
    ids = [UUID(workflow_id) for workflow_id in set(workflow_ids) if _is_uuid(workflow_id)]
    if not ids:
        return {}
    templates = MessageTemplate.objects.filter(team_id=team_id, transactional_hog_flow_id__in=ids)
    return {str(template.transactional_hog_flow_id): template for template in templates}


def _access_condition(column: str, access: WorkflowViewAccess, params: dict[str, Any]) -> str:
    if not access.can_view_deleted:
        params["viewable_workflows"] = list(access.viewable_ids)
        return f"{column} IN %(viewable_workflows)s"
    if not access.blocked_ids:
        return f"{column} != ''"
    params["blocked_workflows"] = list(access.blocked_ids)
    return f"{column} != '' AND {column} NOT IN %(blocked_workflows)s"


def _sees_no_sends(access: WorkflowViewAccess | None) -> bool:
    return access is not None and not access.can_view_deleted and not access.viewable_ids


def _code_send_keys(team_id: int, workflow_ids: Sequence[str]) -> dict[str, str]:
    """The `template_key` of each workflow behind a send from code, which has no template to name it."""
    ids = [UUID(workflow_id) for workflow_id in set(workflow_ids) if _is_uuid(workflow_id)]
    if not ids:
        return {}
    keys = TransactionalEmailKey.objects.for_team(team_id, canonical=True).filter(hog_flow_id__in=ids)
    return {str(hog_flow_id): key for hog_flow_id, key in keys.values_list("hog_flow_id", "key")}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _build_entries(team_id: int, rows: list[tuple]) -> list[TransactionalEmailLogEntry]:
    templates = _templates_by_workflow(team_id, [row[6] for row in rows])
    code_send_keys = _code_send_keys(team_id, [row[6] for row in rows])
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
                template_name=template.name if template else code_send_keys.get(workflow_id, ""),
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
    access: WorkflowViewAccess | None = None,
) -> tuple[list[TransactionalEmailLogEntry], bool]:
    """A page of the project's sends, newest first, and whether more follow. `access` limits the sends to the workflows
    the reader may view, and None reads them all."""
    if _sees_no_sends(access):
        return [], False
    period = _window(date_from, date_to)
    start, end = period.start, period.end
    period_filter = "team_id = %(team_id)s AND created_at >= %(start)s AND created_at < %(end)s"
    having = ["delivery_status != ''"]
    params: dict[str, Any] = {"start": start, "end": end, "limit": limit + 1, "offset": offset}
    # Only the queued row names the recipient and the workflow, so these filters pick messages from queued rows.
    queued_filters: list[str] = []
    settings: dict[str, int] = {}

    search = (search or "").strip()
    message_id = UUID(search) if search and _is_uuid(search) else None
    if message_id:
        sent_around = _message_created_at(team_id, message_id)
        if sent_around is None:
            return [], False
        params["message_id"] = str(message_id)
        params["start"] = max(start, sent_around - _CLOCK_SKEW)
        params["end"] = min(end, sent_around + _CLOCK_SKEW)
    elif search:
        queued_filters.append("positionCaseInsensitive(recipient, %(search)s) > 0")
        params["search"] = search
        settings.update(_SEARCH)
    if status:
        having.append("delivery_status = %(status)s")
        params["status"] = status.value
    if workflow_id:
        queued_filters.append("function_id = %(workflow_id)s")
        having.append("message_function_id = %(workflow_id)s")
        params["workflow_id"] = workflow_id
    if access is not None:
        queued_filters.append(_access_condition("function_id", access, params))
        having.append(_access_condition("message_function_id", access, params))

    queued = " AND ".join([period_filter, "status = 'queued'", *queued_filters])
    candidates = f"SELECT created_at, message_id FROM {EMAIL_STATUS_EVENTS_TABLE} WHERE {queued}"
    if message_id:
        scope = "AND message_id = %(message_id)s"
    elif status:
        # A delivery status comes from all of a message's rows, so this reads every message in the period.
        settings.update(_GROUP_AS_READ)
        scope = f"AND (created_at, message_id) IN ({candidates})" if search or workflow_id else ""
    else:
        # The page comes from queued rows alone, so a long period doesn't group every message to show 50 of them.
        # Kafka can deliver a queued row twice, so this takes extra rows and the grouping below drops the repeats.
        params["candidates"] = (limit + 1 + offset) * 2
        scope = (
            f"AND (created_at, message_id) IN ({candidates} ORDER BY created_at DESC, message_id DESC"
            " LIMIT %(candidates)s)"
        )

    rows = _execute(
        team_id,
        f"""
        SELECT {_MESSAGE_COLUMNS}
        FROM {EMAIL_STATUS_EVENTS_TABLE}
        WHERE {period_filter} {scope}
        GROUP BY created_at, message_id
        HAVING {" AND ".join(having)}
        ORDER BY queued_at DESC, message_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
        settings or None,
    )
    has_more = len(rows) > limit
    return _build_entries(team_id, rows[:limit]), has_more


def get_transactional_email(
    team_id: int, message_id: UUID, *, access: WorkflowViewAccess | None = None
) -> TransactionalEmailLogDetail | None:
    """One send with every status it went through, or None when the project has no send with this id, or the reader
    may not view its workflow."""
    queued = _message_created_at(team_id, message_id)
    if queued is None:
        return None
    params = {"message_id": str(message_id), "start": queued - _CLOCK_SKEW, "end": queued + _CLOCK_SKEW}
    where = "team_id = %(team_id)s AND message_id = %(message_id)s AND created_at >= %(start)s AND created_at < %(end)s"

    rows = _execute(
        team_id,
        f"SELECT {_MESSAGE_COLUMNS} FROM {EMAIL_STATUS_EVENTS_TABLE} WHERE {where} GROUP BY message_id",
        params,
    )
    entries = _build_entries(team_id, rows)
    if not entries or (access is not None and not access.allows(entries[0].workflow_id)):
        return None
    entry = entries[0]

    events = _execute(
        team_id,
        # Kafka can deliver a status twice, and this table keeps every row. A repeat has the same status and time.
        f"""
        SELECT status, status_at, reason FROM {EMAIL_STATUS_EVENTS_TABLE}
        WHERE {where}
        GROUP BY status, status_at, reason
        ORDER BY status_at, max(version)
        """,
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
        # The stored copy opens through its workflow, so a deleted workflow's copy can't be shown.
        action_id=asset.action_id if asset and (access is None or entry.workflow_id in access.viewable_ids) else "",
        sensitive=bool(template and template.sensitive),
    )


def transactional_email_stats(
    team_id: int,
    group_by: EmailStatsGroupBy,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    access: WorkflowViewAccess | None = None,
) -> list[TransactionalEmailStatsRow]:
    """How many sends reached each status, per template or per sending domain, busiest first."""
    if _sees_no_sends(access):
        return []
    period = _window(date_from, date_to)
    start, end = period.start, period.end
    params: dict[str, Any] = {"start": start, "end": end}
    access_filter = f"AND {_access_condition('message_function_id', access, params)}" if access is not None else ""
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
            GROUP BY created_at, message_id
        )
        WHERE delivery_status != '' AND group_key != '' {access_filter}
        GROUP BY group_key
        ORDER BY sent + failed DESC, group_key
        LIMIT 200
        """,
        params,
        _GROUP_AS_READ,
    )
    templates = (
        _templates_by_workflow(team_id, [row[0] for row in rows]) if group_by == EmailStatsGroupBy.TEMPLATE else {}
    )
    code_send_keys = (
        _code_send_keys(team_id, [row[0] for row in rows]) if group_by == EmailStatsGroupBy.TEMPLATE else {}
    )
    stats = []
    for key, sent, delivered, bounced, complained, opened, clicked, failed in rows:
        template = templates.get(key)
        if group_by == EmailStatsGroupBy.TEMPLATE:
            label = template.name if template and not template.deleted else code_send_keys.get(key, "")
            key = str(template.id) if template else key
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


_INTERVAL_BUCKET_FUNCTION = {
    EmailStatsInterval.MINUTE: "toStartOfFiveMinutes",
    EmailStatsInterval.HOUR: "toStartOfHour",
    EmailStatsInterval.DAY: "toStartOfDay",
}


def _stats_interval(span: timedelta) -> EmailStatsInterval:
    if span <= timedelta(hours=2):
        return EmailStatsInterval.MINUTE
    if span <= timedelta(days=2):
        return EmailStatsInterval.HOUR
    return EmailStatsInterval.DAY


def _bucket_starts(start: datetime, end: datetime, interval: EmailStatsInterval, tz: ZoneInfo) -> list[datetime]:
    """The UTC start of every bucket from the one holding `start` up to `end`, in local time for the bucket edges."""
    local = start.astimezone(tz).replace(second=0, microsecond=0)
    if interval == EmailStatsInterval.DAY:
        day = local.replace(hour=0, minute=0)
        starts = []
        while day.astimezone(UTC) < end:
            starts.append(day.astimezone(UTC))
            # Wall-clock addition keeps each bucket on local midnight across a daylight saving change.
            day += timedelta(days=1)
        return starts
    if interval == EmailStatsInterval.HOUR:
        local, step = local.replace(minute=0), timedelta(hours=1)
    else:
        local, step = local.replace(minute=local.minute - local.minute % 5), timedelta(minutes=5)
    # UTC addition keeps the repeated hour when the clocks go back.
    moment = local.astimezone(UTC)
    starts = []
    while moment < end:
        starts.append(moment)
        moment += step
    return starts


def _sum_counts(counts: Sequence[TransactionalEmailStatsCounts]) -> TransactionalEmailStatsCounts:
    return TransactionalEmailStatsCounts(
        sent=sum(count.sent for count in counts),
        delivered=sum(count.delivered for count in counts),
        bounced=sum(count.bounced for count in counts),
        complained=sum(count.complained for count in counts),
        failed=sum(count.failed for count in counts),
    )


def transactional_email_stats_over_time(
    team_id: int,
    timezone: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    access: WorkflowViewAccess | None = None,
) -> TransactionalEmailStatsOverTime:
    """Delivery counts per time bucket in the team's timezone, with every empty bucket filled in."""
    period = _window(date_from, date_to)
    now = datetime.now(UTC)
    # The window reaches past now for clock skew, which is not time that the previous period can be compared with.
    span = min(period.end, now) - period.start
    interval = _stats_interval(span)
    tz = ZoneInfo(timezone)
    previous_start = period.start - span
    has_full_previous = previous_start >= now - RETENTION

    rows: list[tuple] = []
    if not _sees_no_sends(access):
        params: dict[str, Any] = {
            "start": previous_start if has_full_previous else period.start,
            "end": period.end,
            "period_start": period.start,
            "timezone": timezone,
        }
        access_filter = f"AND {_access_condition('message_function_id', access, params)}" if access is not None else ""
        rows = _execute(
            team_id,
            f"""
            SELECT
                queued_at >= %(period_start)s AS in_period,
                {_INTERVAL_BUCKET_FUNCTION[interval]}(queued_at, %(timezone)s) AS bucket,
                countIf(delivery_status IN ('sent', 'delivered', 'bounced', 'complained')) AS sent,
                countIf(delivery_status IN ('delivered', 'complained')) AS delivered,
                countIf(delivery_status = 'bounced') AS bounced,
                countIf(delivery_status = 'complained') AS complained,
                countIf(delivery_status = 'failed') AS failed
            FROM (
                SELECT {_MESSAGE_COLUMNS}
                FROM {EMAIL_STATUS_EVENTS_TABLE}
                WHERE team_id = %(team_id)s AND created_at >= %(start)s AND created_at < %(end)s
                GROUP BY created_at, message_id
            )
            WHERE delivery_status != '' {access_filter}
            GROUP BY in_period, bucket
            """,
            params,
            _GROUP_AS_READ,
        )

    current: dict[datetime, TransactionalEmailStatsCounts] = {}
    previous: list[TransactionalEmailStatsCounts] = []
    for in_period, bucket, sent, delivered, bounced, complained, failed in rows:
        counts = TransactionalEmailStatsCounts(
            sent=sent, delivered=delivered, bounced=bounced, complained=complained, failed=failed
        )
        if in_period:
            current[bucket.astimezone(UTC)] = counts
        else:
            previous.append(counts)

    empty = TransactionalEmailStatsCounts(sent=0, delivered=0, bounced=0, complained=0, failed=0)
    # A day that starts at 01:00 local time has a bucket the clock arithmetic can't name, so the rows' own keys stay.
    starts = sorted({*_bucket_starts(period.start, min(period.end, now), interval, tz), *current})
    buckets = [TransactionalEmailStatsBucket(start=start, counts=current.get(start, empty)) for start in starts]
    return TransactionalEmailStatsOverTime(
        interval=interval,
        timezone=timezone,
        buckets=buckets,
        previous=_sum_counts(previous) if has_full_previous else None,
    )


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

    conversions = _conversions(
        team, user, event, revenue_property, list(sends), first_send, window, start, end + window
    )
    converted_at = {person: conversion.first_at for person, conversion in conversions.items()}
    revenue = sum(conversion.revenue for conversion in conversions.values())

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


@frozen
class _Conversion:
    first_at: datetime
    revenue: float


def _conversions(
    team: Team,
    user: User | None,
    event: str,
    revenue_property: str | None,
    distinct_ids: list[str],
    first_send: dict[str, datetime],
    window: timedelta,
    start: datetime,
    end: datetime,
) -> dict[str, _Conversion]:
    """Each recipient's first conversion within `window` of their first send, and the revenue of those conversions.

    ClickHouse does the windowing and the sums, so a recipient comes back as one row however many events they did. A
    recipient with no person profile is keyed by distinct ID, the same way `transactional_email_results` keys their send.
    """
    revenue: ast.Expr = (
        ast.Call(
            name="toFloatOrNull",
            args=[ast.Call(name="toString", args=[ast.Field(chain=["properties", revenue_property])])],
        )
        if revenue_property
        else ast.Constant(value=None)
    )
    recipients = list(first_send)
    response = execute_hogql_query(
        """
        SELECT conversions.recipient, min(conversions.timestamp), sum(conversions.value)
        FROM (
            SELECT
                if(person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id IN {distinct_ids}),
                   toString(person_id), concat('distinct:', distinct_id)) AS recipient,
                timestamp,
                {revenue} AS value
            FROM events
            WHERE event = {event}
              AND timestamp >= {start} AND timestamp < {end}
              AND (distinct_id IN {distinct_ids}
                   OR person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id IN {distinct_ids}))
        ) AS conversions
        INNER JOIN (
            SELECT tupleElement(send, 1) AS recipient, fromUnixTimestamp64Milli(tupleElement(send, 2)) AS sent_at
            FROM (SELECT arrayJoin(arrayZip({recipients}, {sent_at_ms})) AS send)
        ) AS sends ON conversions.recipient = sends.recipient
        WHERE conversions.timestamp >= sends.sent_at
          AND conversions.timestamp <= sends.sent_at + toIntervalSecond({window_seconds})
        GROUP BY conversions.recipient
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
            "recipients": ast.Constant(value=recipients),
            "sent_at_ms": ast.Constant(
                value=[int(first_send[recipient].timestamp() * 1000) for recipient in recipients]
            ),
            "window_seconds": ast.Constant(value=int(window.total_seconds())),
            "limit": ast.Constant(value=len(recipients)),
        },
        query_type="transactional_email_results_conversions",
        workload=Workload.ONLINE,
    )
    return {
        recipient: _Conversion(first_at=first_at.astimezone(UTC), revenue=float(total or 0.0))
        for recipient, first_at, total in response.results or []
    }
