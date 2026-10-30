"""Project vectors for the mirror region, built in that region.

The mirror region (EU) trains nothing: the training region (US) mirrors its served models there. A
served model can read project vectors, but those are per-team means of report vectors, and each
region's report vectors exist only in its own ClickHouse. So this region builds its own day with the
same `project_vectors()` the training region uses:

    report vectors   this region's ClickHouse, through `report_embeddings_table`
    engagement       the training region's `inbox_engagement_export` in this region's object store

The output lands in this region's object store at `serving_project_vectors_key`, which the served
manifest can name.
"""

import io
import datetime

import dagster
import pyarrow as pa
import pyarrow.parquet as pq

from posthog import settings
from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageClient

from products.signals.backend.ranking.serving_manifest import (
    PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY,
    PROJECT_VECTORS_SCHEMA_VERSION_METADATA_KEY,
    serving_engagement_key,
    serving_project_vectors_key,
)
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE_SUMMARY
from products.signals.dags.inbox_ranking.common import (
    ROW_COUNT_METADATA_KEY,
    SCHEMA_VERSION_METADATA_KEY,
    SNAPSHOT_DATE_METADATA_KEY,
    owner_tags,
    snapshot_bounds,
)
from products.signals.dags.inbox_ranking.consent import training_consent_team_ids
from products.signals.dags.inbox_ranking.dataset.dag import (
    COMMON_ASSET_KWARGS,
    ENGAGEMENT_EXPORT_SCHEMA_VERSION,
    report_embeddings_table,
    tag_dagster_queries,
)
from products.signals.dags.inbox_ranking.dataset.project_vectors import (
    CONTEXT_KINDS,
    ENGAGEMENT_EXPORT_COLUMNS,
    LABEL_COLUMNS,
    PROJECT_VECTORS_SCHEMA_VERSION,
    VECTOR_KINDS,
    project_vectors,
    teams_with_history,
)

MIRROR_PROJECT_VECTORS_ASSET = "inbox_mirror_project_vectors"

# An older export only misses the newest engagement, so a late training-region run costs a little
# history. Past this age the vectors drift too far from what training read, so the asset fails.
ENGAGEMENT_EXPORT_MAX_AGE_DAYS = 2


@frozen
class _ExportShape:
    columns: tuple[str, ...]
    kinds: tuple[str, ...]


# The two regions deploy apart, so this reader also takes the version before the current one. A v1
# export has no `first_fixed_at`, so its day has no `fixed` rows.
_EXPORT_SHAPES: dict[str, _ExportShape] = {
    "1": _ExportShape(columns=LABEL_COLUMNS, kinds=VECTOR_KINDS),
    str(ENGAGEMENT_EXPORT_SCHEMA_VERSION): _ExportShape(columns=ENGAGEMENT_EXPORT_COLUMNS, kinds=CONTEXT_KINDS),
}


@frozen
class EngagementExport:
    export_date: str
    age_days: int
    labels: pa.Table
    # The project vector kinds the labels can build.
    kinds: tuple[str, ...]


def read_engagement_export(
    storage: ObjectStorageClient, bucket: str, prefix: str, partition_key: str
) -> EngagementExport | None:
    """The newest engagement export at or before dt=D and at most `ENGAGEMENT_EXPORT_MAX_AGE_DAYS` old.

    The export is a cumulative snapshot, so an older day is a subset of the newer one. An export with
    another schema version fails rather than feeding columns this reader does not know."""
    partition_day = datetime.date.fromisoformat(partition_key)
    for age_days in range(ENGAGEMENT_EXPORT_MAX_AGE_DAYS + 1):
        export_date = (partition_day - datetime.timedelta(days=age_days)).isoformat()
        key = serving_engagement_key(prefix, export_date)
        head = storage.head_object_strict(bucket, key)
        if head is None:
            continue
        schema_version = head.get("Metadata", {}).get(SCHEMA_VERSION_METADATA_KEY)
        shape = _EXPORT_SHAPES.get(schema_version or "")
        if shape is None:
            raise dagster.Failure(
                f"engagement export {key} has schema version {schema_version}, "
                f"this reader knows {sorted(_EXPORT_SHAPES)}"
            )
        body = storage.read_bytes(bucket, key)
        if body is None:
            continue
        labels = pq.read_table(pa.BufferReader(body), columns=list(shape.columns))
        return EngagementExport(export_date=export_date, age_days=age_days, labels=labels, kinds=shape.kinds)
    return None


@dagster.asset(name=MIRROR_PROJECT_VECTORS_ASSET, **COMMON_ASSET_KWARGS)
def inbox_mirror_project_vectors(context: dagster.AssetExecutionContext) -> None:
    """Per-team context vectors of this region as of the partition end, for a report born on the next day."""
    partition_key = context.partition_key
    _, snapshot_end = snapshot_bounds(partition_key)
    prefix = settings.INBOX_RANKING_DATASET_S3_PREFIX
    bucket = settings.OBJECT_STORAGE_BUCKET
    storage = object_storage.object_storage_client()

    export = read_engagement_export(storage, bucket, prefix, partition_key)
    if export is None:
        raise dagster.Failure(
            f"no engagement export for {partition_key} or the {ENGAGEMENT_EXPORT_MAX_AGE_DAYS} days before it; "
            "check the training region's inbox_engagement_export"
        )
    if export.age_days:
        context.log.warning(
            f"engagement export for {partition_key} is missing; using {export.export_date}, "
            f"so engagement after that day is not in the vectors"
        )

    tag_dagster_queries(context, query_type="inbox_ranking_mirror_report_embeddings")
    # The same consent rule as the training region, decided by this region for its own teams.
    consent_team_ids = training_consent_team_ids()
    embeddings = report_embeddings_table(partition_key, EMBEDDING_RENDERING_TITLE_SUMMARY, consent_team_ids)
    embedding_rows = embeddings.num_rows
    table = project_vectors(export.labels, embeddings, snapshot_end, export.kinds)
    del embeddings

    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd")
    content = buffer.getvalue()
    key = serving_project_vectors_key(prefix, partition_key)
    storage.write(
        bucket=bucket,
        key=key,
        content=content,
        extras={
            "Metadata": {
                ROW_COUNT_METADATA_KEY: str(table.num_rows),
                SNAPSHOT_DATE_METADATA_KEY: partition_key,
                PROJECT_VECTORS_SCHEMA_VERSION_METADATA_KEY: str(PROJECT_VECTORS_SCHEMA_VERSION),
                PROJECT_VECTORS_ENGAGEMENT_DATE_METADATA_KEY: export.export_date,
            }
        },
    )
    context.add_output_metadata(
        {
            "rows": dagster.MetadataValue.int(table.num_rows),
            "teams": dagster.MetadataValue.int(len(set(table.column("team_id").to_pylist()))),
            **{
                f"teams_with_{kind}_history": dagster.MetadataValue.int(count)
                for kind, count in teams_with_history(table, export.kinds).items()
            },
            "embedding_rows": dagster.MetadataValue.int(embedding_rows),
            "engagement_rows": dagster.MetadataValue.int(export.labels.num_rows),
            "engagement_export_date": dagster.MetadataValue.text(export.export_date),
            "engagement_export_age_days": dagster.MetadataValue.int(export.age_days),
            "training_consent_teams": dagster.MetadataValue.int(len(consent_team_ids)),
            "bytes": dagster.MetadataValue.int(len(content)),
            "s3_key": dagster.MetadataValue.text(f"s3://{bucket}/{key}"),
        }
    )


inbox_ranking_mirror_job = dagster.define_asset_job(
    name="inbox_ranking_mirror_job",
    selection=[MIRROR_PROJECT_VECTORS_ASSET],
    tags={
        **owner_tags,
        "dagster/max_runtime": str(60 * 60),
        # The embeddings snapshot holds a 1536-float vector per live report of this region, so the
        # pod's peak memory grows with the inventory, the same as the training region's dataset job.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"memory": "8Gi"},
                    "limits": {"memory": "24Gi"},
                }
            }
        },
    },
)


# After the training region's dataset run, which starts at 02:30 UTC and is capped at two hours, so
# the export of the same day is normally in place.
@dagster.schedule(
    cron_schedule="30 5 * * *",
    job=inbox_ranking_mirror_job,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING
    if settings.CLOUD_DEPLOYMENT == "EU"
    else dagster.DefaultScheduleStatus.STOPPED,
    tags=owner_tags,
)
def inbox_ranking_mirror_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    if not settings.INBOX_RANKING_MIRROR_PROJECT_VECTORS_ENABLED:
        return dagster.SkipReason("INBOX_RANKING_MIRROR_PROJECT_VECTORS_ENABLED is not set")
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    return dagster.RunRequest(partition_key=previous_day.isoformat(), run_key=previous_day.isoformat())
