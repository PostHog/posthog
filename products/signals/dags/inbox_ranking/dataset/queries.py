"""SQL and row-shaping for the inbox-ranking dataset assets.

The label SQL inlines the canonical `inbox_ranking_*` warehouse-view logic (versioned in the
inbox-ranking skill's references/views.md) with explicit event-time bounds instead of the views'
rolling 90-day window, which would silently drop old labels from backfilled partitions. Every
query is bounded `[{labels_epoch}, {snapshot_end})` so a partition is reproducible for any past
day.
"""

import uuid
import datetime
from typing import Any

import dagster

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.cloud_utils import is_cloud
from posthog.models import Team

from products.signals.dags.inbox_ranking.common import LABELS_EPOCH, ensure_utc

# All regions' label telemetry lands in the US dogfood project (PostHog internal, team 2).
LABELS_TEAM_ID = 2

# Naming scheme from products/error_tracking/backend/indexed_embedding.py (the shared
# document-embeddings infrastructure): distributed_posthog_document_embeddings_<model_name>.
EMBEDDINGS_TABLE = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"


def labels_team() -> Team:
    try:
        return Team.objects.get(id=LABELS_TEAM_ID)
    except Team.DoesNotExist:
        raise dagster.Failure(
            f"Labels team {LABELS_TEAM_ID} does not exist in this environment; the inbox ranking "
            "dataset can only be built where the dogfood project is present"
        )


def etl_workload() -> Workload:
    """Route ETL reads to the offline cluster replicas on Cloud so they never compete with
    customer-facing queries; local and self-hosted deployments have no offline cluster."""
    return Workload.OFFLINE if is_cloud() else Workload.DEFAULT


def hogql_rows(sql: str, *, team: Team, query_type: str, snapshot_end: datetime.datetime) -> list[tuple[Any, ...]]:
    response = execute_hogql_query(
        query=sql,
        team=team,
        query_type=query_type,
        placeholders={
            "labels_epoch": ast.Constant(value=LABELS_EPOCH),
            "snapshot_end": ast.Constant(value=snapshot_end.strftime("%Y-%m-%d %H:%M:%S")),
        },
        limit_context=LimitContext.SAVED_QUERY,
        workload=etl_workload(),
        # The label window grows cumulatively from LABELS_EPOCH, so these aggregates need more
        # than the 60s HogQL default; the sort key (team, date, event) keeps the scan bounded.
        settings=HogQLGlobalSettings(max_execution_time=600),
        # The dag runs without a user; the read is a trusted internal ETL over the dogfood project.
        bypass_warehouse_access_control=True,
    )
    return [tuple(row) for row in response.results or []]


def valid_report_uuids(report_ids: set[str]) -> set[str]:
    """Label events are client-supplied; drop ids that cannot be report UUIDs before ORM lookups."""
    valid: set[str] = set()
    for report_id in report_ids:
        try:
            uuid.UUID(report_id)
        except ValueError:
            continue
        valid.add(report_id)
    return valid


LABELED_REPORT_IDS_SQL = """
SELECT DISTINCT report_id
FROM (
    SELECT JSONExtractString(imp, 'report_id') AS report_id
    FROM events
    ARRAY JOIN JSONExtractArrayRaw(coalesce(properties.impressions, '[]')) AS imp
    WHERE event = 'Inbox reports impressed'
      AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
    UNION ALL
    SELECT toString(properties.report_id) AS report_id
    FROM events
    WHERE event IN ('Inbox report opened', 'Inbox report action', 'signal_report_status_changed')
      AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
    UNION ALL
    SELECT toString(properties.signal_report_id) AS report_id
    FROM events
    WHERE event IN ('pr_created', 'pr_merged', 'pr_closed')
      AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
)
WHERE report_id != ''
"""

# Point-in-time caveat: the source is a ReplacingMergeTree versioned by inserted_at, so merges
# keep only the newest version of each key. The inserted_at bound is exact on forward daily runs,
# but a backfill run after a re-embedding or tombstone superseded the vector that existed on the
# snapshot day can return no row for it. embedding_inserted_at lineage records which version each
# row actually carries.
#
# Index reality: the sharded table orders by (team_id, toDate(timestamp), product, document_type,
# rendering, ...) and this cross-team query has no team_id prefix, so it scans the whole table.
# That is acceptable because the 3-month TTL bounds the table and PREWHERE filters the small
# string columns before the wide embedding column is read; the settings below cap the blast
# radius and keep the distributed GROUP BY (1536-float argMax states) memory-efficient.
REPORT_EMBEDDINGS_QUERY_SETTINGS: dict[str, int] = {
    "max_execution_time": 600,
    "max_memory_usage": 20 * 1024**3,
    "max_bytes_before_external_group_by": 10 * 1024**3,
    "distributed_aggregation_memory_efficient": 1,
}

REPORT_EMBEDDINGS_SQL = f"""
SELECT
    team_id,
    document_id,
    argMax(embedding, inserted_at) AS embedding,
    argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) AS is_tombstone,
    max(inserted_at) AS embedding_inserted_at
FROM {EMBEDDINGS_TABLE}
WHERE product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND inserted_at < %(snapshot_end)s
GROUP BY team_id, document_id
"""

IMPRESSIONS_COLUMNS = (
    "first_impressed_at",
    "impression_unit_count",
    "impressed_user_count",
    "first_impression_rank",
    "best_impression_rank",
    "source_products",
)
IMPRESSIONS_SQL = """
SELECT
    JSONExtractString(imp, 'report_id') AS report_id,
    min(timestamp) AS first_impressed_at,
    count() AS impression_unit_count,
    uniq(distinct_id) AS impressed_user_count,
    argMin(JSONExtractInt(imp, 'rank'), timestamp) AS first_impression_rank,
    min(JSONExtractInt(imp, 'rank')) AS best_impression_rank,
    argMax(JSONExtract(imp, 'source_products', 'Array(String)'), timestamp) AS source_products
FROM events
ARRAY JOIN JSONExtractArrayRaw(coalesce(properties.impressions, '[]')) AS imp
WHERE event = 'Inbox reports impressed'
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
GROUP BY report_id
HAVING report_id != ''
"""

OPENS_COLUMNS = ("first_opened_at", "open_count", "opened_user_count")
OPENS_SQL = """
SELECT
    toString(properties.report_id) AS report_id,
    min(timestamp) AS first_opened_at,
    count() AS open_count,
    uniq(distinct_id) AS opened_user_count
FROM events
WHERE event = 'Inbox report opened'
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
  AND toString(properties.report_id) != ''
GROUP BY report_id
"""

ACTIONS_COLUMNS = (
    "ui_dismiss_count",
    "first_ui_dismissed_at",
    "create_pr_click_count",
    "first_create_pr_clicked_at",
    "discuss_count",
    "snooze_count",
)
# Bulk action rows carry no report_id and are excluded; bulk dismissals are recovered from the
# server-side status stream instead. minIf misses fill non-nullable datetimes with epoch 0, hence
# the nullIf(..., fromUnixTimestamp(0)) wraps here and below.
ACTIONS_SQL = """
SELECT
    toString(properties.report_id) AS report_id,
    countIf(toString(properties.action_type) = 'dismiss') AS ui_dismiss_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'dismiss'), fromUnixTimestamp(0)) AS first_ui_dismissed_at,
    countIf(toString(properties.action_type) = 'create_pr') AS create_pr_click_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'create_pr'), fromUnixTimestamp(0)) AS first_create_pr_clicked_at,
    countIf(toString(properties.action_type) = 'discuss') AS discuss_count,
    countIf(toString(properties.action_type) = 'snooze') AS snooze_count
FROM events
WHERE event = 'Inbox report action'
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
  AND toString(properties.report_id) != ''
GROUP BY report_id
"""

STATUS_COLUMNS = (
    "first_resolved_at",
    "first_dismissed_server_at",
    "first_failed_at",
    "first_snoozed_at",
    "latest_status_event",
    "latest_status_event_at",
    "dismissal_reason",
)
# The inner query dedupes at-least-once analytics delivery within 10-minute buckets;
# events.timestamp is qualified because the min() alias shadows the raw column in WHERE/GROUP BY.
STATUS_SQL = """
SELECT
    report_id,
    nullIf(minIf(timestamp, outcome = 'resolved'), fromUnixTimestamp(0)) AS first_resolved_at,
    nullIf(minIf(timestamp, outcome = 'dismissed'), fromUnixTimestamp(0)) AS first_dismissed_server_at,
    nullIf(minIf(timestamp, outcome = 'failed'), fromUnixTimestamp(0)) AS first_failed_at,
    nullIf(minIf(timestamp, outcome = 'snoozed'), fromUnixTimestamp(0)) AS first_snoozed_at,
    argMax(status, timestamp) AS latest_status_event,
    max(timestamp) AS latest_status_event_at,
    argMax(dismissal_reason, timestamp) AS dismissal_reason
FROM (
    SELECT
        min(events.timestamp) AS timestamp,
        toString(properties.report_id) AS report_id,
        toString(properties.previous_status) AS previous_status,
        toString(properties.status) AS status,
        multiIf(
            toString(properties.status) = 'suppressed', 'dismissed',
            toString(properties.status) = 'resolved', 'resolved',
            toString(properties.status) = 'failed', 'failed',
            toString(properties.previous_status) IN ('ready', 'resolved') AND toString(properties.status) = 'potential', 'snoozed',
            'other'
        ) AS outcome,
        any(nullIf(toString(properties.dismissal_reason), '')) AS dismissal_reason
    FROM events
    WHERE event = 'signal_report_status_changed'
      AND events.timestamp >= toDateTime({labels_epoch}) AND events.timestamp < toDateTime({snapshot_end})
      AND toString(properties.report_id) != ''
    GROUP BY
        report_id,
        previous_status,
        status,
        toStartOfInterval(events.timestamp, INTERVAL 10 MINUTE)
)
GROUP BY report_id
"""

PR_COLUMNS = (
    "pr_created_count",
    "first_pr_created_at",
    "pr_merged_count",
    "first_pr_merged_at",
    "pr_closed_count",
)
PR_EVENTS_SQL = """
SELECT
    toString(properties.signal_report_id) AS report_id,
    countIf(event = 'pr_created') AS pr_created_count,
    nullIf(minIf(timestamp, event = 'pr_created'), fromUnixTimestamp(0)) AS first_pr_created_at,
    countIf(event = 'pr_merged') AS pr_merged_count,
    nullIf(minIf(timestamp, event = 'pr_merged'), fromUnixTimestamp(0)) AS first_pr_merged_at,
    countIf(event = 'pr_closed') AS pr_closed_count
FROM events
WHERE event IN ('pr_created', 'pr_merged', 'pr_closed')
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
  AND properties.signal_report_id IS NOT NULL
  AND toString(properties.signal_report_id) != ''
GROUP BY report_id
"""

LABEL_STREAMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("impressions", IMPRESSIONS_SQL, IMPRESSIONS_COLUMNS),
    ("opens", OPENS_SQL, OPENS_COLUMNS),
    ("actions", ACTIONS_SQL, ACTIONS_COLUMNS),
    ("status_changes", STATUS_SQL, STATUS_COLUMNS),
    ("pr_events", PR_EVENTS_SQL, PR_COLUMNS),
)

# Every label column a report can have, with its no-events default. Streams overwrite their own
# columns; the merge keeps counts at 0 (not null) so head derivations need no null handling.
LABEL_DEFAULTS: dict[str, Any] = {
    "first_impressed_at": None,
    "impression_unit_count": 0,
    "impressed_user_count": 0,
    "first_impression_rank": None,
    "best_impression_rank": None,
    "source_products": None,
    "first_opened_at": None,
    "open_count": 0,
    "opened_user_count": 0,
    "ui_dismiss_count": 0,
    "first_ui_dismissed_at": None,
    "create_pr_click_count": 0,
    "first_create_pr_clicked_at": None,
    "discuss_count": 0,
    "snooze_count": 0,
    "first_resolved_at": None,
    "first_dismissed_server_at": None,
    "first_failed_at": None,
    "first_snoozed_at": None,
    "latest_status_event": None,
    "latest_status_event_at": None,
    "dismissal_reason": None,
    "pr_created_count": 0,
    "first_pr_created_at": None,
    "pr_merged_count": 0,
    "first_pr_merged_at": None,
    "pr_closed_count": 0,
}

_TIMESTAMP_LABEL_COLUMNS = frozenset(name for name in LABEL_DEFAULTS if name.endswith("_at"))


def merge_label_streams(
    stream_rows: dict[str, list[tuple[Any, ...]]], snapshot_date: datetime.date
) -> list[dict[str, Any]]:
    """Merge the per-stream aggregates (each row `(report_id, *stream_columns)`) into one labels
    row per report, filling unseen streams with LABEL_DEFAULTS."""
    merged: dict[str, dict[str, Any]] = {}
    columns_by_stream = {name: columns for name, _, columns in LABEL_STREAMS}
    for stream_name, rows in stream_rows.items():
        columns = columns_by_stream[stream_name]
        for row in rows:
            report_id = str(row[0])
            entry = merged.setdefault(
                report_id,
                {"snapshot_date": snapshot_date, "report_id": report_id, **LABEL_DEFAULTS},
            )
            for column, value in zip(columns, row[1:], strict=True):
                entry[column] = ensure_utc(value) if column in _TIMESTAMP_LABEL_COLUMNS else value
    return list(merged.values())
