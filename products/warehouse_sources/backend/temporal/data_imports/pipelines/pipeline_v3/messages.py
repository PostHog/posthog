import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)

SyncTypeLiteral = Literal["full_refresh", "incremental", "append", "cdc"]


@frozen
class ReplaceScopeRef:
    """Where the loader finds a run's replace scope (see `ReplaceScope`).

    The value sets can hold every file of a bucket, so they travel in a manifest file next to the
    run's batches. Only the manifest's path and the column name go into each queue row.
    """

    column: str
    manifest_path: str

    def to_dict(self) -> dict[str, str]:
        return {"column": self.column, "manifest_path": self.manifest_path}

    @classmethod
    def from_dict(cls, raw: object) -> "ReplaceScopeRef | None":
        if not isinstance(raw, dict):
            return None
        column, manifest_path = raw.get("column"), raw.get("manifest_path")
        if not isinstance(column, str) or not isinstance(manifest_path, str):
            return None
        return cls(column=column, manifest_path=manifest_path)


@dataclass(frozen=True)
class ExportSignalMessage:
    """One extracted batch's hand-off from the extraction side to the load consumer.

    Produced per batch by `postgres_queue.producer` (and the CDC extraction activities) and
    consumed by `load.processor`. The schema predates the Postgres load queue — it was the
    v3 Kafka transport's message format — which is why the queue bridge converts a
    `PendingBatch` into this shape rather than the other way around.
    """

    team_id: int
    job_id: str
    schema_id: str
    source_id: str
    resource_name: str
    run_uuid: str
    batch_index: int
    s3_path: str
    row_count: int
    byte_size: int
    is_final_batch: bool
    total_batches: Optional[int]
    total_rows: Optional[int]
    sync_type: SyncTypeLiteral
    data_folder: Optional[str]
    schema_path: Optional[str]
    primary_keys: Optional[list[str]]
    is_resume: bool = False
    timestamp_ns: int = field(default_factory=time.time_ns)
    partition_count: Optional[int] = None
    partition_size: Optional[int] = None
    partition_keys: Optional[list[str]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_mode: Optional[PartitionMode] = None
    is_first_ever_sync: bool = False
    cumulative_row_count: int = 0
    cdc_write_mode: Optional[str] = None
    cdc_table_mode: Optional[str] = None
    # Snapshotted when the run started. Empty means the PostHog warehouse only, which is
    # also what an old message that predates destinations decodes to.
    destination_ids: list[str] = field(default_factory=list)
    # The subset of `destination_ids` a destination writer delivers, so without the warehouse.
    # None on a message queued before the producer recorded it, which readers treat as unknown
    # rather than as none. Resolved once per run, because the consumer reads it per batch.
    external_destination_ids: Optional[list[str]] = None
    replace_scope: Optional[ReplaceScopeRef] = None
    # Jobs that worker restarts stopped and whose cursor this run continues. Their queued batches
    # hold the rows before that cursor, so this run must not complete while one of them is unloaded.
    continued_job_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportSignalMessage":
        return cls(
            team_id=data["team_id"],
            job_id=data["job_id"],
            schema_id=data["schema_id"],
            source_id=data["source_id"],
            resource_name=data["resource_name"],
            run_uuid=data["run_uuid"],
            batch_index=data["batch_index"],
            s3_path=data["s3_path"],
            row_count=data["row_count"],
            byte_size=data["byte_size"],
            is_final_batch=data["is_final_batch"],
            total_batches=data.get("total_batches"),
            total_rows=data.get("total_rows"),
            sync_type=data["sync_type"],
            data_folder=data.get("data_folder"),
            schema_path=data.get("schema_path"),
            primary_keys=data.get("primary_keys"),
            is_resume=data.get("is_resume", False),
            timestamp_ns=data.get("timestamp_ns", time.time_ns()),
            partition_count=data.get("partition_count"),
            partition_size=data.get("partition_size"),
            partition_keys=data.get("partition_keys"),
            partition_format=data.get("partition_format"),
            partition_mode=data.get("partition_mode"),
            is_first_ever_sync=data.get("is_first_ever_sync", False),
            cumulative_row_count=data.get("cumulative_row_count", 0),
            cdc_write_mode=data.get("cdc_write_mode"),
            cdc_table_mode=data.get("cdc_table_mode"),
            destination_ids=data.get("destination_ids") or [],
            external_destination_ids=data.get("external_destination_ids"),
            replace_scope=ReplaceScopeRef.from_dict(data.get("replace_scope")),
            continued_job_ids=list(data.get("continued_job_ids") or []),
        )
