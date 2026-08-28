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

from products.signals.dags.inbox_ranking.common import LABELS_EPOCH, WRONG_DISMISSAL_REASONS, ensure_utc

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


def utc_bound(value: datetime.datetime) -> str:
    """Render a UTC instant for a HogQL toDateTime() placeholder. The explicit +00:00 offset is
    load-bearing: HogQL parses bare datetime strings in the querying team's timezone (US/Pacific
    for the dogfood project), which would silently shift every bound 7-8 hours."""
    return value.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def hogql_rows(sql: str, *, team: Team, query_type: str, snapshot_end: datetime.datetime) -> list[tuple[Any, ...]]:
    response = execute_hogql_query(
        query=sql,
        team=team,
        query_type=query_type,
        placeholders={
            "labels_epoch": ast.Constant(value=LABELS_EPOCH),
            "snapshot_end": ast.Constant(value=utc_bound(snapshot_end)),
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


def canonical_report_uuid(report_id: str | None) -> str | None:
    """Canonical lowercase-hyphenated form of a client-supplied report id, or None when it cannot
    be a report UUID. Canonicalizing (not just validating) matters because a case or hyphenation
    variant would otherwise survive as a separate label-only row instead of joining its report."""
    try:
        return str(uuid.UUID(report_id))
    except ValueError:
        return None
    except TypeError:
        # uuid.UUID(None) raises TypeError, not ValueError; a missing event property surfaces
        # as a None cell in HogQL results.
        return None


def valid_report_uuids(report_ids: set[str | None]) -> set[str]:
    """Label events are client-supplied; drop ids that cannot be report UUIDs before ORM lookups."""
    return {canonical for report_id in report_ids if (canonical := canonical_report_uuid(report_id)) is not None}


# Trust boundary for every label stream below: these are analytics events captured in the dogfood
# project, not authoritative records, so a label attests that an event arrived and never that the
# thing it describes happened. The authoritative rows (SignalReport, SignalReportRefund) sit in
# per-region Postgres while this dag runs US-only, so sourcing labels from them would silently drop
# every non-US report — the same constraint that makes cross-region reports label-only (README.md).
# Weight a label by how it is produced: the status, pr and refund streams are server-emitted behind
# authenticated endpoints, while impressions, opens, actions and feedback come from the clients.

# The `Inbox report feedback` producer contract (products/signals/frontend/inbox/inboxAnalytics.ts emits
# exactly these two). Applied to the labeled-id spine and the feedback stream alike, so an event
# whose sentiment is missing or off-contract carries no label and can neither mint a label-only
# training row nor stamp a feedback label onto a real report.
FEEDBACK_SENTIMENTS_SQL = "toString(properties.sentiment) IN ('positive', 'negative')"

# The feedback filter rides as a second predicate rather than its own UNION branch so the whole
# select keeps one sort-key-aligned `event IN (...)` scan.
LABELED_REPORT_IDS_SQL = f"""
SELECT DISTINCT report_id
FROM (
    SELECT JSONExtractString(imp, 'report_id') AS report_id
    FROM events
    ARRAY JOIN JSONExtractArrayRaw(coalesce(properties.impressions, '[]')) AS imp
    WHERE event = 'Inbox reports impressed'
      AND timestamp >= toDateTime({{labels_epoch}}) AND timestamp < toDateTime({{snapshot_end}})
    UNION ALL
    SELECT toString(properties.report_id) AS report_id
    FROM events
    WHERE event IN (
        'Inbox report opened',
        'Inbox report action',
        'Inbox report feedback',
        'signal_report_status_changed',
        'signals_pr_refund_created'
    )
      AND (event != 'Inbox report feedback' OR {FEEDBACK_SENTIMENTS_SQL})
      AND timestamp >= toDateTime({{labels_epoch}}) AND timestamp < toDateTime({{snapshot_end}})
    UNION ALL
    SELECT toString(properties.signal_report_id) AS report_id
    FROM events
    WHERE event IN ('pr_created', 'pr_merged', 'pr_closed')
      AND timestamp >= toDateTime({{labels_epoch}}) AND timestamp < toDateTime({{snapshot_end}})
)
-- The null guard is load-bearing: an event missing its report id property yields a NULL report_id
-- (most pr_* events are not born from a signal report), and HogQL's null-safe inequality evaluates
-- NULL != '' to true, so the empty-string filter alone would pass a NULL row through.
WHERE report_id IS NOT NULL AND report_id != ''
"""

# Point-in-time caveat: the source is a ReplacingMergeTree versioned by inserted_at, so merges
# keep only the newest version of each key. A run that happens after a re-embedding or tombstone
# superseded the vector that existed on the snapshot day can therefore return no row for that
# report — mostly a backfill concern, but forward runs are exposed too, for the 2.5 hours between
# the snapshot cutoff and the 02:30 schedule. Reports are embedded once at promotion, so this only
# bites the rare re-render; the vector reappears on the next partition, and embedding_inserted_at
# lineage records which version each row actually carries.
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

# Signal documents: the grouping pipeline's own rows in the same table, one per signal, carrying the
# report they grouped into in the metadata JSON. Read incrementally by inserted_at rather than as a
# snapshot — at signal grain a cumulative copy is several GB a day (a 1536-float vector per signal,
# fleet-wide) against tens of MB for one day's emissions.
#
# Rows come back raw, with no argMax dedupe: this scan never builds the wide aggregation states the
# report query needs, and both versions of a re-emitted signal are kept when both survive to be read.
# Readers take the latest row per (team_id, signal_id) at or before their cutoff, because a
# caller-supplied document_id is only unique within a team.
#
# "When both survive" is the honest limit: the source replaces on (team, day, product, document_type,
# rendering, document_id) and a retraction re-emits under that same key, so a merge before this scan
# leaves only the retraction. argMax would not save it — the merge removes the row, it does not hide
# it. The asset docstring records what that costs and why closing it is out of scope here.
#
# Index reality is the report query's, minus the GROUP BY: no team_id sort-key prefix and no
# inserted_at in the sort key, so this full-scans the TTL-bounded table with PREWHERE filtering the
# small columns before the wide embedding column is read. The memory budget is half the report
# scan's because nothing is aggregated.
SIGNAL_EMBEDDINGS_QUERY_SETTINGS: dict[str, int] = {
    "max_execution_time": 600,
    "max_memory_usage": 10 * 1024**3,
}

# `content` is deliberately not selected: the vector is the feature, and the signal's verbatim source
# text has no business leaving ClickHouse. Same for the free-text metadata fields (extra, remediation,
# match_query, reason) — only the structured ones are extracted here.
SIGNAL_EMBEDDINGS_SQL = f"""
SELECT
    team_id,
    document_id,
    nullIf(JSONExtractString(metadata, 'report_id'), '') AS report_id,
    timestamp,
    inserted_at,
    embedding,
    JSONExtractFloat(metadata, 'weight') AS weight,
    nullIf(JSONExtractString(metadata, 'source_product'), '') AS source_product,
    nullIf(JSONExtractString(metadata, 'source_type'), '') AS source_type,
    nullIf(JSONExtractString(metadata, 'source_id'), '') AS source_id,
    JSONExtractBool(metadata, 'deleted') AS is_deleted,
    -- A matched signal's metadata carries parent_signal_id, an unmatched one's carries
    -- rejected_signal_ids, and both carry reason — so the parent check has to come first.
    nullIf(
        multiIf(
            JSONHas(metadata, 'match_metadata', 'parent_signal_id'), 'matched',
            JSONHas(metadata, 'match_metadata', 'reason'), 'no_match',
            ''
        ),
        ''
    ) AS match_kind,
    nullIf(JSONExtractString(metadata, 'match_metadata', 'parent_signal_id'), '') AS match_parent_signal_id,
    JSONLength(metadata, 'match_metadata', 'rejected_signal_ids') AS rejected_signal_count
FROM {EMBEDDINGS_TABLE}
WHERE product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND inserted_at >= %(window_start)s
  AND inserted_at < %(window_end)s
"""

IMPRESSIONS_COLUMNS = (
    "first_impressed_at",
    "impression_unit_count",
    "impressed_user_count",
    "first_impression_rank",
    "best_impression_rank",
    "source_products",
)
# Ranks come from client-supplied JSON, so they can be any Int64, and JSONExtractInt yields 0 for
# a missing or non-numeric value. The producer contract (products/signals/frontend/inbox/inboxAnalytics.ts)
# is 1-based, so anything below 1 is malformed; anything above int32 would raise on the Parquet
# conversion and fail the whole fleet-wide labels asset. Both are nulled out, and the impression
# still counts toward the impression/user counts.
_IMPRESSION_RANK = (
    "if(JSONExtractInt(imp, 'rank') >= 1 AND JSONExtractInt(imp, 'rank') <= 2147483647, "
    "JSONExtractInt(imp, 'rank'), NULL)"
)
IMPRESSIONS_SQL = f"""
SELECT
    JSONExtractString(imp, 'report_id') AS report_id,
    min(timestamp) AS first_impressed_at,
    count() AS impression_unit_count,
    uniq(distinct_id) AS impressed_user_count,
    argMinIf({_IMPRESSION_RANK}, timestamp, {_IMPRESSION_RANK} IS NOT NULL) AS first_impression_rank,
    min({_IMPRESSION_RANK}) AS best_impression_rank,
    argMax(JSONExtract(imp, 'source_products', 'Array(String)'), timestamp) AS source_products
FROM events
ARRAY JOIN JSONExtractArrayRaw(coalesce(properties.impressions, '[]')) AS imp
WHERE event = 'Inbox reports impressed'
  AND timestamp >= toDateTime({{labels_epoch}}) AND timestamp < toDateTime({{snapshot_end}})
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
    "reviewer_add_count",
    "first_reviewer_added_at",
    "reviewer_remove_count",
    "first_reviewer_removed_at",
)
# Bulk action rows carry no report_id and are excluded; bulk dismissals are recovered from the
# server-side status stream instead. minIf misses fill non-nullable datetimes with epoch 0, hence
# the nullIf(..., fromUnixTimestamp(0)) wraps here and below.
#
# The reviewer actions edit the report's suggested-reviewer list: adding one is a mild positive
# engagement signal, removing one plausibly means the suggested-reviewer heuristic mis-routed the
# report, which is useful to the policy layer even if never a model head. `click_suggested_reviewer`
# also exists but is deliberately not aggregated: it fires so rarely it carries no signal.
ACTIONS_SQL = """
SELECT
    toString(properties.report_id) AS report_id,
    countIf(toString(properties.action_type) = 'dismiss') AS ui_dismiss_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'dismiss'), fromUnixTimestamp(0)) AS first_ui_dismissed_at,
    countIf(toString(properties.action_type) = 'create_pr') AS create_pr_click_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'create_pr'), fromUnixTimestamp(0)) AS first_create_pr_clicked_at,
    countIf(toString(properties.action_type) = 'discuss') AS discuss_count,
    countIf(toString(properties.action_type) = 'snooze') AS snooze_count,
    countIf(toString(properties.action_type) = 'add_suggested_reviewer') AS reviewer_add_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'add_suggested_reviewer'), fromUnixTimestamp(0)) AS first_reviewer_added_at,
    countIf(toString(properties.action_type) = 'remove_suggested_reviewer') AS reviewer_remove_count,
    nullIf(minIf(timestamp, toString(properties.action_type) = 'remove_suggested_reviewer'), fromUnixTimestamp(0)) AS first_reviewer_removed_at
FROM events
WHERE event = 'Inbox report action'
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
  AND toString(properties.report_id) != ''
GROUP BY report_id
"""

_WRONG_DISMISSAL_REASONS_SQL = ", ".join(f"'{reason}'" for reason in WRONG_DISMISSAL_REASONS)

STATUS_COLUMNS = (
    "first_resolved_at",
    "first_dismissed_server_at",
    "first_failed_at",
    "first_snoozed_at",
    "latest_status_event",
    "latest_status_event_at",
    "dismissal_reason",
    "wrong_dismissal_count",
    "status_event_priority",
    "status_event_actionability",
    "status_event_team_id",
)
# The inner query dedupes at-least-once analytics delivery within 10-minute buckets; events.timestamp
# is qualified because the min()/max() aliases shadow the raw column in WHERE/GROUP BY.
#
# A bucket keeps both its first and last timestamp because the grouping can also collapse genuine
# repeats — dismiss, restore, dismiss again inside ten minutes is one bucket of two real events.
# `first_*` reads the bucket's first timestamp and everything latest-wins reads its last, so the
# intervening restore can no longer out-rank the dismissal that actually came after it.
#
# status_event_priority/actionability are the classification the *event* carried, which is why
# capture_status_change_analytics snapshots them onto every transition: artefacts can be re-judged
# or edited, so the state asset's cutoff-observed judgment is not necessarily what was true when
# the outcome happened. Both are kept — state for features, these for label-time provenance.
STATUS_SQL = (
    """
SELECT
    report_id,
    nullIf(minIf(first_timestamp, outcome = 'resolved'), fromUnixTimestamp(0)) AS first_resolved_at,
    nullIf(minIf(first_timestamp, outcome = 'dismissed'), fromUnixTimestamp(0)) AS first_dismissed_server_at,
    nullIf(minIf(first_timestamp, outcome = 'failed'), fromUnixTimestamp(0)) AS first_failed_at,
    nullIf(minIf(first_timestamp, outcome = 'snoozed'), fromUnixTimestamp(0)) AS first_snoozed_at,
    argMax(status, last_timestamp) AS latest_status_event,
    max(last_timestamp) AS latest_status_event_at,
    -- argMax skips NULL values, so this is the reason from the latest *reasoned* transition (the
    -- intended semantic: reasons only accompany dismissals/snoozes), not necessarily paired with
    -- latest_status_event above. Restricted to the latest transition's tenant, like the count
    -- below: a reason-less genuine transition must not let an older reason from another team
    -- through.
    argMaxIf(bucket_dismissal_reason, last_timestamp, event_team_id = latest_event_team_id) AS dismissal_reason,
    -- Cumulative, unlike dismissal_reason above: a restore or a later dismissal with another reason
    -- overwrites the latest-wins reason, and a label that can revert to 0 breaks the training
    -- builder's assumption that labels only grow. Counted per bucket (a bucket that saw any wrong
    -- reason counts once, so a same-bucket re-dismissal cannot erase it) and only for buckets that
    -- name the same tenant as the latest transition, which is the event the provenance
    -- cross-check validates against Postgres. Buckets are split by tenant, so the flag and the
    -- team it is checked against always come from the same events. The dismiss_wrong head reads
    -- this column.
    countIf(
        outcome = 'dismissed' AND bucket_wrong_dismissal = 1 AND event_team_id = latest_event_team_id
    ) AS wrong_dismissal_count,
    -- These two must stay paired with latest_status_event, so coalesce/nullIf keeps argMax from
    -- skipping a null: a judgment artefact can be deleted, and then the latest transition
    -- genuinely carries none. Plain argMax would reach back to an older transition and present
    -- its classification as the one this outcome was judged at.
    nullIf(argMax(coalesce(event_priority, ''), last_timestamp), '') AS status_event_priority,
    nullIf(argMax(coalesce(event_actionability, ''), last_timestamp), '') AS status_event_actionability,
    -- The owning team as the transition itself reported it. This is the only tenant attribution a
    -- label-only row can have: reports outside this dag's region have no Postgres state and no
    -- embedding here. Deliberately *not* merged into report_team_id, which is a US team id by
    -- construction — team ids are per-region, so an EU 42 and a US 42 are different teams and
    -- nothing on the event says which region emitted it. Read from the window column rather than
    -- selected again, so the tenant the provenance check sees is the one the aggregates above
    -- filtered on, even when two tenants' buckets tie on last_timestamp.
    toInt(any(latest_event_team_id)) AS status_event_team_id
FROM (
    SELECT
        *,
        -- The team the latest transition reported, on every bucket row, so an aggregate above can
        -- filter on it (ClickHouse does not allow an aggregate inside another aggregate). The
        -- tenant is the tie-breaker so the selection is deterministic.
        argMax(
            coalesce(event_team_id, ''), tuple(last_timestamp, coalesce(event_team_id, ''))
        ) OVER (PARTITION BY report_id) AS latest_event_team_id
    FROM (
    SELECT
        min(events.timestamp) AS first_timestamp,
        max(events.timestamp) AS last_timestamp,
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
        -- Latest event in the bucket rather than any(): identical for the duplicate deliveries this
        -- grouping targets, and the one that matches last_timestamp when it collapsed real repeats.
        -- Named apart from the outer alias: ClickHouse resolves a bare `dismissal_reason` in the outer
        -- aggregates to the outer alias, which is itself an aggregate.
        nullIf(argMax(toString(properties.dismissal_reason), events.timestamp), '') AS bucket_dismissal_reason,
        max(toString(properties.dismissal_reason) IN ("""
    + _WRONG_DISMISSAL_REASONS_SQL
    + """)) AS bucket_wrong_dismissal,
        nullIf(argMax(toString(properties.priority), events.timestamp), '') AS event_priority,
        nullIf(argMax(toString(properties.actionability), events.timestamp), '') AS event_actionability,
        nullIf(toString(properties.team_id), '') AS event_team_id
    FROM events
    WHERE event = 'signal_report_status_changed'
      AND events.timestamp >= toDateTime({labels_epoch}) AND events.timestamp < toDateTime({snapshot_end})
      AND toString(properties.report_id) != ''
    -- The tenant is part of the bucket key: an event naming another team never shares a bucket
    -- with the genuine transition it collides with, so its reason cannot be counted under the
    -- genuine event's team.
    GROUP BY
        report_id,
        previous_status,
        status,
        event_team_id,
        toStartOfInterval(events.timestamp, INTERVAL 10 MINUTE)
    )
)
GROUP BY report_id
"""
)

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

FEEDBACK_COLUMNS = (
    "feedback_positive_count",
    "feedback_negative_count",
    "first_feedback_at",
    "latest_feedback_sentiment",
)
# The thumbs at the end of a report body. Feedback-only (the report stays in the inbox), so it is
# not recoverable from the action or status streams. Only the rating event is aggregated; the
# optional `Inbox report feedback note` rides separately and carries no additional label.
FEEDBACK_SQL = f"""
SELECT
    toString(properties.report_id) AS report_id,
    countIf(toString(properties.sentiment) = 'positive') AS feedback_positive_count,
    countIf(toString(properties.sentiment) = 'negative') AS feedback_negative_count,
    min(timestamp) AS first_feedback_at,
    argMax(toString(properties.sentiment), timestamp) AS latest_feedback_sentiment
FROM events
WHERE event = 'Inbox report feedback'
  AND {FEEDBACK_SENTIMENTS_SQL}
  AND timestamp >= toDateTime({{labels_epoch}}) AND timestamp < toDateTime({{snapshot_end}})
  AND toString(properties.report_id) != ''
GROUP BY report_id
"""

REFUNDS_COLUMNS = (
    "refund_count",
    "first_refunded_at",
    "refund_reason",
    "refund_billing_path",
    "refund_credits",
)
# The refund action is the strongest explicit negative PR-quality label: a human reviewed the
# implementation PR and asked for the charge back. It is deliberately its own stream because the
# status stream cannot recover it: a refunded merged-PR report stays `resolved` (see the refund
# guard in products/signals/backend/views.py), so `dismissal_reason='refunded'` misses those.
# The endpoint mints one refund per report ever and repeat calls do not re-emit, so uniq over
# refund_id keeps the count honest under at-least-once analytics delivery.
REFUNDS_SQL = """
SELECT
    toString(properties.report_id) AS report_id,
    uniq(toString(properties.refund_id)) AS refund_count,
    min(timestamp) AS first_refunded_at,
    nullIf(argMax(toString(properties.reason), timestamp), '') AS refund_reason,
    nullIf(argMax(toString(properties.billing_path), timestamp), '') AS refund_billing_path,
    argMax(toInt(properties.credits), timestamp) AS refund_credits
FROM events
WHERE event = 'signals_pr_refund_created'
  AND timestamp >= toDateTime({labels_epoch}) AND timestamp < toDateTime({snapshot_end})
  AND toString(properties.report_id) != ''
GROUP BY report_id
"""

LABEL_STREAMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("impressions", IMPRESSIONS_SQL, IMPRESSIONS_COLUMNS),
    ("opens", OPENS_SQL, OPENS_COLUMNS),
    ("actions", ACTIONS_SQL, ACTIONS_COLUMNS),
    ("feedback", FEEDBACK_SQL, FEEDBACK_COLUMNS),
    ("status_changes", STATUS_SQL, STATUS_COLUMNS),
    ("pr_events", PR_EVENTS_SQL, PR_COLUMNS),
    ("refunds", REFUNDS_SQL, REFUNDS_COLUMNS),
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
    "feedback_positive_count": 0,
    "feedback_negative_count": 0,
    "first_feedback_at": None,
    "latest_feedback_sentiment": None,
    "first_resolved_at": None,
    "first_dismissed_server_at": None,
    "first_failed_at": None,
    "first_snoozed_at": None,
    "latest_status_event": None,
    "latest_status_event_at": None,
    "dismissal_reason": None,
    "wrong_dismissal_count": 0,
    "status_event_priority": None,
    "status_event_actionability": None,
    "status_event_team_id": None,
    "pr_created_count": 0,
    "first_pr_created_at": None,
    "pr_merged_count": 0,
    "first_pr_merged_at": None,
    "pr_closed_count": 0,
    "refund_count": 0,
    "first_refunded_at": None,
    "refund_reason": None,
    "refund_billing_path": None,
    "refund_credits": None,
    "reviewer_add_count": 0,
    "first_reviewer_added_at": None,
    "reviewer_remove_count": 0,
    "first_reviewer_removed_at": None,
}

_TIMESTAMP_LABEL_COLUMNS = frozenset(name for name in LABEL_DEFAULTS if name.endswith("_at"))


def canonical_stream_rows(rows: list[tuple[Any, ...]]) -> dict[str, tuple[Any, ...]]:
    """One row per canonical report id, dropping ids that cannot be report UUIDs.

    ClickHouse groups on the raw client-supplied id, so spelling variants of one UUID arrive as
    separate rows that canonicalize onto the same report. The canonically spelled row wins, so a
    forged alias can never overwrite a real report's aggregates; between aliases the smallest raw
    id wins, so the choice does not depend on ClickHouse's row order."""
    best: dict[str, tuple[tuple[bool, str], tuple[Any, ...]]] = {}
    for row in rows:
        raw_id = str(row[0])
        report_id = canonical_report_uuid(raw_id)
        if report_id is None:
            continue
        rank = (raw_id != report_id, raw_id)
        current = best.get(report_id)
        if current is None or rank < current[0]:
            best[report_id] = (rank, row)
    return {report_id: row for report_id, (_rank, row) in best.items()}


def merge_label_streams(
    stream_rows: dict[str, list[tuple[Any, ...]]], snapshot_date: datetime.date
) -> list[dict[str, Any]]:
    """Merge the per-stream aggregates (each row `(report_id, *stream_columns)`) into one labels
    row per report, filling unseen streams with LABEL_DEFAULTS. Report ids are canonicalized and
    rows with impossible ids dropped, so forged or malformed client events cannot mint label-only
    training rows."""
    merged: dict[str, dict[str, Any]] = {}
    columns_by_stream = {name: columns for name, _, columns in LABEL_STREAMS}
    for stream_name, rows in stream_rows.items():
        columns = columns_by_stream[stream_name]
        for report_id, row in canonical_stream_rows(rows).items():
            entry = merged.setdefault(
                report_id,
                {"snapshot_date": snapshot_date, "report_id": report_id, **LABEL_DEFAULTS},
            )
            for column, value in zip(columns, row[1:], strict=True):
                entry[column] = ensure_utc(value) if column in _TIMESTAMP_LABEL_COLUMNS else value
    return list(merged.values())
