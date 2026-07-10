# Annotations are lazy (PEP 563) so the dlt import below can stay type-only — dlt is heavy and this
# module is reachable from warehouse_sources models at django.setup().
from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterable, Callable, Iterable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NotRequired, Optional, Protocol, TypedDict, TypeVar

from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.types import IncrementalFieldType

if TYPE_CHECKING:
    from dlt.common.data_types.typing import TDataType

    from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
        ValidatedRowFilter,
    )
else:
    # Runtime stubs so get_type_hints() on the dataclasses below resolves without importing dlt or the
    # predicates module. Deliberately not `str` — nothing should rely on the runtime value, and a named
    # stub makes accidental use obvious rather than silently passing as a plausible type. The real,
    # mypy-visible types come from the TYPE_CHECKING branch.
    class TDataType:
        def __repr__(self) -> str:
            return "<TDataType: type-checking-only stub for dlt.common.data_types.typing.TDataType>"

    class ValidatedRowFilter:
        def __repr__(self) -> str:
            return "<ValidatedRowFilter: type-checking-only stub>"


SortMode = Literal["asc", "desc"]
PartitionMode = Literal["md5", "numerical", "datetime"]
PartitionFormat = Literal["month", "week", "day", "hour"]


class _Dataclass(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]


ResumableData = TypeVar("ResumableData", bound=_Dataclass)


@dataclasses.dataclass
class SourceResponse:
    name: str
    items: Callable[[], Iterable[Any] | AsyncIterable[Any]]
    primary_keys: list[str] | None
    column_hints: dict[str, TDataType | None] | None = None  # Legacy support for DLT sources
    partition_count: Optional[int] = None
    partition_size: Optional[int] = None
    partition_keys: Optional[list[str]] = None
    """Override partition keys at a source level"""
    partition_mode: Optional[PartitionMode] = None
    """Override partition mode at a source level"""
    partition_format: Optional[PartitionFormat] = None
    """Override partition format at a source level"""
    sort_mode: Optional[SortMode] = "asc"
    """our source typically return data in ascending timestamp order, but some (eg Stripe) do not"""
    rows_to_sync: Optional[int] = None
    has_duplicate_primary_keys: Optional[bool] = None
    """Whether incremental tables have non-unique primary keys"""
    chunk_size: Optional[int] = None
    """Override the batcher's rows-per-chunk (defaults to DEFAULT_CHUNK_SIZE)."""
    chunk_size_bytes: Optional[int] = None
    """Override the batcher's per-chunk byte cap (defaults to DEFAULT_CHUNK_SIZE_BYTES). Lower it for
    sources whose rows are large (e.g. whole documents) so the source->Arrow conversion doesn't
    materialise an oversized table and OOM the worker."""
    xmin_ceiling_xid: Optional[int] = None
    """xmin syncs: bare 32-bit ceiling captured this run, persisted as the next run's lower bound."""
    xmin_ceiling_xid8: Optional[int] = None
    """xmin syncs: full 64-bit `xid8` ceiling, the durable wraparound-safe cursor."""
    xmin_num_wraparound: Optional[int] = None
    """xmin syncs: epoch (high 32 bits of `xmin_ceiling_xid8`) at this run's ceiling."""


@dataclasses.dataclass
class SourceInputs:
    """Contextual info required by a source to actually run"""

    schema_name: str
    schema_id: str
    source_id: str
    team_id: int
    should_use_incremental_field: bool
    db_incremental_field_last_value: Optional[Any]
    db_incremental_field_earliest_value: Optional[Any]
    incremental_field: Optional[str]
    incremental_field_type: Optional[IncrementalFieldType]
    job_id: str
    logger: FilteringBoundLogger
    reset_pipeline: bool
    enabled_columns: Optional[list[str]] = None
    row_filters: Optional[list[ValidatedRowFilter]] = None
    # Multi-schema import context, read by `resolve_source_location`.
    schema_metadata: Optional[dict[str, Any]] = None
    s3_folder_name: Optional[str] = None
    # Effective vendor API version: the source instance's pin resolved through the source's
    # `default_version`. Sources with a versioned vendor API thread it to their request layer.
    api_version: Optional[str] = None


class PipelineResult(TypedDict):
    should_trigger_cdp_producer: bool
    consumer_manages_job_status: NotRequired[bool]
    skip_post_import_activities: NotRequired[bool]
