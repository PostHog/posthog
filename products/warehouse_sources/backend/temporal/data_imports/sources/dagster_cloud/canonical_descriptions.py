from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Timestamp columns are Dagster epoch-seconds floats at the API, normalized to ISO-8601 UTC strings
# on ingest (see dagster_cloud.py:_epoch_to_iso).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "runs": {
        "description": "Historical job/pipeline run records for the deployment, used to compute reliability, DORA, and SLA metrics.",
        "docs_url": "https://docs.dagster.io/api/graphql",
        "columns": {
            "runId": "Unique identifier for the run.",
            "jobName": "Name of the job (pipeline) the run executed.",
            "pipelineName": "Legacy alias for the job name.",
            "status": "Run status (e.g. QUEUED, STARTED, SUCCESS, FAILURE, CANCELED).",
            "mode": "Execution mode the run used.",
            "creationTime": "When the run record was created.",
            "startTime": "When the run started executing.",
            "endTime": "When the run finished executing.",
            "updateTime": "When the run record was last updated (advances as the run's status changes).",
            "tags": "Key/value tags attached to the run.",
            "repositoryOrigin": "The code location and repository the run originated from.",
            "assetSelection": "Asset keys the run targeted, each as a path list.",
        },
    },
    "backfills": {
        "description": "Partition backfills launched in the deployment, including asset backfills.",
        "docs_url": "https://docs.dagster.io/api/graphql",
        "columns": {
            "id": "Unique identifier for the backfill.",
            "status": "Bulk-action status of the backfill (e.g. REQUESTED, COMPLETED, FAILED, CANCELED).",
            "timestamp": "When the backfill was created.",
            "endTimestamp": "When the backfill finished, if it has.",
            "numPartitions": "Number of partitions targeted by the backfill.",
            "partitionSetName": "Name of the partition set the backfill ran against.",
            "jobName": "Name of the job the backfill executed, if any.",
            "isAssetBackfill": "Whether this is an asset backfill rather than a job backfill.",
            "title": "User-provided title for the backfill.",
            "description": "User-provided description for the backfill.",
            "user": "User who launched the backfill.",
        },
    },
    "assets": {
        "description": "Catalog of assets known to the deployment.",
        "docs_url": "https://docs.dagster.io/api/graphql",
        "columns": {
            "id": "Unique identifier for the asset (its serialized asset key).",
            "key": "The asset key as a path list.",
        },
    },
}
