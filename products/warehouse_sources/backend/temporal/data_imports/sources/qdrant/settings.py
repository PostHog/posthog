from datetime import timedelta

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.cloud.qdrant.io"
API_VERSION = "v1"
PAGE_SIZE = 100

ACCOUNTS_PATH = "/api/account/v1/accounts"
CLUSTERS_PATH = "/api/cluster/v1/accounts/{account_id}/clusters"
CLOUD_PROVIDERS_PATH = "/api/platform/v1/accounts/{account_id}/cloud-providers"
MONTHLY_METERINGS_PATH = "/api/metering/v1/accounts/{account_id}/meterings"

# The usage metrics API defaults to the last hour. Full refreshes and long-paused incremental
# syncs read at most this far back.
USAGE_METRICS_LOOKBACK = timedelta(days=7)
# Incremental syncs re-read this much before the watermark, for points Qdrant records late.
USAGE_METRICS_OVERLAP = timedelta(hours=1)


@frozen
class QdrantParent:
    name: str
    path: str
    paginated: bool
    # Child path param -> parent row field.
    path_params: dict[str, str]
    # Parent row field -> child row column.
    include: dict[str, str]
    # Child responses that skip one parent instead of failing the table.
    ignored_statuses: tuple[int, ...] = ()


@frozen
class QdrantEndpoint:
    path: str
    paginated: bool = True
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "createdAt"
    parent: QdrantParent | None = None


ENDPOINTS: dict[str, QdrantEndpoint] = {
    "clusters": QdrantEndpoint(path=CLUSTERS_PATH),
    "backups": QdrantEndpoint(path="/api/cluster/backup/v1/accounts/{account_id}/backups"),
    "backup_schedules": QdrantEndpoint(path="/api/cluster/backup/v1/accounts/{account_id}/backup_schedules"),
    "backup_restores": QdrantEndpoint(path="/api/cluster/backup/v1/accounts/{account_id}/backup_restores"),
    "cloud_providers": QdrantEndpoint(path=CLOUD_PROVIDERS_PATH, paginated=False, partition_key=None),
    "cloud_provider_regions": QdrantEndpoint(
        path=CLOUD_PROVIDERS_PATH + "/{cloudProviderId}/regions",
        paginated=False,
        primary_keys=("cloud_provider_id", "id"),
        partition_key=None,
        parent=QdrantParent(
            name="cloud_providers",
            path=CLOUD_PROVIDERS_PATH,
            paginated=False,
            path_params={"cloudProviderId": "id"},
            include={"id": "cloud_provider_id"},
            # The "hybrid" provider needs read:clusters or read:hybrid_cloud_environments; the others need none.
            ignored_statuses=(403,),
        ),
    ),
    "metering_entries": QdrantEndpoint(
        path=MONTHLY_METERINGS_PATH + "/{year}/{month}",
        paginated=False,
        # Metering items carry no id of their own: one row is one billable entity over one window.
        primary_keys=("billableEntityId", "startTime", "endTime"),
        partition_key="startTime",
        parent=QdrantParent(
            name="monthly_meterings",
            path=MONTHLY_METERINGS_PATH,
            paginated=False,
            path_params={"year": "year", "month": "month"},
            include={},
        ),
    ),
    "cluster_usage_metrics": QdrantEndpoint(
        path="/api/monitoring/v1/accounts/{account_id}/cluster/{clusterId}/usage-metrics",
        paginated=False,
        primary_keys=("cluster_id", "node_id", "metric", "timestamp"),
        partition_key="timestamp",
        parent=QdrantParent(
            name="clusters",
            path=CLUSTERS_PATH,
            paginated=True,
            path_params={"clusterId": "id"},
            include={"id": "cluster_id"},
            # A cluster deleted between the listing and its metrics request.
            ignored_statuses=(404,),
        ),
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "cluster_usage_metrics": [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

AUTH_ERROR = "Qdrant rejected the Cloud Management Key. Check the key in Access Management > Cloud Management Keys."
PERMISSION_ERROR = "The Qdrant key lacks permission. Grant read:clusters, read:backups, read:backup_schedules, or read:payment_information for the selected tables."
ACCOUNT_ERROR = "Enter a valid Qdrant account ID from the Cloud Console."
