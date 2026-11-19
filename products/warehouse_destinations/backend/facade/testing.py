"""Test support for code that writes through warehouse destinations.

`FakeDestination` is an in-memory destination that records every call. It is its own factory,
so a test installs it with `override_destination` and the code under test gets it from
`api.get_destination`:

    fake = FakeDestination()
    with override_destination(DestinationType.POSTGRES, fake):
        await code_under_test()
    assert fake.tables[("public", "orders")] == [{"id": 1}]

The fake follows the session contract: it validates targets against its capabilities, keeps
staged rows per staging key and batch key, upserts MERGE rows on the primary keys (the last
written row wins; version keys are not compared), and records the staging key of a REPLACE
commit so a replay gets `already_committed=True`.
"""

import contextlib
from collections import defaultdict
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterator
from typing import Any

import pyarrow as pa

from posthog.dataclasses import frozen

from ..core.validation import check_batch_key, check_ref
from ..logic import registry
from .contracts import (
    DestinationCapabilities,
    DestinationConnection,
    DestinationError,
    DestinationFactory,
    DestinationLogger,
    PreparedTarget,
    TableTarget,
    TargetRef,
    WriteOutcome,
)
from .enums import DestinationType, ErrorKind, WriteMode

Row = dict[str, Any]
TableKey = tuple[str, ...]

DEFAULT_FAKE_CAPABILITIES = DestinationCapabilities(
    write_modes=frozenset(WriteMode),
    batch_key_modes=frozenset({WriteMode.MERGE, WriteMode.REPLACE}),
    namespace_depth=1,
    atomic_replace=True,
)


@frozen
class FakeCall:
    """One call a `FakeSession` received. Fields that do not apply to the method are None."""

    method: str
    ref: TargetRef
    batch_key: str | None = None
    final: bool | None = None
    rows: tuple[Row, ...] = ()


@frozen(frozen=False)
class _Staged:
    target: TableTarget
    batches: dict[str | None, list[Row]]


@contextlib.contextmanager
def override_destination(destination_type: DestinationType, factory: DestinationFactory) -> Iterator[None]:
    """Make `api.get_destination` and `api.get_capabilities` use `factory` inside the context."""
    with registry.override(DestinationType(destination_type), factory):
        yield


class FakeDestination:
    """An in-memory `Destination` that is also its own `DestinationFactory`.

    `calls` lists every session call in order. `tables` holds the committed rows of each final
    table, keyed by `(*namespace, table_name)`. `connections` lists the connections the factory
    received. `fail_next(method, error)` makes the next call of a session method, or of
    `connect`, raise `error` after it is recorded and before it changes anything. An error
    injected into `abort` is swallowed, as `abort` never raises.
    """

    def __init__(
        self,
        *,
        destination_type: DestinationType = DestinationType.POSTGRES,
        capabilities: DestinationCapabilities = DEFAULT_FAKE_CAPABILITIES,
    ) -> None:
        self.destination_type = destination_type
        self.capabilities = capabilities
        self.calls: list[FakeCall] = []
        self.tables: dict[TableKey, list[Row]] = defaultdict(list)
        self.connections: list[DestinationConnection] = []
        self._staged: dict[tuple[TableKey, str], _Staged] = {}
        self._committed_keys: dict[TableKey, str] = {}
        self._failures: dict[str, list[BaseException]] = defaultdict(list)

    def __call__(
        self, connection: DestinationConnection, /, *, logger: DestinationLogger | None = None
    ) -> "FakeDestination":
        self.connections.append(connection)
        return self

    def fail_next(self, method: str, error: BaseException) -> None:
        self._failures[method].append(error)

    def _raise_if_failing(self, method: str) -> None:
        if self._failures[method]:
            raise self._failures[method].pop(0)

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator["FakeSession"]:
        self._raise_if_failing("connect")
        yield FakeSession(self)


class FakeSession:
    """The `DestinationSession` of a `FakeDestination`."""

    def __init__(self, destination: FakeDestination) -> None:
        self._destination = destination

    async def prepare(self, target: TableTarget) -> PreparedTarget:
        fake = self._destination
        fake.calls.append(FakeCall(method="prepare", ref=target.ref))
        fake._raise_if_failing("prepare")
        ref = target.ref
        check_ref(fake.capabilities, ref)

        table = _table_key(ref)
        if ref.write_mode == WriteMode.REPLACE and fake._committed_keys.get(table) == ref.staging_key:
            return PreparedTarget(target=target, already_committed=True)

        if ref.write_mode != WriteMode.REPLACE:
            fake.tables.setdefault(table, [])
        if ref.write_mode != WriteMode.APPEND:
            assert ref.staging_key is not None
            staged = fake._staged.setdefault((table, ref.staging_key), _Staged(target=target, batches={}))
            staged.target = target
        return PreparedTarget(target=target)

    async def write(
        self, prepared: PreparedTarget, batches: AsyncIterable[pa.RecordBatch], *, batch_key: str | None = None
    ) -> WriteOutcome:
        fake = self._destination
        ref = prepared.target.ref
        rows: list[Row] = []
        if not prepared.already_committed:
            async for batch in batches:
                rows.extend(batch.to_pylist())
        fake.calls.append(FakeCall(method="write", ref=ref, batch_key=batch_key, rows=tuple(rows)))
        fake._raise_if_failing("write")
        check_batch_key(fake.capabilities, ref, batch_key)
        if prepared.already_committed:
            return WriteOutcome(rows_written=0, bytes_written=0)

        table = _table_key(ref)
        if ref.write_mode == WriteMode.APPEND:
            fake.tables[table].extend(rows)
        else:
            assert ref.staging_key is not None
            staged = fake._staged.get((table, ref.staging_key))
            if staged is None:
                raise DestinationError("Write before prepare", kind=ErrorKind.CONFIGURATION)
            if batch_key is not None:
                staged.batches[batch_key] = []
            staged.batches.setdefault(batch_key, []).extend(rows)
        return WriteOutcome(rows_written=len(rows), bytes_written=sum(len(repr(row)) for row in rows))

    async def commit(self, ref: TargetRef, *, final: bool = True) -> None:
        fake = self._destination
        fake.calls.append(FakeCall(method="commit", ref=ref, final=final))
        fake._raise_if_failing("commit")
        check_ref(fake.capabilities, ref)
        if ref.write_mode == WriteMode.APPEND or (ref.write_mode == WriteMode.REPLACE and not final):
            return

        table = _table_key(ref)
        assert ref.staging_key is not None
        staged = fake._staged.get((table, ref.staging_key))
        if staged is None:
            return
        rows = [row for batch in staged.batches.values() for row in batch]

        if ref.write_mode == WriteMode.REPLACE:
            fake.tables[table] = rows
            fake._committed_keys[table] = ref.staging_key
        else:
            merge = staged.target.merge
            assert merge is not None
            _upsert(fake.tables[table], rows, key=lambda row: tuple(row.get(k) for k in merge.primary_keys))

        if final:
            del fake._staged[(table, ref.staging_key)]
        else:
            staged.batches.clear()

    async def abort(self, ref: TargetRef) -> None:
        fake = self._destination
        fake.calls.append(FakeCall(method="abort", ref=ref))
        try:
            fake._raise_if_failing("abort")
        except Exception:
            return
        if ref.staging_key is not None:
            fake._staged.pop((_table_key(ref), ref.staging_key), None)


def _table_key(ref: TargetRef) -> TableKey:
    return (*ref.namespace, ref.table_name)


def _upsert(table: list[Row], rows: list[Row], *, key: Callable[[Row], tuple[Any, ...]]) -> None:
    positions = {key(row): index for index, row in enumerate(table)}
    for row in rows:
        row_key = key(row)
        if row_key in positions:
            table[positions[row_key]] = row
        else:
            positions[row_key] = len(table)
            table.append(row)
