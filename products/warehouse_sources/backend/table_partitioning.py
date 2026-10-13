"""Let a user choose the date column a synced table is partitioned by.

A query that filters on the partition column reads only the matching partitions. The pipeline picks
a layout on the first sync, and it cannot know which column a team filters on, so a large table can
end up in hash buckets that no filter can skip.

Nothing is rewritten here. `stage_datetime_partitioning` stages the same `repartition_pending`
target as the admin page, and the next sync rewrites the stored files before it extracts.
"""

from typing import Any

from django.db import models

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.table import HIDDEN_COLUMNS


class PartitionMode(models.TextChoices):
    MD5 = "md5", "Hash buckets"
    NUMERICAL = "numerical", "Numeric ranges"
    DATETIME = "datetime", "Date ranges"


class PartitionGranularity(models.TextChoices):
    MONTH = "month", "Month"
    WEEK = "week", "Week"
    DAY = "day", "Day"
    HOUR = "hour", "Hour"


PARTITIONABLE_SYNC_TYPES = frozenset({ExternalDataSchema.SyncType.INCREMENTAL, ExternalDataSchema.SyncType.APPEND})

_BUSY_KEYS = ("repartition_pending", "repartition_swap", "delta_revive_required")


class PartitioningNotAllowed(Exception):
    pass


def _clickhouse_type(definition: Any) -> str:
    raw = definition.get("clickhouse", "") if isinstance(definition, dict) else definition
    raw = raw if isinstance(raw, str) else ""
    return raw.removeprefix("Nullable(")


def date_columns(schema: ExternalDataSchema) -> dict[str, bool]:
    """Columns of the synced table that can be a partition column, mapped to whether they carry a time of day."""
    table = schema.table
    if table is None:
        return {}
    columns: dict[str, bool] = {}
    for name, definition in (table.columns or {}).items():
        if name in HIDDEN_COLUMNS:
            continue
        clickhouse_type = _clickhouse_type(definition)
        if clickhouse_type.startswith("DateTime"):
            columns[name] = True
        elif clickhouse_type.startswith("Date"):
            columns[name] = False
    return columns


def partitioning_state(schema: ExternalDataSchema) -> dict[str, Any]:
    config = schema.sync_type_config or {}
    mode = schema.partition_mode
    return {
        "mode": mode,
        "columns": schema.partitioning_keys or [],
        "date_granularity": schema.partition_format if mode == PartitionMode.DATETIME else None,
        "change_pending": any(isinstance(config.get(key), dict) for key in _BUSY_KEYS),
        "available_columns": sorted(date_columns(schema)),
    }


def stage_datetime_partitioning(schema: ExternalDataSchema, column: str, granularity: str) -> None:
    if schema.sync_type not in PARTITIONABLE_SYNC_TYPES:
        raise PartitioningNotAllowed(
            "Only tables that sync with the incremental or append-only method can change this."
        )
    if not schema.should_sync:
        raise PartitioningNotAllowed("Turn on syncing for this table first. The next sync applies the change.")

    columns = date_columns(schema)
    if not columns:
        raise PartitioningNotAllowed("This table has no date column yet. Wait for its first sync to finish.")
    if column not in columns:
        raise PartitioningNotAllowed(f"'{column}' is not a date column of this table.")
    # Every row of a day has the same hour in a date-only column, so hour partitions split nothing.
    if granularity == PartitionGranularity.HOUR and not columns[column]:
        raise PartitioningNotAllowed(f"'{column}' has no time of day. Choose day, week or month.")

    if (
        schema.partition_mode == PartitionMode.DATETIME
        and schema.partitioning_keys == [column]
        and schema.partition_format == granularity
    ):
        raise PartitioningNotAllowed("The table already uses this partitioning.")

    target = {
        "partition_mode": PartitionMode.DATETIME.value,
        "partition_format": granularity,
        "partition_count": None,
        "partition_size": None,
        "partition_keys": [column],
        "trigger_reason": "user",
        "attempts": 0,
    }

    def _stage(config: dict[str, Any]) -> None:
        # A second rewrite staged over a running one would change the target under it.
        if any(isinstance(config.get(key), dict) for key in _BUSY_KEYS):
            raise PartitioningNotAllowed("A change to this table's partitioning is already in progress.")
        config["repartition_pending"] = target

    schema.sync_type_config = update_sync_type_config_keys(schema.id, schema.team_id, mutate=_stage)
