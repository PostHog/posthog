from collections.abc import AsyncIterator

import pytest

import pyarrow as pa

from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationCapabilities,
    DestinationConnection,
    DestinationError,
    MergeSpec,
    TableTarget,
    TargetRef,
)
from products.warehouse_destinations.backend.facade.enums import DestinationType, ErrorKind, WriteMode
from products.warehouse_destinations.backend.facade.testing import (
    FakeCall,
    FakeDestination,
    fake_config,
    override_destination,
)


def _schema(*fields: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema(list(fields))


SCHEMA = _schema(("id", pa.int64()), ("name", pa.string()))
TABLE = ("public", "t")


def _rows(*rows: tuple[int, str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist([{"id": i, "name": n} for i, n in rows], schema=SCHEMA)


async def _batches(*batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in batches:
        yield batch


def _target(write_mode: WriteMode, staging_key: str | None = "run1") -> TableTarget:
    ref = TargetRef(namespace=("public",), table_name="t", write_mode=write_mode, staging_key=staging_key)
    merge = MergeSpec(primary_keys=("id",)) if write_mode == WriteMode.MERGE else None
    return TableTarget(ref=ref, schema=SCHEMA, merge=merge)


async def test_the_fake_reached_through_the_facade_records_every_call() -> None:
    fake = FakeDestination()
    target = _target(WriteMode.MERGE)

    with override_destination(DestinationType.POSTGRES, fake):
        destination = api.get_destination(DestinationConnection(team_id=1, config=fake_config()))
        async with destination.connect() as session:
            prepared = await session.prepare(target)
            await session.write(prepared, _batches(_rows((1, "a"))), batch_key="0")
            await session.commit(target.ref, final=False)
            await session.abort(target.ref)

    assert fake.calls == [
        FakeCall(method="prepare", ref=target.ref),
        FakeCall(method="write", ref=target.ref, batch_key="0", rows=({"id": 1, "name": "a"},)),
        FakeCall(method="commit", ref=target.ref, final=False),
        FakeCall(method="abort", ref=target.ref),
    ]
    assert fake.tables[TABLE] == [{"id": 1, "name": "a"}]


@pytest.mark.parametrize(
    "write_mode, expected",
    [
        (WriteMode.APPEND, [(1, "a"), (2, "b"), (2, "B"), (3, "c")]),
        (WriteMode.MERGE, [(1, "a"), (2, "B"), (3, "c")]),
        (WriteMode.REPLACE, [(2, "B"), (3, "c")]),
    ],
)
async def test_the_fake_applies_each_write_mode(write_mode: WriteMode, expected: list) -> None:
    fake = FakeDestination()

    async with fake.connect() as session:
        for staging_key, batches in (
            ("run1", [_rows((1, "a"), (2, "b"))]),
            ("run2", [_rows((2, "B")), _rows((3, "c"))]),
        ):
            target = _target(write_mode, staging_key)
            prepared = await session.prepare(target)
            for index, batch in enumerate(batches):
                key = None if write_mode == WriteMode.APPEND else str(index)
                await session.write(prepared, _batches(batch), batch_key=key)
            await session.commit(target.ref)

    assert [(row["id"], row["name"]) for row in fake.tables[TABLE]] == expected


async def test_the_fake_replaces_rows_of_a_retried_batch_key_and_skips_a_replayed_replace() -> None:
    fake = FakeDestination()
    target = _target(WriteMode.REPLACE)

    async with fake.connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(_rows((1, "a"))), batch_key="0")
        await session.write(prepared, _batches(_rows((1, "retry"))), batch_key="0")
        await session.commit(target.ref)
        replayed = await session.prepare(target)
        outcome = await session.write(replayed, _batches(_rows((9, "late"))), batch_key="0")

    assert replayed.already_committed
    assert outcome.rows_written == 0
    assert fake.tables[TABLE] == [{"id": 1, "name": "retry"}]


@pytest.mark.parametrize(
    "call",
    [
        "append_batch_key",
        "unsupported_mode",
        "wrong_namespace_depth",
    ],
)
async def test_the_fake_enforces_its_capabilities(call: str) -> None:
    fake = FakeDestination(
        capabilities=DestinationCapabilities(
            write_modes=frozenset({WriteMode.APPEND, WriteMode.MERGE}),
            batch_key_modes=frozenset({WriteMode.MERGE}),
            namespace_depth=1,
            atomic_replace=False,
        )
    )

    async with fake.connect() as session:
        with pytest.raises(DestinationError) as exc_info:
            if call == "append_batch_key":
                prepared = await session.prepare(_target(WriteMode.APPEND))
                await session.write(prepared, _batches(_rows((1, "a"))), batch_key="0")
            elif call == "unsupported_mode":
                await session.prepare(_target(WriteMode.REPLACE))
            else:
                ref = TargetRef(namespace=("db", "public"), table_name="t", write_mode=WriteMode.APPEND)
                await session.prepare(TableTarget(ref=ref, schema=SCHEMA))

    assert exc_info.value.kind == ErrorKind.CONFIGURATION
    assert fake.tables[TABLE] == []


@pytest.mark.parametrize("method", ["connect", "prepare", "write", "commit"])
async def test_the_fake_raises_an_injected_error_once(method: str) -> None:
    fake = FakeDestination()
    error = DestinationError("injected", kind=ErrorKind.TRANSIENT)
    fake.fail_next(method, error)
    target = _target(WriteMode.MERGE)

    async def run() -> None:
        async with fake.connect() as session:
            prepared = await session.prepare(target)
            await session.write(prepared, _batches(_rows((1, "a"))))
            await session.commit(target.ref)

    with pytest.raises(DestinationError) as exc_info:
        await run()
    await run()

    assert exc_info.value is error
    assert fake.tables[TABLE] == [{"id": 1, "name": "a"}]


async def test_an_error_injected_into_abort_is_swallowed() -> None:
    fake = FakeDestination()
    fake.fail_next("abort", DestinationError("injected", kind=ErrorKind.TRANSIENT))

    async with fake.connect() as session:
        await session.abort(_target(WriteMode.MERGE).ref)

    assert [call.method for call in fake.calls] == ["abort"]
