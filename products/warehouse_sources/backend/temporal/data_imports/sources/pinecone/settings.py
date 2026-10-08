from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionMode
    from products.warehouse_sources.backend.types import IncrementalField


BASE_URL = "https://api.pinecone.io"


@frozen
class PineconeEndpoint:
    path: str
    data_selector: str
    primary_key: str
    partition_key: str
    partition_mode: "PartitionMode"
    paginated: bool = False


ENDPOINTS: dict[str, PineconeEndpoint] = {
    "indexes": PineconeEndpoint(
        path="/indexes", data_selector="indexes", primary_key="name", partition_key="name", partition_mode="md5"
    ),
    "collections": PineconeEndpoint(
        path="/collections", data_selector="collections", primary_key="name", partition_key="name", partition_mode="md5"
    ),
    "backups": PineconeEndpoint(
        path="/backups",
        data_selector="data",
        primary_key="backup_id",
        partition_key="created_at",
        partition_mode="datetime",
        paginated=True,
    ),
    "restore_jobs": PineconeEndpoint(
        path="/restore-jobs",
        data_selector="data",
        primary_key="restore_job_id",
        # Pinecone permits a null created_at on restore jobs, so partition by their stable ID.
        partition_key="restore_job_id",
        partition_mode="md5",
        paginated=True,
    ),
}

INCREMENTAL_FIELDS: dict[str, list["IncrementalField"]] = {}
