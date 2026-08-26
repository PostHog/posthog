"""Daily modeling dataset for the Self-driving Inbox report-ranking model.

Five assets on one daily partition, each writing Parquet under the configured S3 prefix:

    inbox_report_state/v1/dt=D/       Postgres spine + report state + tabular features
    inbox_report_embeddings/v1/dt=D/  report_id -> small-1536 vector as of snapshot end
    inbox_report_labels/v1/dt=D/      cumulative label columns from the dogfood project's events
    inbox_report_model_data/v1/dt=D/  materialized join of the three, plus a rewritten latest/
    inbox_signal_embeddings/v1/dt=D/  one row per signal emission during D, for the group-level model

The first four are report grain and feed one table; the fifth is signal grain and is read on its
own, joined to the others by report_id at training time.

Partition dt=D is a full snapshot of the eligible report inventory (promoted or ever-labeled),
with every label aggregate bounded `event_time < D+1 00:00 UTC`. Label columns are cumulative,
so later partitions strictly dominate earlier ones: training reads features from dt=D and labels
from any later partition, choosing the label-maturity window at read time. Late-arriving labels
are never backfilled into old partitions.

Point-in-time caveats, per source:
- labels are fully point-in-time for any past day (explicit event-time bound);
- embeddings are point-in-time within the underlying table's 3-month TTL (inserted_at bound);
- signal embeddings are exact for any past day within that same TTL, which is measured from signal
  event time — a day whose signals have since aged out cannot be rebuilt, and the asset refuses to
  overwrite a partition with fewer rows rather than quietly shrink it;
- report state is current-state-only. A backfilled partition therefore carries *today's* Postgres
  state, flagged by features_observed_at being far after snapshot_date. Only forward-run daily
  partitions are true point-in-time snapshots. This reaches row *inclusion*, not just feature
  values: promoted_at is cleared on suppression and snooze, so a report promoted before the cutoff
  and suppressed after it drops out of the spine unless a label event referenced it in time. A
  spine derived from immutable promotion history (the status telemetry carries promoted_at) is the
  fix, and is a v2 change.
"""

import json
import datetime
from collections.abc import Iterator
from typing import Any, cast

from django.db.models import Q

import dagster
import pyarrow as pa

from posthog import settings
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries
from posthog.dags.common import dagster_tags

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT, EMBEDDING_RENDERING
from products.signals.backend.signal_metadata import (
    SIGNAL_DOCUMENT_PRODUCT,
    SIGNAL_DOCUMENT_RENDERING,
    SIGNAL_DOCUMENT_TYPE,
)
from products.signals.dags.inbox_ranking.common import (
    DATASET_VERSION,
    S3_BUCKET_ENV,
    dataset_bucket,
    dataset_unconfigured,
    ensure_utc,
    latest_is_stale,
    latest_object_key,
    merge_emission_rows,
    object_row_count,
    object_snapshot_date,
    owner_tags,
    partition_def,
    partition_object_key,
    partition_write_allowed,
    read_parquet,
    read_parquet_if_exists,
    s3_client,
    skip_unconfigured,
    snapshot_bounds,
    write_parquet,
)
from products.signals.dags.inbox_ranking.dataset.queries import (
    LABEL_DEFAULTS,
    LABEL_STREAMS,
    LABELED_REPORT_IDS_SQL,
    LABELS_TEAM_ID,
    REPORT_EMBEDDINGS_QUERY_SETTINGS,
    REPORT_EMBEDDINGS_SQL,
    SIGNAL_EMBEDDINGS_QUERY_SETTINGS,
    SIGNAL_EMBEDDINGS_SQL,
    etl_workload,
    hogql_rows,
    labels_team,
    merge_label_streams,
    valid_report_uuids,
)

FEATURE_SCHEMA_VERSION = 3

# Statuses a report can be authored straight into and still be in the inbox (`create_scout_report`
# and `create_custom_agent_ready_report`), which is how a report reaches the spine without a
# promotion. Suppressed and deleted are absent on purpose: authored-then-hidden is not inventory.
BORN_VISIBLE_STATUSES = (
    SignalReport.Status.READY,
    SignalReport.Status.PENDING_INPUT,
    SignalReport.Status.IN_PROGRESS,
    SignalReport.Status.RESOLVED,
)

STATE_TABLE = "inbox_report_state"
EMBEDDINGS_TABLE = "inbox_report_embeddings"
LABELS_TABLE = "inbox_report_labels"
MODEL_DATA_TABLE = "inbox_report_model_data"
SIGNAL_EMBEDDINGS_TABLE = "inbox_signal_embeddings"

COMMON_ASSET_KWARGS: dict[str, Any] = {
    "group_name": "inbox_ranking",
    "partitions_def": partition_def,
    "tags": owner_tags,
    # Transient ClickHouse/S3 blips shouldn't fail the daily partition outright.
    "retry_policy": dagster.RetryPolicy(max_retries=2, delay=60),
    # Step-level, so it also bounds the implicit __ASSET_JOB runs a multi-day UI backfill launches:
    # each partition otherwise starts its own fleet-wide embeddings aggregation with a 20 GiB query
    # budget. The limit itself is a Dagster deployment setting (charts repo), like the duckling
    # backfill keys; this only names the pool it targets.
    "pool": "inbox_ranking_etl",
}


def _tag_dagster_queries(context: dagster.AssetExecutionContext, query_type: str) -> None:
    """Stamp product + feature + dagster run tags into the thread's query tags so every ClickHouse
    query this asset issues (sync_execute and HogQL alike) is attributable in system.query_log.
    Both product and feature are required: sync_execute refuses an untagged query in local dev.
    team_id and query_type are set because sync_execute warns on every call missing either; the
    fleet-wide embedding scans have no single tenant, so they carry the labels team as the owner of
    the dataset they feed (HogQL calls re-tag the team from their own context)."""
    tag_queries(product=Product.SIGNALS, feature=Feature.DATA_MODELING, team_id=LABELS_TEAM_ID, query_type=query_type)
    get_query_tags().with_dagster(dagster_tags(context))


_TIMESTAMP = pa.timestamp("us", tz="UTC")

_STATE_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    ("report_team_id", pa.int64()),
    ("region", pa.string()),
    ("status", pa.string()),
    ("billing_exempt_reason", pa.string()),
    ("report_created_at", _TIMESTAMP),
    ("promoted_at", _TIMESTAMP),
    ("last_run_at", _TIMESTAMP),
    ("pg_updated_at", _TIMESTAMP),
    ("report_age_hours", pa.float32()),
    ("hours_since_promotion", pa.float32()),
    ("signal_count", pa.int32()),
    ("total_weight", pa.float32()),
    ("run_count", pa.int32()),
    ("priority", pa.string()),
    ("actionability", pa.string()),
    ("title_chars", pa.int32()),
    ("summary_chars", pa.int32()),
    ("features_observed_at", _TIMESTAMP),
]
STATE_SCHEMA = pa.schema(_STATE_FIELDS)

_EMBEDDING_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    ("report_team_id", pa.int64()),
    ("embedding_small", pa.list_(pa.float32())),
    ("embedding_inserted_at", _TIMESTAMP),
    ("embedding_rendering", pa.string()),
    ("is_tombstone", pa.bool_()),
]
EMBEDDINGS_SCHEMA = pa.schema(_EMBEDDING_FIELDS)

_SIGNAL_EMBEDDING_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("signal_id", pa.string()),
    ("team_id", pa.int64()),
    ("report_id", pa.string()),
    ("signal_timestamp", _TIMESTAMP),
    ("embedding_inserted_at", _TIMESTAMP),
    ("embedding_small", pa.list_(pa.float32())),
    ("embedding_rendering", pa.string()),
    ("weight", pa.float32()),
    ("source_product", pa.string()),
    ("source_type", pa.string()),
    ("source_id", pa.string()),
    ("is_deleted", pa.bool_()),
    ("match_kind", pa.string()),
    ("match_parent_signal_id", pa.string()),
    ("rejected_signal_count", pa.int32()),
]
SIGNAL_EMBEDDINGS_SCHEMA = pa.schema(_SIGNAL_EMBEDDING_FIELDS)

# What makes one emission distinct from another, so a re-run can tell a row it already archived from
# a genuinely new one. embedding_inserted_at is the version: the source keys a signal by
# (team_id, document_id) and distinguishes its versions by inserted_at.
SIGNAL_EMISSION_KEY = ("team_id", "signal_id", "embedding_inserted_at")

LABEL_FIELDS: list[tuple[str, pa.DataType]] = [
    ("first_impressed_at", _TIMESTAMP),
    ("impression_unit_count", pa.int32()),
    ("impressed_user_count", pa.int32()),
    ("first_impression_rank", pa.int32()),
    ("best_impression_rank", pa.int32()),
    ("source_products", pa.list_(pa.string())),
    ("first_opened_at", _TIMESTAMP),
    ("open_count", pa.int32()),
    ("opened_user_count", pa.int32()),
    ("ui_dismiss_count", pa.int32()),
    ("first_ui_dismissed_at", _TIMESTAMP),
    ("create_pr_click_count", pa.int32()),
    ("first_create_pr_clicked_at", _TIMESTAMP),
    ("discuss_count", pa.int32()),
    ("snooze_count", pa.int32()),
    ("feedback_positive_count", pa.int32()),
    ("feedback_negative_count", pa.int32()),
    ("first_feedback_at", _TIMESTAMP),
    ("latest_feedback_sentiment", pa.string()),
    ("first_resolved_at", _TIMESTAMP),
    ("first_dismissed_server_at", _TIMESTAMP),
    ("first_failed_at", _TIMESTAMP),
    ("first_snoozed_at", _TIMESTAMP),
    ("latest_status_event", pa.string()),
    ("latest_status_event_at", _TIMESTAMP),
    ("dismissal_reason", pa.string()),
    ("status_event_priority", pa.string()),
    ("status_event_actionability", pa.string()),
    ("status_event_team_id", pa.int64()),
    ("pr_created_count", pa.int32()),
    ("first_pr_created_at", _TIMESTAMP),
    ("pr_merged_count", pa.int32()),
    ("first_pr_merged_at", _TIMESTAMP),
    ("pr_closed_count", pa.int32()),
    ("refund_count", pa.int32()),
    ("first_refunded_at", _TIMESTAMP),
    ("refund_reason", pa.string()),
    ("refund_billing_path", pa.string()),
    ("refund_credits", pa.int64()),
    ("reviewer_add_count", pa.int32()),
    ("first_reviewer_added_at", _TIMESTAMP),
    ("reviewer_remove_count", pa.int32()),
    ("first_reviewer_removed_at", _TIMESTAMP),
]

_LABELS_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    *LABEL_FIELDS,
]
LABELS_SCHEMA = pa.schema(_LABELS_FIELDS)

_MODEL_DATA_FIELDS: list[tuple[str, pa.DataType]] = [
    ("snapshot_date", pa.date32()),
    ("report_id", pa.string()),
    ("report_team_id", pa.int64()),
    ("region", pa.string()),
    ("dataset_version", pa.string()),
    ("feature_schema_version", pa.int32()),
    ("built_at", _TIMESTAMP),
    ("run_id", pa.string()),
    ("features_observed_at", _TIMESTAMP),
    ("status", pa.string()),
    ("billing_exempt_reason", pa.string()),
    ("report_created_at", _TIMESTAMP),
    ("promoted_at", _TIMESTAMP),
    ("last_run_at", _TIMESTAMP),
    ("pg_updated_at", _TIMESTAMP),
    ("report_age_hours", pa.float32()),
    ("hours_since_promotion", pa.float32()),
    ("signal_count", pa.int32()),
    ("total_weight", pa.float32()),
    ("run_count", pa.int32()),
    ("priority", pa.string()),
    ("actionability", pa.string()),
    ("title_chars", pa.int32()),
    ("summary_chars", pa.int32()),
    ("embedding_small", pa.list_(pa.float32())),
    ("embedding_inserted_at", _TIMESTAMP),
    ("embedding_rendering", pa.string()),
    ("has_embedding", pa.bool_()),
    *LABEL_FIELDS,
    ("label_provenance_ok", pa.bool_()),
    ("impressions_cloud_only", pa.bool_()),
]
MODEL_DATA_SCHEMA = pa.schema(_MODEL_DATA_FIELDS)

_STATE_PASSTHROUGH_COLUMNS = (
    "report_team_id",
    "region",
    "features_observed_at",
    "status",
    "billing_exempt_reason",
    "report_created_at",
    "promoted_at",
    "last_run_at",
    "pg_updated_at",
    "report_age_hours",
    "hours_since_promotion",
    "signal_count",
    "total_weight",
    "run_count",
    "priority",
    "actionability",
    "title_chars",
    "summary_chars",
)


# Stay far below Postgres's 65,535 bind-parameter cap when expanding id__in filters.
_ORM_ID_CHUNK = 10_000


def _chunked(ids: list[str]) -> Iterator[list[str]]:
    for offset in range(0, len(ids), _ORM_ID_CHUNK):
        yield ids[offset : offset + _ORM_ID_CHUNK]


def _judgment_value(parsed: dict[str, Any], key: str) -> str | None:
    # Legacy artefact content is unconstrained JSON; a non-string value must not reach the
    # pa.string() column, where it would abort the whole partition build.
    value = parsed.get(key)
    return value if isinstance(value, str) else None


def _artefact_judgments(report_ids: list[str], snapshot_end: datetime.datetime) -> dict[str, dict[str, str | None]]:
    """Latest priority/actionability judgment per report as of the snapshot cutoff, parsed from
    the artefact content JSON.

    Artefacts are appended in normal operation but the API permits editing one in place
    (`update_content` rewrites content and bumps updated_at, leaving created_at alone), so a row's
    current content is not necessarily what it held at the cutoff. The latest pre-cutoff row is
    therefore chosen first and then nulled if it was edited afterwards: skipping edited rows during
    selection instead would hand back the judgment they superseded, which was already stale at the
    cutoff — silently wrong where null is merely unknown. The genuinely immutable classification is
    status_event_priority/actionability, snapshotted onto each transition in the label stream."""
    judgments: dict[str, dict[str, str | None]] = {}
    for chunk in _chunked(report_ids):
        artefacts = (
            SignalReportArtefact.objects.filter(
                report_id__in=chunk,
                type__in=[
                    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                ],
                created_at__lt=snapshot_end,
            )
            .order_by("report_id", "type", "-created_at")
            .distinct("report_id", "type")
            .values_list("report_id", "type", "content", "updated_at")
        )
        for report_id, artefact_type, content, updated_at in artefacts.iterator(chunk_size=2000):
            # A null updated_at is a row predating the field, never an edit.
            if updated_at is not None and updated_at >= snapshot_end:
                continue
            try:
                parsed = json.loads(content)
            except ValueError:
                continue
            # Legacy artefact rows can hold JSON that is not an object; readers tolerate them.
            if not isinstance(parsed, dict):
                continue
            entry = judgments.setdefault(str(report_id), {"priority": None, "actionability": None})
            if artefact_type == SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT:
                entry["priority"] = _judgment_value(parsed, "priority")
            else:
                entry["actionability"] = _judgment_value(parsed, "actionability")
    return judgments


def spine_report_filter(snapshot_end: datetime.datetime) -> Q:
    """Reports that were in the inbox before the cutoff.

    Two ways in, because not every visible report was promoted: the pipeline promotes a `potential`
    report and stamps promoted_at, but the scout and custom-agent authoring paths create a report
    already in a visible status and never stamp it. Keying only on promotion dropped every
    directly-authored report until a user happened to interact with it, biasing the inventory toward
    reports that already had engagement — the wrong bias for a ranking model. A never-promoted report
    is only eligible while it is still visible, so a promotion after the cutoff (promoted_at set, not
    null) still cannot leak in through the second branch."""
    return Q(promoted_at__isnull=False, promoted_at__lt=snapshot_end) | Q(
        promoted_at__isnull=True, status__in=BORN_VISIBLE_STATUSES, created_at__lt=snapshot_end
    )


@dagster.asset(name=STATE_TABLE, **COMMON_ASSET_KWARGS)
def inbox_report_state(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    _tag_dagster_queries(context, query_type="inbox_ranking_report_state")
    partition_key = context.partition_key
    _, snapshot_end = snapshot_bounds(partition_key)
    snapshot_date = datetime.date.fromisoformat(partition_key)
    features_observed_at = datetime.datetime.now(datetime.UTC)

    labeled_rows = hogql_rows(
        LABELED_REPORT_IDS_SQL,
        team=labels_team(),
        query_type="inbox_ranking_labeled_report_ids",
        snapshot_end=snapshot_end,
    )
    labeled_ids = valid_report_uuids({row[0] for row in labeled_rows})

    # Spine: reports in the inbox before the cutoff, plus anything a label stream referenced before
    # it, so raw `potential` noise and reports that appeared after the cutoff stay out. Labeled ids
    # missing from Postgres (EU reports, hard-deleted rows) still get a model_data row downstream
    # via the labels asset.
    spine_ids: set[str] = {
        str(report_id)
        for report_id in SignalReport.objects.filter(spine_report_filter(snapshot_end)).values_list("id", flat=True)
    }
    for chunk in _chunked(sorted(labeled_ids)):
        spine_ids |= {
            str(report_id)
            for report_id in SignalReport.objects.filter(id__in=chunk, created_at__lt=snapshot_end).values_list(
                "id", flat=True
            )
        }
    ordered_spine_ids = sorted(spine_ids)
    judgments = _artefact_judgments(ordered_spine_ids, snapshot_end)

    rows: list[dict[str, Any]] = []
    for spine_chunk in _chunked(ordered_spine_ids):
        for report in (
            SignalReport.objects.filter(id__in=spine_chunk)
            .values(
                "id",
                "team_id",
                "status",
                "billing_exempt_reason",
                "created_at",
                "promoted_at",
                "last_run_at",
                "updated_at",
                "signal_count",
                "total_weight",
                "run_count",
                "title",
                "summary",
            )
            .iterator(chunk_size=2000)
        ):
            report_id = str(report["id"])
            created_at = ensure_utc(report["created_at"])
            promoted_at = ensure_utc(report["promoted_at"])
            judgment = judgments.get(report_id, {})
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "report_id": report_id,
                    "report_team_id": report["team_id"],
                    "region": (settings.CLOUD_DEPLOYMENT or "local").lower(),
                    "status": report["status"],
                    "billing_exempt_reason": report["billing_exempt_reason"],
                    "report_created_at": created_at,
                    "promoted_at": promoted_at,
                    "last_run_at": ensure_utc(report["last_run_at"]),
                    "pg_updated_at": ensure_utc(report["updated_at"]),
                    "report_age_hours": (snapshot_end - created_at).total_seconds() / 3600 if created_at else None,
                    "hours_since_promotion": (snapshot_end - promoted_at).total_seconds() / 3600
                    if promoted_at
                    else None,
                    "signal_count": report["signal_count"],
                    "total_weight": report["total_weight"],
                    "run_count": report["run_count"],
                    "priority": judgment.get("priority"),
                    "actionability": judgment.get("actionability"),
                    "title_chars": len(report["title"] or ""),
                    "summary_chars": len(report["summary"] or ""),
                    "features_observed_at": features_observed_at,
                }
            )

    bucket = dataset_bucket()
    key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, STATE_TABLE, partition_key)
    write_parquet(s3_client(), bucket, key, pa.Table.from_pylist(rows, schema=STATE_SCHEMA))
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(rows)),
            "labeled_report_ids": dagster.MetadataValue.int(len(labeled_ids)),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


@dagster.asset(name=EMBEDDINGS_TABLE, **COMMON_ASSET_KWARGS)
def inbox_report_embeddings(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    _tag_dagster_queries(context, query_type="inbox_ranking_report_embeddings")
    partition_key = context.partition_key
    _, snapshot_end = snapshot_bounds(partition_key)
    snapshot_date = datetime.date.fromisoformat(partition_key)

    results = cast(
        list[tuple[Any, ...]],
        sync_execute(
            REPORT_EMBEDDINGS_SQL,
            {
                "product": EMBEDDING_PRODUCT,
                "document_type": EMBEDDING_DOCUMENT_TYPE,
                "rendering": EMBEDDING_RENDERING,
                "snapshot_end": snapshot_end.replace(tzinfo=None),
            },
            settings=REPORT_EMBEDDINGS_QUERY_SETTINGS,
            workload=etl_workload(),
        )
        or [],
    )

    # Consumed column-wise straight into Arrow, and each source row is released as it is converted.
    # This is the widest thing the dag holds — a 1536-float vector per live report, fleet-wide — so
    # the intermediate list of row dicts that from_pylist would need is a whole extra copy of it.
    row_count = len(results)
    tombstones = 0
    report_ids: list[str] = []
    team_ids: list[int] = []
    embeddings: list[list[float] | None] = []
    inserted_ats: list[datetime.datetime | None] = []
    tombstone_flags: list[bool] = []
    for index in range(row_count):
        team_id, document_id, embedding, is_tombstone, inserted_at = results[index]
        results[index] = ()
        if is_tombstone:
            tombstones += 1
        report_ids.append(str(document_id))
        team_ids.append(int(team_id))
        # Tombstoned vectors embed the fixed retraction text, not report content, so they are
        # useless as features; keep the row for lineage but null the vector.
        embeddings.append(None if is_tombstone else list(embedding))
        inserted_ats.append(ensure_utc(inserted_at))
        tombstone_flags.append(bool(is_tombstone))
    del results

    table = pa.Table.from_pydict(
        {
            "snapshot_date": [snapshot_date] * row_count,
            "report_id": report_ids,
            "report_team_id": team_ids,
            "embedding_small": embeddings,
            "embedding_inserted_at": inserted_ats,
            "embedding_rendering": [EMBEDDING_RENDERING] * row_count,
            "is_tombstone": tombstone_flags,
        },
        schema=EMBEDDINGS_SCHEMA,
    )

    bucket = dataset_bucket()
    key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, EMBEDDINGS_TABLE, partition_key)
    write_parquet(s3_client(), bucket, key, table)
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(row_count),
            "tombstones": dagster.MetadataValue.int(tombstones),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


@dagster.asset(name=SIGNAL_EMBEDDINGS_TABLE, **COMMON_ASSET_KWARGS)
def inbox_signal_embeddings(context: dagster.AssetExecutionContext) -> None:
    """One row per signal emission in the partition day, for the group-level model.

    This asset is an emission log, not a snapshot, and is the one table in this dag whose partitions
    do not each hold the full inventory: dt=D carries only what was inserted during D. Training
    reads the union of partitions and takes the latest row per (team_id, signal_id) at or before its
    cutoff, the same argMax the other assets do in SQL, moved to read time. The tenant key is part of
    the identity because signal_id is a caller-supplied document_id that is only unique within a team.
    Snapshotting instead would copy a
    1536-float vector per signal fleet-wide every day, which is several GB daily against tens of MB
    for a day's emissions.

    Writing the day's emissions down also outlives the source table's 3-month TTL, which is measured
    from signal event time. That makes this dag the durable store for signal vectors: whatever is not
    captured before a signal ages out is unrecoverable. A re-run is therefore additive rather than a
    replacement — it unions the fresh scan into what the partition already holds, so a row the source
    can no longer supply survives.

    The log is best-effort, and deliberately so. The source is a ReplacingMergeTree versioned by
    inserted_at, and a retraction re-emits the signal under the same sort key, so a merge between the
    two writes keeps only the retraction. A signal whose report is deleted in the same window it was
    inserted therefore reaches no partition in its live form, and no query shape recovers it, since
    the merge has already dropped the row. The reverse gap is the TTL: a retraction inherits the
    original event timestamp, so retracting a signal more than three months old writes a row that is
    already expired and may never be scanned. Absence of an is_deleted row is not proof a signal is
    live. Closing either gap needs an append-only source or a changed emission contract, both out of
    this asset's scope.
    """
    if skip_unconfigured(context):
        return
    _tag_dagster_queries(context, query_type="inbox_ranking_signal_embeddings")
    partition_key = context.partition_key
    window_start, window_end = snapshot_bounds(partition_key)
    snapshot_date = datetime.date.fromisoformat(partition_key)

    results = cast(
        list[tuple[Any, ...]],
        sync_execute(
            SIGNAL_EMBEDDINGS_SQL,
            {
                "product": SIGNAL_DOCUMENT_PRODUCT,
                "document_type": SIGNAL_DOCUMENT_TYPE,
                "rendering": SIGNAL_DOCUMENT_RENDERING,
                "window_start": window_start.replace(tzinfo=None),
                "window_end": window_end.replace(tzinfo=None),
            },
            settings=SIGNAL_EMBEDDINGS_QUERY_SETTINGS,
            workload=etl_workload(),
        )
        or [],
    )

    # Column-wise into Arrow, releasing each source row as it is converted, for the same reason the
    # report embeddings asset does it: the vectors are the widest thing this dag holds.
    row_count = len(results)
    deleted_count = 0
    columns: dict[str, list[Any]] = {name: [] for name, _type in _SIGNAL_EMBEDDING_FIELDS}
    for index in range(row_count):
        (
            team_id,
            signal_id,
            report_id,
            timestamp,
            inserted_at,
            embedding,
            weight,
            source_product,
            source_type,
            source_id,
            is_deleted,
            match_kind,
            match_parent_signal_id,
            rejected_signal_count,
        ) = results[index]
        results[index] = ()
        if is_deleted:
            deleted_count += 1
        columns["snapshot_date"].append(snapshot_date)
        columns["signal_id"].append(str(signal_id))
        columns["team_id"].append(int(team_id))
        columns["report_id"].append(report_id)
        columns["signal_timestamp"].append(ensure_utc(timestamp))
        columns["embedding_inserted_at"].append(ensure_utc(inserted_at))
        # A retracted signal is re-emitted with its original text, unlike a report tombstone, so its
        # vector is real content that we have been told to stop showing. A partition written while it
        # was live keeps it; this one records the retraction without carrying the content forward.
        # Whether such a partition exists depends on merge timing — see the docstring's best-effort note.
        columns["embedding_small"].append(None if is_deleted else list(embedding))
        columns["embedding_rendering"].append(SIGNAL_DOCUMENT_RENDERING)
        columns["weight"].append(weight)
        columns["source_product"].append(source_product)
        columns["source_type"].append(source_type)
        columns["source_id"].append(source_id)
        columns["is_deleted"].append(bool(is_deleted))
        columns["match_kind"].append(match_kind)
        columns["match_parent_signal_id"].append(match_parent_signal_id)
        columns["rejected_signal_count"].append(rejected_signal_count)
    del results

    table = pa.Table.from_pydict(columns, schema=SIGNAL_EMBEDDINGS_SCHEMA)

    bucket = dataset_bucket()
    key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, SIGNAL_EMBEDDINGS_TABLE, partition_key)
    client = s3_client()
    # A re-run is additive. The source can no longer supply a row this partition already archived —
    # a merge or the TTL removed it — so overwriting with the fresh scan alone would delete history
    # that exists nowhere else. Row counts cannot police that on their own: a scan can lose one
    # emission and gain another and land on the same total.
    existing = read_parquet_if_exists(client, bucket, key)
    if existing is not None:
        table = merge_emission_rows(existing, table, SIGNAL_EMISSION_KEY)
    existing_row_count = object_row_count(client, bucket, key)
    if not partition_write_allowed(existing_row_count, table.num_rows):
        raise dagster.Failure(
            f"{SIGNAL_EMBEDDINGS_TABLE} dt={partition_key} already holds {existing_row_count} rows and the union "
            f"with this run produced {table.num_rows}: a union can only grow, so this is a bug in the merge rather "
            "than a source change. Refusing the write to keep archived rows the source may no longer hold."
        )
    write_parquet(client, bucket, key, table)
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(table.num_rows),
            "scanned": dagster.MetadataValue.int(row_count),
            "carried_over": dagster.MetadataValue.int(table.num_rows - row_count),
            "retracted": dagster.MetadataValue.int(deleted_count),
            "reports": dagster.MetadataValue.int(len({report_id for report_id in columns["report_id"] if report_id})),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


@dagster.asset(name=LABELS_TABLE, **COMMON_ASSET_KWARGS)
def inbox_report_labels(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    _tag_dagster_queries(context, query_type="inbox_ranking_labels")
    partition_key = context.partition_key
    _, snapshot_end = snapshot_bounds(partition_key)
    team = labels_team()

    stream_rows: dict[str, list[tuple[Any, ...]]] = {}
    for stream_name, sql, _columns in LABEL_STREAMS:
        stream_rows[stream_name] = hogql_rows(
            sql,
            team=team,
            query_type=f"inbox_ranking_labels_{stream_name}",
            snapshot_end=snapshot_end,
        )
        context.log.info(f"{stream_name}: {len(stream_rows[stream_name])} reports")

    rows = merge_label_streams(stream_rows, datetime.date.fromisoformat(partition_key))
    bucket = dataset_bucket()
    key = partition_object_key(settings.INBOX_RANKING_DATASET_S3_PREFIX, LABELS_TABLE, partition_key)
    write_parquet(s3_client(), bucket, key, pa.Table.from_pylist(rows, schema=LABELS_SCHEMA))
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(rows)),
            **{
                f"{stream_name}_reports": dagster.MetadataValue.int(len(stream_rows[stream_name]))
                for stream_name, _, _ in LABEL_STREAMS
            },
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


def label_provenance_ok(
    pg_status: str | None,
    pg_updated_at: datetime.datetime | None,
    latest_status_event: str | None,
    *,
    report_team_id: int | None,
    status_event_team_id: int | None,
    snapshot_end: datetime.datetime,
) -> bool:
    """Status labels cross-checked against Postgres current state (the label-telemetry PR's
    security-review requirement): the report must exist in Postgres, its status telemetry must be
    about that report's tenant, and its latest status event must either match the current status or
    be explained by the cutoff.

    The only legitimate mismatch is a status that moved after the label window closed — labels are
    bounded at the cutoff, Postgres is read at run time. Any *earlier* write is no excuse: signal
    ingestion bumps `updated_at` without touching status, so accepting one would let stale or forged
    status telemetry pass as soon as the report saw unrelated activity."""
    if pg_status is None:
        return False
    if latest_status_event is None:
        return True
    # The transition reported a tenant; a real emit always carries the report's own. Naming a
    # different team (or no readable team at all) means the event isn't about this report, however
    # well its status happens to line up.
    if report_team_id is None or status_event_team_id != report_team_id:
        return False
    if latest_status_event == pg_status:
        return True
    return pg_updated_at is not None and pg_updated_at >= snapshot_end


def assemble_model_rows(
    state_rows: list[dict[str, Any]],
    embedding_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    *,
    snapshot_date: datetime.date,
    built_at: datetime.datetime,
    run_id: str,
) -> list[dict[str, Any]]:
    """Join the three sub-tables on report_id into the wide training rows.

    The row set is the union of state and labels: label-only rows (EU reports, hard-deleted
    reports) survive with null state so their label history stays real, while embedding-only
    reports (never promoted, never labeled) stay out of the spine.

    A deleted report is indistinguishable from an EU one here — both are label rows with no
    Postgres row — so re-running a partition cannot scrub one. See the README's retention section:
    scrubbing means deleting the objects.
    """
    _, snapshot_end = snapshot_bounds(snapshot_date.isoformat())
    state_by_id = {row["report_id"]: row for row in state_rows}
    embedding_by_id = {row["report_id"]: row for row in embedding_rows}
    labels_by_id = {row["report_id"]: row for row in label_rows}

    rows: list[dict[str, Any]] = []
    for report_id in sorted(set(state_by_id) | set(labels_by_id)):
        state = state_by_id.get(report_id)
        embedding = embedding_by_id.get(report_id)
        labels = labels_by_id.get(report_id)

        row: dict[str, Any] = {
            "snapshot_date": snapshot_date,
            "report_id": report_id,
            "dataset_version": DATASET_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "built_at": built_at,
            "run_id": run_id,
        }
        for column in _STATE_PASSTHROUGH_COLUMNS:
            row[column] = state.get(column) if state else None
        if row["report_team_id"] is None and embedding:
            row["report_team_id"] = embedding["report_team_id"]

        if embedding is not None:
            # Tombstoned rows already carry a null vector in the sub-table.
            row["embedding_small"] = embedding["embedding_small"]
            row["embedding_inserted_at"] = embedding["embedding_inserted_at"]
            row["embedding_rendering"] = embedding["embedding_rendering"]
        else:
            row["embedding_small"] = None
            row["embedding_inserted_at"] = None
            row["embedding_rendering"] = None
        row["has_embedding"] = row["embedding_small"] is not None

        for column in LABEL_DEFAULTS:
            row[column] = labels.get(column, LABEL_DEFAULTS[column]) if labels else LABEL_DEFAULTS[column]

        row["label_provenance_ok"] = label_provenance_ok(
            row["status"],
            row["pg_updated_at"],
            row["latest_status_event"],
            report_team_id=row["report_team_id"],
            status_event_team_id=row["status_event_team_id"],
            snapshot_end=snapshot_end,
        )
        # Desktop Code app does not emit impressions yet, so p(open) negatives are cloud-only;
        # recorded per row so the caveat travels with the data.
        row["impressions_cloud_only"] = True
        rows.append(row)
    return rows


@dagster.asset(
    name=MODEL_DATA_TABLE,
    deps=[STATE_TABLE, EMBEDDINGS_TABLE, LABELS_TABLE],
    **COMMON_ASSET_KWARGS,
)
def inbox_report_model_data(context: dagster.AssetExecutionContext) -> None:
    if skip_unconfigured(context):
        return
    partition_key = context.partition_key
    snapshot_date = datetime.date.fromisoformat(partition_key)
    built_at = datetime.datetime.now(datetime.UTC)
    bucket = dataset_bucket()
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    client = s3_client()

    state_rows = read_parquet(client, bucket, partition_object_key(prefix, STATE_TABLE, partition_key)).to_pylist()
    embedding_rows = read_parquet(
        client, bucket, partition_object_key(prefix, EMBEDDINGS_TABLE, partition_key)
    ).to_pylist()
    label_rows = read_parquet(client, bucket, partition_object_key(prefix, LABELS_TABLE, partition_key)).to_pylist()

    rows = assemble_model_rows(
        state_rows,
        embedding_rows,
        label_rows,
        snapshot_date=snapshot_date,
        built_at=built_at,
        run_id=context.run.run_id,
    )
    table = pa.Table.from_pylist(rows, schema=MODEL_DATA_SCHEMA)

    partition_key_path = partition_object_key(prefix, MODEL_DATA_TABLE, partition_key)
    write_parquet(client, bucket, partition_key_path, table, snapshot_date=partition_key)
    latest_key = latest_object_key(prefix, MODEL_DATA_TABLE)
    wrote_latest = latest_is_stale(object_snapshot_date(client, bucket, latest_key), partition_key)
    if wrote_latest:
        write_parquet(client, bucket, latest_key, table, snapshot_date=partition_key)

    with_state = sum(1 for row in rows if row["status"] is not None)
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(len(rows)),
            "rows_with_state": dagster.MetadataValue.int(with_state),
            "rows_with_embedding": dagster.MetadataValue.int(sum(1 for row in rows if row["has_embedding"])),
            "rows_provenance_ok": dagster.MetadataValue.int(sum(1 for row in rows if row["label_provenance_ok"])),
            "wrote_latest": dagster.MetadataValue.bool(wrote_latest),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{partition_key_path}"),
        }
    )


inbox_ranking_dataset_job = dagster.define_asset_job(
    name="inbox_ranking_dataset_job",
    selection=[STATE_TABLE, EMBEDDINGS_TABLE, SIGNAL_EMBEDDINGS_TABLE, LABELS_TABLE, MODEL_DATA_TABLE],
    partitions_def=partition_def,
    # The seven label streams run sequentially and each may take its full 600s query timeout, so an
    # hour left a slow-but-valid pass no room for the join, the S3 writes, or an asset retry — and
    # the label windows only grow, since they accumulate from LABELS_EPOCH.
    tags={**owner_tags, "dagster/max_runtime": str(3 * 60 * 60)},
)


# On Cloud the assets self-disable while the destination bucket is unset, so the schedule can
# default to RUNNING and the dataset starts flowing the moment infra provisions the bucket.
# Everywhere else (local dev loads this location via workspace.yaml, self-hosted) it stays
# stopped: those environments have no dogfood project, so a running schedule would only produce
# a failed run every day.
@dagster.schedule(
    cron_schedule="30 2 * * *",
    job=inbox_ranking_dataset_job,
    execution_timezone="UTC",
    # Only prod US runs on its own: the dogfood project this dag reads labels from lives there, so
    # a DEV or E2E deployment (also `is_cloud()`) would fail every daily run on the missing team.
    # Those deployments still register the location and can trigger a run by hand.
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "US"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_dataset_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    # Skip rather than launch a run whose assets would all take their early return: a run that
    # materializes every asset without writing an object reads as a healthy partition, and once the
    # bucket lands the schedule has already moved past those dates. Skipped ticks leave the
    # partitions plainly unmaterialized and backfillable.
    if dataset_unconfigured():
        return dagster.SkipReason(f"{S3_BUCKET_ENV} is not set; skipping until the dedicated bucket is provisioned")
    # Derived from the tick rather than wall-clock now() so a delayed or replayed tick still
    # builds the partition it was scheduled for; run_key dedupes a re-evaluated tick.
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=previous_day.isoformat())
