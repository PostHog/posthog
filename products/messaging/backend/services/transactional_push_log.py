"""The transactional push log: every send of a project's push notifications, and how many went out.

Each send is one run of the push's workflow. A run that delivered to a device stored a copy of the push, so a finished
run with no copy did not reach anyone, and the warnings its push step logged say why.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import (
    PushSendStatus,
    TransactionalPushLogEntry,
    TransactionalPushStatsRow,
)
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.facade.contracts import WorkflowViewAccess

# Runs, stored pushes and run logs are all kept this long.
PUSH_LOG_RETENTION_DAYS = 30
RETENTION = timedelta(days=PUSH_LOG_RETENTION_DAYS)
# The send API stamps a run with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
# A send's step logs a line per device platform, so a handful covers every reason.
_MAX_MESSAGES = 10
# The step logs its terminal error twice, once more behind "Errored: Error:", and the run records it a third time.
_ACTION_PREFIX = re.compile(r"^\[Action:[^\]]*\]\s*(?:Errored:\s*(?:Error:\s*)?)?")

_RUNS = """
    SELECT
        invocation_id,
        min(scheduled_at) AS queued_at,
        argMax(status, version) AS run_status,
        argMax(error_message, version) AS run_error,
        argMax(distinct_id, version) AS run_distinct_id,
        argMax(person_id, version) AS run_person_id,
        any(function_id) AS run_workflow_id,
        argMax(is_deleted, version) AS run_is_deleted
    FROM hog_invocation_results
    WHERE team_id = %(team_id)s
      AND function_kind = 'hog_flow'
      AND function_id IN %(workflows)s
      AND scheduled_at >= toDateTime64(%(start)s, 6)
      AND scheduled_at < toDateTime64(%(end)s, 6)
      {search}
    GROUP BY invocation_id
"""

# A run counts as sent once any device took the push, which is when its copy is stored.
_SEND_STATUS = """
    multiIf(
        run_status = 'running', 'sending',
        run_status IN ('failed', 'canceled'), 'failed',
        invocation_id IN (
            SELECT invocation_id FROM message_assets
            WHERE team_id = %(team_id)s
              AND function_kind = 'hog_flow'
              AND kind = 'push'
              AND function_id IN %(workflows)s
              AND sent_at >= toDateTime64(%(start)s, 6)
        ), 'sent',
        'not_sent'
    )
"""


@frozen
class _Period:
    start: datetime
    end: datetime


def _window(date_from: datetime | None, date_to: datetime | None) -> _Period:
    now = datetime.now(UTC)
    start = max(date_from or now - timedelta(days=7), now - RETENTION)
    end = min(date_to, now + _CLOCK_SKEW) if date_to else now + _CLOCK_SKEW
    return _Period(start=start, end=end)


def _ch_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _execute(team_id: int, query: str, params: dict[str, Any]) -> list[tuple]:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    # The log is read by a person looking at the page.
    return cast(list, sync_execute(query, {"team_id": team_id, **params}, workload=Workload.ONLINE, team_id=team_id))


def _push_templates(team_id: int, access: WorkflowViewAccess | None) -> dict[str, MessageTemplate]:
    """The project's sendable push notifications that the reader may view, by the workflow behind each."""
    templates = MessageTemplate.objects.filter(
        team_id=team_id, type="push", deleted=False, transactional_hog_flow_id__isnull=False
    )
    by_workflow = {str(template.transactional_hog_flow_id): template for template in templates}
    if access is None:
        return by_workflow
    return {workflow_id: template for workflow_id, template in by_workflow.items() if access.allows(workflow_id)}


def _step_messages(
    team_id: int, workflow_ids: Sequence[str], run_ids: Sequence[str], start: datetime
) -> dict[str, list[str]]:
    if not run_ids:
        return {}
    rows = _execute(
        team_id,
        """
        SELECT instance_id, groupArray(%(max_messages)s)(message)
        FROM (
            SELECT instance_id, message
            FROM log_entries
            WHERE team_id = %(team_id)s
              AND log_source = 'hog_flow'
              AND log_source_id IN %(workflows)s
              AND instance_id IN %(runs)s
              AND timestamp >= toDateTime64(%(start)s, 6)
              AND level IN ('warn', 'error')
              AND startsWith(message, '[Action:')
            ORDER BY timestamp
        )
        GROUP BY instance_id
        """,
        {
            "workflows": list(workflow_ids),
            "runs": list(run_ids),
            "start": _ch_time(start - _CLOCK_SKEW),
            "max_messages": _MAX_MESSAGES,
        },
    )
    return {run_id: [_ACTION_PREFIX.sub("", message) for message in messages] for run_id, messages in rows}


def _titles(team_id: int, workflow_ids: Sequence[str], run_ids: Sequence[str], start: datetime) -> dict[str, str]:
    if not run_ids:
        return {}
    rows = _execute(
        team_id,
        """
        SELECT invocation_id, argMax(subject, version)
        FROM message_assets
        WHERE team_id = %(team_id)s
          AND function_kind = 'hog_flow'
          AND kind = 'push'
          AND function_id IN %(workflows)s
          AND invocation_id IN %(runs)s
          AND sent_at >= toDateTime64(%(start)s, 6)
        GROUP BY invocation_id
        """,
        {"workflows": list(workflow_ids), "runs": list(run_ids), "start": _ch_time(start)},
    )
    return dict(rows)


def list_transactional_pushes(
    team_id: int,
    *,
    search: str | None = None,
    status: PushSendStatus | None = None,
    workflow_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    access: WorkflowViewAccess | None = None,
) -> tuple[list[TransactionalPushLogEntry], bool]:
    """A page of the project's push sends, newest first, and whether more follow. `access` limits the sends to the
    workflows the reader may view, and None reads them all."""
    templates = _push_templates(team_id, access)
    workflow_ids = [workflow_id] if workflow_id else list(templates)
    workflow_ids = [workflow for workflow in workflow_ids if workflow in templates]
    if not workflow_ids:
        return [], False

    period = _window(date_from, date_to)
    params: dict[str, Any] = {
        "workflows": workflow_ids,
        "start": _ch_time(period.start),
        "end": _ch_time(period.end),
        "limit": limit + 1,
        "offset": offset,
    }
    search_condition = ""
    if search and search.strip():
        params["search"] = search.strip()
        search_condition = "AND (distinct_id = %(search)s OR invocation_id = %(search)s)"
    status_condition = ""
    if status:
        params["status"] = status.value
        status_condition = "WHERE send_status = %(status)s"

    rows = _execute(
        team_id,
        f"""
        SELECT invocation_id, queued_at, send_status, run_error, run_distinct_id, run_person_id, run_workflow_id
        FROM (
            SELECT *, {_SEND_STATUS} AS send_status
            FROM ({_RUNS.format(search=search_condition)})
            WHERE run_is_deleted = 0
        )
        {status_condition}
        ORDER BY queued_at DESC, invocation_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]

    unsent = [row[0] for row in rows if row[2] != PushSendStatus.SENT.value]
    sent = [row[0] for row in rows if row[2] == PushSendStatus.SENT.value]
    messages = _step_messages(team_id, workflow_ids, unsent, period.start)
    titles = _titles(team_id, workflow_ids, sent, period.start)

    entries = []
    for run_id, queued_at, send_status, run_error, distinct_id, person_id, run_workflow_id in rows:
        template = templates[run_workflow_id]
        run_messages = [*messages.get(run_id, []), *([run_error] if run_error else [])]
        entries.append(
            TransactionalPushLogEntry(
                run_id=run_id,
                created_at=queued_at.replace(tzinfo=UTC),
                status=PushSendStatus(send_status),
                messages=tuple(dict.fromkeys(run_messages)),
                distinct_id=distinct_id,
                person_id=person_id,
                workflow_id=run_workflow_id,
                template_id=str(template.id),
                template_name=template.name,
                title=titles.get(run_id, ""),
            )
        )
    return entries, has_more


def transactional_push_stats(
    team_id: int,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    access: WorkflowViewAccess | None = None,
) -> list[TransactionalPushStatsRow]:
    """How many sends of each push notification went out, busiest first. Counts the same sends the log lists."""
    templates = _push_templates(team_id, access)
    if not templates:
        return []
    period = _window(date_from, date_to)
    rows = _execute(
        team_id,
        f"""
        SELECT
            run_workflow_id,
            countIf(send_status = 'sent'),
            countIf(send_status = 'not_sent'),
            countIf(send_status = 'failed')
        FROM (
            SELECT run_workflow_id, {_SEND_STATUS} AS send_status
            FROM ({_RUNS.format(search="")})
            WHERE run_is_deleted = 0
        )
        GROUP BY run_workflow_id
        """,
        {"workflows": list(templates), "start": _ch_time(period.start), "end": _ch_time(period.end)},
    )
    stats = [
        TransactionalPushStatsRow(
            template_id=str(templates[workflow_id].id),
            template_name=templates[workflow_id].name,
            sent=sent,
            not_sent=not_sent,
            failed=failed,
        )
        for workflow_id, sent, not_sent, failed in rows
        if workflow_id in templates
    ]
    return sorted(stats, key=lambda row: row.sent + row.not_sent + row.failed, reverse=True)
