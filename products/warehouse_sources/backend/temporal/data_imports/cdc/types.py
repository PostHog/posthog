from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, Self

import pyarrow as pa

ManagementMode = Literal["posthog", "self_managed"]


@dataclass(frozen=True)
class CDCConfig:
    """Base class for engine-specific CDC configs returned by ``parse_cdc_config``.

    Holds fields that apply to any change-stream engine (slot/publication-style
    identifiers, lag thresholds, management policy). Engine adapters return their
    own subclasses (e.g. ``PostgresCDCConfig``) and add engine-specific fields.
    """

    enabled: bool
    slot_name: str
    publication_name: str
    management_mode: ManagementMode
    lag_warning_threshold_mb: int
    lag_critical_threshold_mb: int
    auto_drop_slot: bool


class CDCPosition(Protocol):
    """Opaque replication position. PG=LSN, MySQL=GTID set."""

    def serialize(self) -> str: ...

    @classmethod
    def deserialize(cls, value: str) -> Self: ...

    def __le__(self, other: Self) -> bool: ...

    def __lt__(self, other: Self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """A single row-level change captured from a database's change stream."""

    operation: Literal["I", "U", "D"]
    table_name: str
    position_serialized: str
    timestamp: datetime
    columns: dict[str, Any]
    # Authoritative Arrow type per source column, from the engine's schema metadata
    # (e.g. Postgres relation OIDs). Lets the batcher type a column the same way in
    # every micro-batch even when one flush sees it all-null — without it, an all-null
    # flush is inferred as string while a concrete flush is int64, and the two Parquet
    # schemas fail to merge. Shared across all events of one relation; None when unknown.
    column_types: Mapping[str, pa.DataType] | None = None


class CDCStreamReader(Protocol):
    """Database-specific interface for reading change streams.

    Implementations:
    - Postgres: PgCDCStreamReader (SQL-based via pg_logical_slot_peek_binary_changes)
    - MySQL: future binlog/GTID reader
    """

    def connect(self) -> None: ...

    def read_changes(self) -> Iterator[ChangeEvent]: ...

    def confirm_position(self, position: str) -> None: ...

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]: ...

    def get_decoder_key_columns(self, table_name: str) -> list[str]: ...

    @property
    def truncated_tables(self) -> list[str]: ...

    def clear_truncated_tables(self) -> None: ...

    @property
    def last_commit_end_lsn(self) -> str | None: ...

    def close(self) -> None: ...
