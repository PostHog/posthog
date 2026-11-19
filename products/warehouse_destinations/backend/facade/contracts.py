"""Public contracts for warehouse destinations.

Batch exports and warehouse source writers both use these types to write Arrow
record batches into a destination. No Django imports here.
"""

from collections.abc import AsyncIterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import field
from types import MappingProxyType
from typing import Any, Protocol

import pyarrow as pa

from posthog.dataclasses import frozen

from .enums import NewColumnPolicy, TypePolicy, WriteMode


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@frozen
class DestinationConnection:
    """Where a destination connects, and with which secrets.

    `config` holds settings that are not secret, for example host, port,
    database, schema or has_self_signed_cert. `credentials` holds inline secrets.
    Legacy batch exports use them when `integration_id` is None.
    """

    destination_type: str
    team_id: int
    integration_id: int | None = None
    config: Mapping[str, Any] = field(default_factory=_empty_mapping)
    credentials: Mapping[str, Any] = field(default_factory=_empty_mapping, repr=False)

    def __post_init__(self) -> None:
        # Copy the mappings so that a caller cannot change a connection after construction.
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))
        object.__setattr__(self, "credentials", MappingProxyType(dict(self.credentials)))


@frozen
class MergeSpec:
    """How a MERGE write matches incoming rows with rows in the table.

    `version_keys` decide which of two matching rows wins. `dedupe_source` removes
    duplicate primary keys from the incoming rows before the merge.
    """

    primary_keys: tuple[str, ...]
    version_keys: tuple[str, ...] = ()
    dedupe_source: bool = False

    def __post_init__(self) -> None:
        if not self.primary_keys:
            raise ValueError("MergeSpec requires at least one primary key")

        overlap = set(self.primary_keys) & set(self.version_keys)
        if overlap:
            raise ValueError(f"Keys cannot be both primary and version keys: {sorted(overlap)}")


@frozen
class TableTarget:
    """The table that a write goes to, and how the write behaves.

    `namespace` holds the parents of the table, for example (database, schema).
    `column_overrides` maps a column name to a destination type that replaces the
    type the destination infers from `schema`. `staging_key` names the staging
    table, so that a retry can find the staging table of an earlier attempt.
    `owner_tag` marks tables this caller created.
    """

    namespace: tuple[str, ...]
    table_name: str
    schema: pa.Schema
    write_mode: WriteMode
    merge: MergeSpec | None = None
    type_policy: TypePolicy = TypePolicy.STRICT
    new_columns: NewColumnPolicy = NewColumnPolicy.ADD
    column_overrides: Mapping[str, str] = field(default_factory=_empty_mapping)
    staging_key: str | None = None
    owner_tag: str | None = None

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("TableTarget requires a table name")

        if self.write_mode == WriteMode.MERGE:
            if self.merge is None:
                raise ValueError("A MERGE write requires a MergeSpec")
        elif self.merge is not None:
            raise ValueError(f"A {self.write_mode} write cannot have a MergeSpec")

        if self.write_mode in (WriteMode.MERGE, WriteMode.REPLACE) and not self.staging_key:
            raise ValueError(f"A {self.write_mode} write requires a staging key")

        if self.merge is not None:
            missing = [
                key for key in (*self.merge.primary_keys, *self.merge.version_keys) if key not in self.schema.names
            ]
            if missing:
                raise ValueError(f"Merge keys are not in the schema: {missing}")

        object.__setattr__(self, "column_overrides", MappingProxyType(dict(self.column_overrides)))


@frozen
class PreparedTarget:
    """A target after `Destination.prepare`.

    `write_into` is the fully qualified name of the table that writes go to: the
    final table for APPEND, and the staging table for MERGE and REPLACE.
    `existing_columns` holds the columns the final table had before the write.
    """

    target: TableTarget
    write_into: tuple[str, ...]
    existing_columns: tuple[str, ...]


@frozen
class WriteOutcome:
    rows_written: int
    bytes_written: int


class DestinationLogger(Protocol):
    """The logger a destination writes to. A structlog logger satisfies it."""

    def debug(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...


class Destination(Protocol):
    """A place that receives Arrow record batches.

    A caller enters `connect()`, then calls `prepare`, `write` (one or more times),
    and `commit`. On failure, the caller calls `abort`.
    """

    @property
    def destination_type(self) -> str: ...

    def connect(self) -> AbstractAsyncContextManager[None]:
        """Open the connection for the duration of the context."""
        ...

    async def prepare(self, target: TableTarget) -> PreparedTarget:
        """Make sure the final table and, if needed, the staging table exist.

        This is idempotent for the same `staging_key`. When a staging table for
        that key already exists, a resumed attempt keeps its rows.
        """
        ...

    async def write(
        self,
        prepared: PreparedTarget,
        batches: AsyncIterable[pa.RecordBatch],
        *,
        batch_key: str | None = None,
    ) -> WriteOutcome:
        """Write `batches` into `prepared.write_into`.

        A retried write with the same `batch_key` does not duplicate rows. Only MERGE and
        REPLACE writes go through a staging table that can carry the key, so an APPEND write
        with a `batch_key` raises `ValueError`.
        """
        ...

    async def commit(self, prepared: PreparedTarget) -> None:
        """Make the written rows visible in the final table.

        For MERGE and REPLACE this moves the staging rows into the final table.
        It is safe to call two times.
        """
        ...

    async def abort(self, prepared: PreparedTarget) -> None:
        """Clean up after a failed write.

        This is best effort and never raises.
        """
        ...


class DestinationFactory(Protocol):
    """Build a destination for one connection."""

    def __call__(
        self, connection: DestinationConnection, /, *, logger: DestinationLogger | None = None
    ) -> Destination: ...


class DestinationError(Exception):
    """Base class for errors from a destination."""


class DestinationConfigurationError(DestinationError):
    """The destination settings or credentials are not correct.

    Callers must not retry, because a retry fails the same way.
    """


class UnsupportedDestinationError(DestinationError):
    """No destination is registered for the requested destination type."""
