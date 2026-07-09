import sys
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from dateutil import parser
from django_deprecate_fields import deprecate_field

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

type IncrementalFieldValue = str | int | float | None


class ExternalDataSchema(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        FAILED = "Failed", "Failed"
        COMPLETED = "Completed", "Completed"
        BILLING_LIMIT_REACHED = "BillingLimitReached", "BillingLimitReached"
        BILLING_LIMIT_TOO_LOW = "BillingLimitTooLow", "BillingLimitTooLow"

    class SyncType(models.TextChoices):
        FULL_REFRESH = "full_refresh", "full_refresh"
        INCREMENTAL = "incremental", "incremental"
        APPEND = "append", "append"
        WEBHOOK = "webhook", "webhook"
        CDC = "cdc", "cdc"
        XMIN = "xmin", "xmin"

    class SyncFrequency(models.TextChoices):
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"

    name = models.CharField(max_length=400)
    label = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source = models.ForeignKey("warehouse_sources.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE)
    table = models.ForeignKey("warehouse_sources.DataWarehouseTable", on_delete=models.SET_NULL, null=True, blank=True)
    should_sync = models.BooleanField(default=True)
    latest_error = models.TextField(
        null=True, blank=True, help_text="The latest error that occurred when syncing this schema."
    )
    last_error_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this schema's failure was last included in a failure digest email.",
    )
    status = models.CharField(max_length=400, null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_type = models.CharField(max_length=128, choices=SyncType, null=True, blank=True)
    # { "incremental_field": string, "incremental_field_type": string, "incremental_field_last_value": any, "incremental_field_earliest_value": any, "incremental_field_lookback_seconds": int | None, "reset_pipeline": bool, "partitioning_enabled": bool, "partition_count": int, "partition_size": int, "partition_mode": str, "partitioning_keys": list[str], "chunk_size_override": int | None, "primary_key_columns": list[str] | None, "xmin_last_value": int, "xmin_ceiling": int, "xmin_num_wraparound": int, "max_partition_bytes": int, "last_repartition_at": iso8601 str, "repartition_pending": { "partition_mode": str, "partition_format": str | None, "partition_count": int | None, "partition_size": int | None, "partition_keys": list[str], "trigger_reason": str }, "repartition_swap": { "state": "ready", "temp_uri": str, "live_uri": str } }
    sync_type_config = models.JSONField(
        default=dict,
        blank=True,
    )
    # Normalized leaf subdir under the source's S3 folder that Delta data is written to (the actual
    # folder name, e.g. `my_table`, not `My Table`). Pins legacy rows (renamed to qualified form
    # during multi-schema migration) to their original path. Empty for rows written before this
    # column existed — readers fall back to the legacy JSON key, then the normalized schema `name`.
    s3_folder_name = models.CharField(max_length=400, null=True, blank=True)
    # Deprecated in favour of `sync_frequency_interval`
    sync_frequency = deprecate_field(
        models.CharField(max_length=128, choices=SyncFrequency, default=SyncFrequency.DAILY, blank=True)
    )
    sync_frequency_interval = models.DurationField(default=timedelta(hours=6), null=True, blank=True)
    sync_time_of_day = models.TimeField(null=True, blank=True, help_text="Time of day to run the sync (UTC)")
    initial_sync_complete = models.BooleanField(default=False)
    description = models.CharField(max_length=1000, null=True, blank=True)
    # null = sync all columns (default). Non-empty list = exact column projection.
    # PK + active incremental field are always retained server-side regardless of this list.
    enabled_columns = models.JSONField(null=True, blank=True, default=None)
    # null (default) = sync all rows. List of {column, operator, value} predicates ANDed onto the WHERE clause.
    row_filters = models.JSONField(null=True, blank=True, default=None)

    __repr__ = sane_repr("name")

    class Meta:
        db_table = "posthog_externaldataschema"

    def save(self, *args: Any, skip_activity_log: bool = False, **kwargs: Any) -> None:
        # Populate the S3 folder on first write so the column is always authoritative for new rows.
        # Legacy/qualified rows set it explicitly before renaming (see `_qualify_legacy_row`); this
        # only fills it when empty, so an existing folder is never overwritten by a later rename.
        if not self.s3_folder_name and self.name and self.name.strip():
            self.s3_folder_name = NamingConvention.normalize_identifier(self.resolved_s3_folder_name or self.name)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "s3_folder_name"}

        if skip_activity_log:
            # Internal pipeline-driven bookkeeping saves (sync_type_config / xmin state) don't need
            # an audit trail. Bypass ModelActivityMixin.save() so we skip its extra _get_before_update
            # SELECT — that read needs a fresh pooler connection and raises OperationalError when the
            # transaction pooler has dropped the connection mid-sync, failing the import activity.
            super(ModelActivityMixin, self).save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source.source_type}_{str(self.id)}".lower().replace("-", "_")

    @property
    def normalized_name(self):
        return NamingConvention.normalize_identifier(self.name)

    @property
    def is_incremental(self):
        return self.sync_type == self.SyncType.INCREMENTAL

    @property
    def is_append(self):
        return self.sync_type == self.SyncType.APPEND

    @property
    def is_webhook(self):
        return self.sync_type == self.SyncType.WEBHOOK

    @property
    def is_cdc(self):
        return self.sync_type == self.SyncType.CDC

    @property
    def is_xmin(self):
        return self.sync_type == self.SyncType.XMIN

    @property
    def xmin_last_value(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("xmin_last_value", None)
        return None

    @property
    def xmin_ceiling(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("xmin_ceiling", None)
        return None

    @property
    def xmin_num_wraparound(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("xmin_num_wraparound", None)
        return None

    @property
    def cdc_mode(self) -> Literal["snapshot", "streaming"] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_mode")
        return None

    @property
    def cdc_last_log_position(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_last_log_position")
        return None

    @property
    def cdc_table_mode(self) -> Literal["consolidated", "cdc_only", "both"]:
        if self.sync_type_config:
            return self.sync_type_config.get("cdc_table_mode", "consolidated")
        return "consolidated"

    @property
    def should_use_incremental_field(self):
        return self.is_incremental or self.is_append or self.is_webhook

    @property
    def table_row_count_is_cumulative(self) -> bool:
        # These sync types append/merge into the warehouse table across runs, so its true size is the
        # full table count — not the latest run's row_count, which is only that run's delta. Full refresh
        # replaces the whole table, so there the run's row_count already equals the table size.
        return self.should_use_incremental_field or self.is_cdc or self.is_xmin

    @property
    def incremental_field(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field", None)

        return None

    @property
    def incremental_field_type(self) -> IncrementalFieldType | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_type", None)

        return None

    @property
    def incremental_field_last_value(self) -> IncrementalFieldValue:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_last_value", None)

        return None

    @property
    def incremental_field_earliest_value(self) -> IncrementalFieldValue:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_earliest_value", None)

        return None

    @property
    def incremental_field_lookback_seconds(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("incremental_field_lookback_seconds", None)

        return None

    @property
    def reset_pipeline(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("reset_pipeline", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partitioning_enabled(self) -> bool:
        if self.sync_type_config:
            value = self.sync_type_config.get("partitioning_enabled", None)
            if value is None:
                return False

            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True

        return False

    @property
    def partition_count(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count", None)

        return None

    @property
    def partition_size(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size", None)

        return None

    @property
    def partition_count_override(self) -> int | None:
        # Operator-pinned partition_count set via the admin repartition action. Unlike
        # `partition_count` (which is auto-detected and wiped on every reset), this key
        # survives `update_sync_type_config_for_reset_pipeline` so the operator's choice
        # wins the reset resync that the repartition triggers. It is consumed (popped) by
        # `set_partitioning_enabled` once applied, so a later reset re-detects.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_count_override", None)

        return None

    @property
    def partition_size_override(self) -> int | None:
        # Operator-pinned partition_size for numerical mode. Same one-shot semantics as
        # `partition_count_override`.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_size_override", None)

        return None

    @property
    def partition_mode_override(self) -> PartitionMode | None:
        # Operator-pinned partition_mode set via the admin "change partition mode" action.
        # Like `partition_count_override`, it survives `update_sync_type_config_for_reset_pipeline`
        # (which wipes the auto-detected `partition_mode`) so the operator's choice wins the reset
        # resync that the mode change triggers, then is consumed by `set_partitioning_enabled`.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode_override", None)

        return None

    @property
    def partitioning_keys_override(self) -> list[str] | None:
        # Operator-pinned partitioning_keys paired with `partition_mode_override` — e.g. the
        # date/timestamp column to bucket on when switching a table to datetime mode. Same
        # one-shot, reset-surviving semantics as `partition_mode_override`.
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys_override", None)

        return None

    @property
    def partition_mode(self) -> PartitionMode | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partition_mode", None)

        return None

    @property
    def partition_format(self) -> PartitionFormat | None:
        # This key doesn't get reset on pipeline_reset.
        if self.sync_type_config:
            return self.sync_type_config.get("partition_format", None)

        return None

    @property
    def partitioning_keys(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("partitioning_keys", None)

        return None

    @property
    def primary_key_columns(self) -> list[str] | None:
        if self.sync_type_config:
            return self.sync_type_config.get("primary_key_columns", None)

        return None

    @property
    def chunk_size_override(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("chunk_size_override", None)

        return None

    @property
    def schema_metadata(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            metadata = self.sync_type_config.get("schema_metadata")
            if isinstance(metadata, dict):
                return metadata
        return None

    @property
    def resolved_s3_folder_name(self) -> str | None:
        # JSON fallback covers rows written by old workers before the column rollout.
        if self.s3_folder_name:
            return self.s3_folder_name
        legacy_key = (self.sync_type_config or {}).get("dwh_storage_key")
        if isinstance(legacy_key, str) and legacy_key:
            return legacy_key
        return None

    @property
    def foreign_keys(self) -> list[dict[str, str]] | None:
        metadata = self.schema_metadata
        if metadata:
            foreign_keys = metadata.get("foreign_keys")
            if isinstance(foreign_keys, list):
                return foreign_keys
        return None

    def set_partitioning_enabled(
        self,
        partitioning_keys: list[str],
        partition_count: Optional[int],
        partition_size: Optional[int],
        partition_mode: Optional[PartitionMode],
        partition_format: Optional[PartitionFormat],
    ) -> None:
        self.sync_type_config["partitioning_enabled"] = True
        self.sync_type_config["partition_count"] = partition_count
        self.sync_type_config["partition_size"] = partition_size
        self.sync_type_config["partitioning_keys"] = partitioning_keys
        self.sync_type_config["partition_mode"] = partition_mode
        self.sync_type_config["partition_format"] = partition_format
        # Consume any operator-pinned overrides: they've now been baked into the effective
        # settings above, so drop them. This makes the pin one-shot — a later reset falls
        # back to auto-detection instead of re-applying a stale pin (re-pin via the admin
        # repartition action if needed).
        self.sync_type_config.pop("partition_count_override", None)
        self.sync_type_config.pop("partition_size_override", None)
        self.sync_type_config.pop("partition_mode_override", None)
        self.sync_type_config.pop("partitioning_keys_override", None)
        self.save()

    # --- In-place repartition controller state ------------------------------------------------
    # These keys drive the automated, no-source-pull repartition that bounds per-partition memory
    # so incremental merges stop OOMing the worker. Detection records `max_partition_bytes` and (when
    # over budget) a `repartition_pending` target; the next run's pre-extraction activity performs the
    # in-place rewrite, using `repartition_swap` as a crash-safe marker, then stamps `last_repartition_at`.

    @property
    def max_partition_bytes(self) -> int | None:
        if self.sync_type_config:
            return self.sync_type_config.get("max_partition_bytes", None)
        return None

    @property
    def last_repartition_at(self) -> str | None:
        if self.sync_type_config:
            return self.sync_type_config.get("last_repartition_at", None)
        return None

    @property
    def repartition_pending(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            pending = self.sync_type_config.get("repartition_pending", None)
            if isinstance(pending, dict):
                return pending
        return None

    @property
    def repartition_swap(self) -> dict[str, Any] | None:
        if self.sync_type_config:
            swap = self.sync_type_config.get("repartition_swap", None)
            if isinstance(swap, dict):
                return swap
        return None

    def _save_sync_type_config(self) -> None:
        # Internal bookkeeping write — skip the activity-log SELECT (see save()) since these run
        # inside the sync/repartition activity where a dropped pooler connection would fail the run.
        self.save(update_fields=["sync_type_config", "updated_at"], skip_activity_log=True)

    def record_partition_measurement(self, max_partition_bytes: int) -> None:
        self.sync_type_config["max_partition_bytes"] = max_partition_bytes
        self._save_sync_type_config()

    def set_repartition_pending(self, target: dict[str, Any]) -> None:
        self.sync_type_config["repartition_pending"] = target
        self._save_sync_type_config()

    def clear_repartition_pending(self) -> None:
        self.sync_type_config.pop("repartition_pending", None)
        self._save_sync_type_config()

    def set_repartition_swap(self, swap: dict[str, Any]) -> None:
        self.sync_type_config["repartition_swap"] = swap
        self._save_sync_type_config()

    def clear_repartition_swap(self) -> None:
        self.sync_type_config.pop("repartition_swap", None)
        self._save_sync_type_config()

    def stamp_last_repartition_at(self) -> None:
        self.sync_type_config["last_repartition_at"] = timezone.now().isoformat()
        self._save_sync_type_config()

    def stage_incremental_field_value(self, run_uuid: str, last_value: Any, earliest_value: Any = None) -> None:
        existing = self.sync_type_config.get("incremental_staged", {})
        if existing.get("run_uuid") == run_uuid:
            staged = existing
        else:
            staged = {"run_uuid": run_uuid}
        if last_value is not None:
            staged["last_value"] = self._serialize_incremental_value(last_value)
        if earliest_value is not None:
            staged["earliest_value"] = self._serialize_incremental_value(earliest_value)
        self.sync_type_config["incremental_staged"] = staged
        self.save()

    def promote_staged_incremental_values(self, run_uuid: str) -> bool:
        staged = self.sync_type_config.get("incremental_staged")
        if not staged or staged.get("run_uuid") != run_uuid:
            return False
        if "last_value" in staged:
            self.sync_type_config["incremental_field_last_value"] = staged["last_value"]
        if "earliest_value" in staged:
            self.sync_type_config["incremental_field_earliest_value"] = staged["earliest_value"]
        self.sync_type_config.pop("incremental_staged", None)
        self.save()
        return True

    def _serialize_incremental_value(self, value: Any) -> Any:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")
        if "numpy" in sys.modules:
            import numpy  # noqa: PLC0415

            value = value.item() if isinstance(value, numpy.generic) else value
        if value is None:
            return None
        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(value, int | float):
                return value
            elif isinstance(value, datetime):
                return value.isoformat()
            else:
                return int(value)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(value, datetime):
                return value.isoformat()
            else:
                return str(value)
        return str(value)

    def update_sync_type_config_for_reset_pipeline(self) -> None:
        self.sync_type_config.pop("reset_pipeline", None)
        self.sync_type_config.pop("incremental_field_last_value", None)
        self.sync_type_config.pop("incremental_field_earliest_value", None)
        self.sync_type_config.pop("incremental_staged", None)
        self.sync_type_config.pop("partitioning_enabled", None)
        self.sync_type_config.pop("partition_size", None)
        self.sync_type_config.pop("partition_count", None)
        self.sync_type_config.pop("partitioning_keys", None)
        self.sync_type_config.pop("partition_mode", None)
        self.sync_type_config.pop("backfilled_partition_format", None)
        self.sync_type_config.pop("xmin_last_value", None)
        self.sync_type_config.pop("xmin_ceiling", None)
        self.sync_type_config.pop("xmin_num_wraparound", None)
        # We don't reset partition_format
        # We don't reset chunk_size_override
        # We intentionally don't reset partition_count_override / partition_size_override /
        # partition_mode_override / partitioning_keys_override: an operator pins those via the admin
        # repartition / change-partition-mode actions precisely so they survive this reset and win
        # the resync it triggers. They're consumed in set_partitioning_enabled.

        self.initial_sync_complete = False

        self.save(skip_activity_log=True)

    def update_incremental_field_value(
        self, last_value: Any, save: bool = True, type: Literal["last"] | Literal["earliest"] = "last"
    ) -> None:
        incremental_field_type = self.sync_type_config.get("incremental_field_type")

        # a numpy scalar can only arrive here if numpy is already imported (the import-pipeline
        # paths that produce one import it); gating keeps numpy off the django.setup() path
        if "numpy" in sys.modules:
            import numpy  # noqa: PLC0415

            last_value_py = last_value.item() if isinstance(last_value, numpy.generic) else last_value
        else:
            last_value_py = last_value
        last_value_json: Any

        if last_value_py is None:
            return

        if (
            incremental_field_type == IncrementalFieldType.Integer
            or incremental_field_type == IncrementalFieldType.Numeric
        ):
            if isinstance(last_value_py, int | float):
                last_value_json = last_value_py
            elif isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = int(last_value_py)
        elif (
            incremental_field_type == IncrementalFieldType.DateTime
            or incremental_field_type == IncrementalFieldType.Timestamp
        ):
            if isinstance(last_value_py, datetime):
                last_value_json = last_value_py.isoformat()
            else:
                last_value_json = str(last_value_py)
        else:
            last_value_json = str(last_value_py)

        if type == "last":
            self.sync_type_config["incremental_field_last_value"] = last_value_json
        elif type == "earliest":
            self.sync_type_config["incremental_field_earliest_value"] = last_value_json
        else:
            raise ValueError(f"Unsupported type for update_incremental_field_value: {type}")

        if save:
            self.save(skip_activity_log=True)

    def update_xmin_state(self, ceiling_xid: int, ceiling_xid8: int, num_wraparound: int, save: bool = True) -> None:
        # Call at job completion, not per-batch: a mid-run crash then re-reads the window
        # instead of skipping it.
        self.sync_type_config["xmin_last_value"] = ceiling_xid
        self.sync_type_config["xmin_ceiling"] = ceiling_xid8
        self.sync_type_config["xmin_num_wraparound"] = num_wraparound

        if save:
            self.save(skip_activity_log=True)

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def delete_table(self):
        # s3fs/boto3 at module scope would load at app population — only this method needs them
        from products.data_warehouse.backend.facade.api import get_s3_client  # noqa: PLC0415

        if self.table is not None:
            try:
                client = get_s3_client()
                client.delete(f"{settings.BUCKET_URL}/{self.folder_path()}", recursive=True)
            except Exception as e:
                capture_exception(e)

            if not self.table.deleted:
                self.table.soft_delete()

            self.table_id = None
            self.last_synced_at = None
            self.status = None
            self.save()

            self.update_sync_type_config_for_reset_pipeline()


def process_incremental_value(value: Any | None, field_type: IncrementalFieldType | None) -> Any:
    if value is None or value == "None" or field_type is None:
        return None

    if (
        field_type == IncrementalFieldType.Integer
        or field_type == IncrementalFieldType.Numeric
        or field_type == IncrementalFieldType.XID
    ):
        return value

    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        if isinstance(value, datetime):
            return value

        return parser.parse(value)

    if field_type == IncrementalFieldType.Date:
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        return parser.parse(value).date()

    if field_type == IncrementalFieldType.ObjectID:
        return str(value)


def apply_incremental_lookback(
    value: Any, field_type: IncrementalFieldType | None, lookback_seconds: int | None
) -> Any:
    """Shift a processed incremental watermark back by `lookback_seconds` for the source query only.

    Used to re-read a rolling overlap window each incremental run so late or backdated rows (whose
    incremental field lands at or below the stored watermark) are picked up. The persisted watermark
    is never mutated — this only adjusts the value bound into the source's WHERE clause. Timestamp/date
    fields only; for `Date` a sub-day lookback rounds down to whole days.
    """
    if value is None or not isinstance(lookback_seconds, int) or lookback_seconds <= 0:
        return value

    if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp, IncrementalFieldType.Date):
        return value - timedelta(seconds=lookback_seconds)

    return value


@database_sync_to_async
def asave_external_data_schema(schema: ExternalDataSchema) -> None:
    schema.save()


def get_schema_if_exists(schema_name: str, team_id: int, source_id: uuid.UUID) -> ExternalDataSchema | None:
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, source_id=source_id, name=schema_name)
        .first()
    )
    return schema


@database_sync_to_async
def aget_schema_by_id(schema_id: str, team_id: int) -> ExternalDataSchema | None:
    return (
        ExternalDataSchema.objects.prefetch_related("source").exclude(deleted=True).get(id=schema_id, team_id=team_id)
    )


def update_should_sync(schema_id: str, team_id: int, should_sync: bool) -> ExternalDataSchema | None:
    # data_load.service imports temporalio at module scope; this is a models module, so a
    # top-level import would put the Temporal client on the django.setup() path
    from products.data_warehouse.backend.facade.api import (  # noqa: PLC0415
        external_data_workflow_exists,
        pause_external_data_schedule,
        sync_external_data_job_workflow,
        unpause_external_data_schedule,
    )

    schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id, team_id=team_id)
    schema.should_sync = should_sync
    schema.save()

    if not schema.source.supports_scheduled_sync:
        return schema

    schedule_exists = external_data_workflow_exists(schema_id)

    if schedule_exists:
        if should_sync is False:
            pause_external_data_schedule(schema_id)
        elif should_sync is True:
            unpause_external_data_schedule(schema_id)
    else:
        if should_sync is True:
            sync_external_data_job_workflow(schema, create=True)

    return schema


def update_sync_type_config_keys(
    schema_id: str | uuid.UUID,
    team_id: int,
    *,
    updates: dict[str, Any] | None = None,
    removes: Iterable[str] | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    extra_model_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically merge keys into a schema's `sync_type_config` under a row lock and return the
    persisted config.

    The CDC extract activity holds a long-lived in-memory schema and writes `sync_type_config`
    repeatedly across a run, while API PATCHes rewrite the same JSON concurrently. A
    read-modify-write off a copy loaded earlier loses whichever side saved last. Re-fetching the
    row inside the transaction with `select_for_update` makes every writer merge onto the latest
    committed value instead of clobbering it.

    `updates` sets keys, `removes` pops keys, and `mutate` runs last for in-place edits of nested
    structures (e.g. appending to `cdc_deferred_runs`) that must happen inside the critical section.
    Callers refresh their in-memory copy from the returned dict.

    `extra_model_fields` saves additional model fields in the same transaction and row lock — use
    when a reset must flip both `sync_type_config` and another field (e.g. `initial_sync_complete`)
    atomically so no reader can observe the half-written state.

    Saves with `skip_activity_log=True`: `sync_type_config` is excluded from the schema's audit
    diff anyway, and the bypass skips the extra `_get_before_update` SELECT that can fail when the
    pooler drops the connection mid-sync.
    """
    with transaction.atomic():
        schema = ExternalDataSchema.objects.select_for_update().get(id=schema_id, team_id=team_id)
        config = schema.sync_type_config or {}
        if updates:
            config.update(updates)
        if removes:
            for key in removes:
                config.pop(key, None)
        if mutate is not None:
            mutate(config)
        schema.sync_type_config = config
        update_fields = ["sync_type_config", "updated_at"]
        if extra_model_fields:
            for field, value in extra_model_fields.items():
                setattr(schema, field, value)
                update_fields.append(field)
        schema.save(update_fields=update_fields, skip_activity_log=True)
        return config


def get_all_schemas_for_source_id(source_id: str, team_id: int):
    return list(ExternalDataSchema.objects.exclude(deleted=True).filter(team_id=team_id, source_id=source_id).all())


def _update_labels(old_schemas: list["ExternalDataSchema"], new_schemas: dict[str, str | None]) -> None:
    for schema in old_schemas:
        new_label = new_schemas.get(schema.name)
        if new_label is not None and schema.label != new_label:
            schema.label = new_label
            schema.save(update_fields=["label", "updated_at"])


def sync_old_schemas_with_new_schemas(
    new_schemas: dict[str, str | None],
    source_id: str,
    team_id: int,
    descriptions: dict[str, str | None] | None = None,
) -> tuple[list[str], list[str]]:
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    old_schemas_names = [schema.name for schema in old_schemas]

    if descriptions:
        for old_schema in old_schemas:
            new_description = descriptions.get(old_schema.name)
            if old_schema.description != new_description:
                old_schema.description = new_description
                old_schema.save(update_fields=["description", "updated_at"])

    # Update display labels on existing schemas
    _update_labels(old_schemas, new_schemas)

    new_schema_names = list(new_schemas.keys())

    # Discovery names a table qualified (`schema.table`) or bare (`table`) depending on config, so
    # bare and qualified mean the same table — else a live row is wrongly disabled/duplicated. Two
    # qualified names still need exact equality so same-named tables in different schemas stay distinct.
    def _same_table(a: str, b: str) -> bool:
        one_qualified = ("." in a) != ("." in b)
        return a == b or (one_qualified and a.rpartition(".")[2] == b.rpartition(".")[2])

    # Create discovered names not already stored; flag stored names discovery no longer reports.
    schemas_to_create: list[str] = []
    for new_name in new_schema_names:
        if not any(_same_table(new_name, old_name) for old_name in old_schemas_names):
            schemas_to_create.append(new_name)

    schemas_to_possibly_delete: list[str] = []
    for old_name in old_schemas_names:
        if not any(_same_table(old_name, new_name) for new_name in new_schema_names):
            schemas_to_possibly_delete.append(old_name)
    deleted_schemas: list[str] = []
    actually_created: list[str] = []

    for schema in schemas_to_create:
        deleted_obj = (
            ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, name=schema, deleted=True)
            .order_by("-updated_at", "-created_at")
            .first()
        )
        if deleted_obj is not None:
            deleted_obj.deleted = False
            deleted_obj.deleted_at = None
            deleted_obj.description = descriptions.get(schema) if descriptions else None
            deleted_obj.label = new_schemas.get(schema)
            deleted_obj.save(update_fields=["deleted", "deleted_at", "description", "label", "updated_at"])
            actually_created.append(schema)
            continue

        obj, created = ExternalDataSchema.objects.get_or_create(
            team_id=team_id,
            source_id=source_id,
            name=schema,
            deleted=False,
            defaults={
                "should_sync": False,
                "description": descriptions.get(schema) if descriptions else None,
                "label": new_schemas.get(schema),
            },
        )
        if created:
            actually_created.append(schema)

    for schema in schemas_to_possibly_delete:
        # There _could_ exist multiple schemas with the same name, there shouldn't be, but it's not impossible
        schemas_to_check = ExternalDataSchema.objects.filter(
            team_id=team_id, name=schema, source_id=source_id, deleted=False
        )
        for s in schemas_to_check:
            if s.table_id is None:
                s.soft_delete()
                deleted_schemas.append(schema)
            else:
                s.should_sync = False
                s.status = ExternalDataSchema.Status.COMPLETED
                s.save()

    return actually_created, deleted_schemas


def sync_frequency_to_sync_frequency_interval(frequency: str) -> timedelta | None:
    if frequency == "never":
        return None
    if frequency == "1min":
        return timedelta(minutes=1)
    if frequency == "5min":
        return timedelta(minutes=5)
    if frequency == "15min":
        return timedelta(minutes=15)
    if frequency == "30min":
        return timedelta(minutes=30)
    if frequency == "1hour":
        return timedelta(hours=1)
    if frequency == "6hour":
        return timedelta(hours=6)
    if frequency == "12hour":
        return timedelta(hours=12)
    if frequency == "24hour":
        return timedelta(hours=24)
    if frequency == "7day":
        return timedelta(days=7)
    if frequency == "30day":
        return timedelta(days=30)

    raise ValueError(f"Frequency {frequency} is not supported")


def sync_frequency_interval_to_sync_frequency(sync_frequency_interval: timedelta | None) -> str | None:
    if sync_frequency_interval is None:
        return None
    if sync_frequency_interval == timedelta(minutes=1):
        return "1min"
    if sync_frequency_interval == timedelta(minutes=5):
        return "5min"
    if sync_frequency_interval == timedelta(minutes=15):
        return "15min"
    if sync_frequency_interval == timedelta(minutes=30):
        return "30min"
    if sync_frequency_interval == timedelta(hours=1):
        return "1hour"
    if sync_frequency_interval == timedelta(hours=6):
        return "6hour"
    if sync_frequency_interval == timedelta(hours=12):
        return "12hour"
    if sync_frequency_interval == timedelta(hours=24):
        return "24hour"
    if sync_frequency_interval == timedelta(days=7):
        return "7day"
    if sync_frequency_interval == timedelta(days=30):
        return "30day"

    raise ValueError(f"Frequency interval {sync_frequency_interval} is not supported")
