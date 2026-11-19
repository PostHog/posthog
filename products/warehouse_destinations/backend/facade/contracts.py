"""Public contracts for warehouse destinations.

A caller gets a `Destination` from `api.get_destination`, opens a `DestinationSession` with
`connect()`, and writes Arrow record batches through it:

    async with destination.connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, batches, batch_key="0")
        await session.commit(target.ref)

Error contract: every exception that escapes `connect()` or a session method is a
`DestinationError`. When a driver error caused it, that error is its `__cause__`. Callers
decide what to do from `DestinationError.kind`, never from the class name or the message.

No Django imports here.
"""

from collections.abc import AsyncIterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import field
from types import MappingProxyType
from typing import Any, ClassVar, Protocol

import pyarrow as pa

from posthog.dataclasses import frozen

from .enums import DestinationType, ErrorKind, ExistingTablePolicy, LogicalType, NewColumnPolicy, TypePolicy, WriteMode


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@frozen
class DestinationConnection:
    """Where a destination connects, and with which secrets.

    The connection picks the database, project or catalog. A target's namespace is relative to
    it. `config` holds settings that are not secret, for example host, port and database, and
    every switch that only one vendor has. Each destination documents the keys it reads.
    `credentials` holds inline secrets, which the destination uses when `integration_id` is None.
    A string `destination_type` is converted to `DestinationType`, and an unknown string raises
    `ValueError`.
    """

    destination_type: DestinationType
    team_id: int
    integration_id: int | None = None
    config: Mapping[str, Any] = field(default_factory=_empty_mapping)
    credentials: Mapping[str, Any] = field(default_factory=_empty_mapping, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "destination_type", DestinationType(self.destination_type))
        # Copy the mappings so that a caller cannot change a connection after construction.
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))
        object.__setattr__(self, "credentials", MappingProxyType(dict(self.credentials)))


@frozen
class DestinationCapabilities:
    """What one destination type supports. Available without a connection.

    `write_modes` are the modes `prepare` accepts. `batch_key_modes` are the modes whose `write`
    accepts a `batch_key`; it is a subset of `write_modes`. `namespace_depth` is the number of
    parts a target namespace must have, for example 1 for a Postgres schema. `atomic_replace`
    is True when readers of the final table see either the old rows or all new rows during a
    REPLACE commit, never a mix or an empty table.
    """

    write_modes: frozenset[WriteMode]
    batch_key_modes: frozenset[WriteMode]
    namespace_depth: int
    atomic_replace: bool

    def __post_init__(self) -> None:
        if not self.write_modes:
            raise ValueError("A destination must support at least one write mode")
        unsupported = self.batch_key_modes - self.write_modes
        if unsupported:
            raise ValueError(f"Batch key modes are not write modes: {sorted(map(str, unsupported))}")
        if self.namespace_depth < 0:
            raise ValueError("The namespace depth cannot be negative")


@frozen
class MergeSpec:
    """How a MERGE write matches incoming rows with rows of the final table.

    `primary_keys` identify a row. A matched row is updated and an unmatched row is inserted.
    `version_keys` only add a condition: a matched row changes only when one of these columns
    is greater in the incoming row. `dedupe_source` keeps one incoming row per primary key:
    the row with the greatest version keys, then the row written last. Without it, two incoming
    rows with the same primary key in one commit raise a DATA-kind error.

    The final table needs a unique key on exactly `primary_keys`. A table the destination
    creates has one. For a table that exists without one, `ensure_unique_key` True makes
    `prepare` add it; False makes `prepare` raise a DATA-kind error.
    """

    primary_keys: tuple[str, ...]
    version_keys: tuple[str, ...] = ()
    dedupe_source: bool = False
    ensure_unique_key: bool = False

    def __post_init__(self) -> None:
        if not self.primary_keys:
            raise ValueError("MergeSpec requires at least one primary key")

        for keys in (self.primary_keys, self.version_keys):
            if len(set(keys)) != len(keys):
                raise ValueError(f"Keys repeat: {list(keys)}")

        overlap = set(self.primary_keys) & set(self.version_keys)
        if overlap:
            raise ValueError(f"Keys cannot be both primary and version keys: {sorted(overlap)}")


@frozen
class TargetRef:
    """The identity of a write: which table, in which mode, under which keys.

    `namespace` holds the parents of the table relative to the connection, for example
    `(schema,)` for Postgres. Its length must equal the destination's `namespace_depth`.

    `staging_key` names the staging state of a MERGE or REPLACE write. Every attempt of the
    same logical write must use the same key, so that a retry finds the staging state of an
    earlier attempt and a replayed REPLACE finds that it already committed. Use a new key for
    a new logical write. APPEND ignores it.

    `owner_tag` marks the tables the destination creates, so that a later write can tell them
    apart from tables someone else created. Both keys are opaque: the destination encodes them,
    and compares them only for exact equality.
    """

    namespace: tuple[str, ...]
    table_name: str
    write_mode: WriteMode
    staging_key: str | None = None
    owner_tag: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", tuple(self.namespace))
        object.__setattr__(self, "write_mode", WriteMode(self.write_mode))

        if not self.table_name.strip():
            raise ValueError("TargetRef requires a table name")
        if any(not part.strip() for part in self.namespace):
            raise ValueError("Namespace parts cannot be blank")
        if self.write_mode in (WriteMode.MERGE, WriteMode.REPLACE) and not self.staging_key:
            raise ValueError(f"A {self.write_mode} write requires a staging key")
        if self.owner_tag == "":
            raise ValueError("The owner tag cannot be empty; pass None for no tag")


@frozen
class TableTarget:
    """A `TargetRef` plus the schema of the rows and how the write behaves.

    `schema` is the Arrow schema of every batch the caller writes. `merge` is required for
    MERGE and forbidden for other modes, and its keys must be columns of `schema`.
    `column_types` pins a column of `schema` to a logical type, which wins over `type_policy`
    for that column. `existing_table` REQUIRE_OWNED needs `ref.owner_tag`.

    A JSON column is a column whose Arrow type is an extension type named `json` or
    `arrow.json` (any class), or a column that `column_types` pins to `LogicalType.JSON`.
    """

    ref: TargetRef
    schema: pa.Schema
    merge: MergeSpec | None = None
    type_policy: TypePolicy = TypePolicy.STRICT
    new_columns: NewColumnPolicy = NewColumnPolicy.ADD
    existing_table: ExistingTablePolicy = ExistingTablePolicy.USE
    column_types: Mapping[str, LogicalType] = field(default_factory=_empty_mapping)

    def __post_init__(self) -> None:
        if self.ref.write_mode == WriteMode.MERGE:
            if self.merge is None:
                raise ValueError("A MERGE write requires a MergeSpec")
        elif self.merge is not None:
            raise ValueError(f"A {self.ref.write_mode} write cannot have a MergeSpec")

        if self.merge is not None:
            missing = [
                key for key in (*self.merge.primary_keys, *self.merge.version_keys) if key not in self.schema.names
            ]
            if missing:
                raise ValueError(f"Merge keys are not in the schema: {missing}")

        if self.existing_table == ExistingTablePolicy.REQUIRE_OWNED and self.ref.owner_tag is None:
            raise ValueError("REQUIRE_OWNED needs an owner tag on the target")

        unknown = sorted(set(self.column_types) - set(self.schema.names))
        if unknown:
            raise ValueError(f"Column types name columns that are not in the schema: {unknown}")
        column_types = {name: LogicalType(value) for name, value in self.column_types.items()}
        object.__setattr__(self, "column_types", MappingProxyType(column_types))


@frozen
class PreparedTarget:
    """The result of `DestinationSession.prepare`. Pass it to `write`.

    Only `prepare` builds one. Callers read `target` and `already_committed` and nothing else:
    `internal` is state the destination owns, and its shape can change at any time.

    `already_committed` is True when an earlier attempt already committed this REPLACE under
    the same staging key. Then `prepare` created nothing, `write` reads nothing and returns a
    zero outcome, and `commit` does nothing.
    """

    target: TableTarget
    already_committed: bool = False
    internal: object = field(default=None, repr=False, compare=False)


@frozen
class WriteOutcome:
    """What one `write` call sent.

    `rows_written` counts the rows `write` accepted from the input batches. `bytes_written`
    counts the bytes it sent to the destination after serialization and before any compression
    on the wire. `files` lists the object keys an object store wrote, and is empty for table
    destinations.
    """

    rows_written: int
    bytes_written: int
    files: tuple[str, ...] = ()


class DestinationLogger(Protocol):
    """The logger a destination writes to. A structlog logger satisfies it."""

    def debug(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: str, /, *args: Any, **kwargs: Any) -> None: ...


class DestinationSession(Protocol):
    """An open connection to a destination.

    A session serves one task at a time: do not call its methods concurrently. Separate
    sessions, in one process or in many, can write distinct `batch_key` values into the same
    `staging_key` at the same time. The caller makes sure that no write into a staging key runs
    while a commit of that key runs.

    A session is valid only inside the `connect()` context that yielded it.
    """

    async def prepare(self, target: TableTarget) -> PreparedTarget:
        """Make sure the final table and, for MERGE and REPLACE, the staging table exist.

        Validates the target against the capabilities first, and raises a CONFIGURATION-kind
        error for a write mode the destination does not support or a namespace of the wrong
        depth, before it changes anything. Then it creates the namespace and the final table
        when they do not exist, and applies `new_columns` to an existing final table.
        A REPLACE does not touch the final table before its commit.

        Idempotent for the same target: when a staging table for the staging key exists, the
        call keeps its rows, so a resumed write continues where it stopped. When a REPLACE
        already committed under the staging key, it creates nothing and returns
        `already_committed=True`.
        """
        ...

    async def write(
        self,
        prepared: PreparedTarget,
        batches: AsyncIterable[pa.RecordBatch],
        *,
        batch_key: str | None = None,
    ) -> WriteOutcome:
        """Write `batches` into the table `prepare` chose.

        Every batch must have the schema of `prepared.target.schema`. Empty batches are skipped.
        `prepared` can come from another session of the same destination.

        With a `batch_key`, the write first removes the rows an earlier write with the same key
        left in the staging state, so a retried write does not duplicate rows. A mode outside
        `capabilities.batch_key_modes` raises a CONFIGURATION-kind error for a `batch_key`.

        APPEND writes go to the final table and are not atomic: each chunk commits on its own,
        so a failed write can leave some rows behind. A retried APPEND without a batch key can
        duplicate rows.
        """
        ...

    async def commit(self, ref: TargetRef, *, final: bool = True) -> None:
        """Make the staged rows of `ref` visible in the final table.

        - APPEND: does nothing, because writes are already visible.
        - MERGE: upserts the staged rows into the final table. With `final=False` it then
          empties the staging table and keeps it for the next batch. With `final=True` it
          drops the staging table. The upsert and the cleanup happen in one transaction.
        - REPLACE: with `final=True`, swaps the staging table in place of the final table and
          records the staging key on it. With `final=False`, does nothing.

        Needs no prior `prepare` in this session and no schema, so a new process can finish
        a write. When no staging state exists for the key (nothing was prepared, or an earlier
        commit finished), it does nothing. So it is safe to call two times.
        """
        ...

    async def abort(self, ref: TargetRef) -> None:
        """Drop the staging state of `ref`. Rows an earlier commit made visible stay.

        Needs no prior `prepare` and no schema. When there is nothing to clean up, it does
        nothing. It never raises: a failure is logged.
        """
        ...


class Destination(Protocol):
    """A place that receives Arrow record batches.

    The object holds no connection state, so one instance can open many sessions, one after
    another or at the same time.
    """

    @property
    def destination_type(self) -> DestinationType: ...

    @property
    def capabilities(self) -> DestinationCapabilities: ...

    def connect(self) -> AbstractAsyncContextManager[DestinationSession]:
        """Open a session for the duration of the context.

        A failure to connect raises a `DestinationError`. An exception the caller raises inside
        the context passes through unchanged.
        """
        ...


class DestinationFactory(Protocol):
    """Build a destination for one connection. Its `capabilities` need no connection."""

    @property
    def capabilities(self) -> DestinationCapabilities: ...

    def __call__(
        self, connection: DestinationConnection, /, *, logger: DestinationLogger | None = None
    ) -> Destination: ...


class DestinationError(Exception):
    """Base class for every error a destination raises.

    `kind` tells the caller what to do. `detail` is a message that is safe to show the
    customer; it never contains secrets, and it is None when the destination has nothing
    specific to say. A subclass can set `default_kind`, so that it does not need `kind`.
    """

    default_kind: ClassVar[ErrorKind | None] = None

    def __init__(self, message: str, *, kind: ErrorKind | None = None, detail: str | None = None) -> None:
        resolved = kind or self.default_kind
        if resolved is None:
            raise TypeError(f"{type(self).__name__} requires an error kind")
        super().__init__(message)
        self.kind: ErrorKind = resolved
        self.detail = detail

    @property
    def retryable(self) -> bool:
        """True only for TRANSIENT errors. For TIMEOUT the caller decides."""
        return self.kind == ErrorKind.TRANSIENT


class DestinationConfigurationError(DestinationError):
    """The settings, credentials or permissions are wrong. Callers must not retry."""

    default_kind = ErrorKind.CONFIGURATION


class UnsupportedDestinationError(DestinationConfigurationError):
    """No destination exists for the requested destination type."""
