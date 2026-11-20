import io
import csv
import json
import typing
import datetime as dt
import collections.abc
import concurrent.futures

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_destinations.backend.core.json_type import JsonType
from products.warehouse_destinations.backend.core.transformer import (
    Chunk,
    CSVStreamTransformer,
    JSONLStreamTransformer,
    ParquetStreamTransformer,
    SerializedStreamTransformer,
)

RECORDS = [
    {
        "id": 1,
        "event": "pageview",
        "properties": '{"path": "/", "count": 1}',
        "loaded_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    },
    {
        "id": 2,
        "event": "signup",
        "properties": "{}",
        "loaded_at": dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    },
]
FIELD_NAMES = ["id", "event", "loaded_at"]


def _record_batch() -> pa.RecordBatch:
    batch = pa.RecordBatch.from_pylist(RECORDS)
    properties_index = batch.schema.get_field_index("properties")
    return batch.set_column(
        properties_index, pa.field("properties", JsonType()), batch.column(properties_index).cast(JsonType())
    )


async def _batches(*batches: pa.RecordBatch) -> collections.abc.AsyncIterator[pa.RecordBatch]:
    for batch in batches:
        yield batch


async def _collect(chunks: collections.abc.AsyncIterator[Chunk]) -> list[Chunk]:
    return [chunk async for chunk in chunks]


class _RecordingRecorder:
    def __init__(self, calls: list[dict[str, typing.Any]], histogram_name: str) -> None:
        self.call: dict[str, typing.Any] = {"histogram_name": histogram_name, "bytes": 0, "exited": False}
        calls.append(self.call)

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.call["exited"] = True

    def add_bytes_processed(self, bytes_processed: int) -> int:
        self.call["bytes"] += bytes_processed
        return self.call["bytes"]


def _recording_factory(calls: list[dict[str, typing.Any]]):
    def factory(histogram_name: str, /, description=None, log_message="", log_attributes=None) -> _RecordingRecorder:
        return _RecordingRecorder(calls, histogram_name)

    return factory


@pytest.mark.parametrize("delimiter", [",", "\t"])
async def test_csv_stream_transformer_writes_rows(delimiter: str) -> None:
    transformer = CSVStreamTransformer(field_names=FIELD_NAMES, delimiter=delimiter, exclude_columns=("loaded_at",))

    chunks = await _collect(transformer.iter(_batches(_record_batch())))

    assert chunks[-1] == Chunk(b"", True)
    rows = list(csv.reader(io.StringIO(b"".join(c.data for c in chunks).decode()), delimiter=delimiter))
    assert rows == [["1", "pageview"], ["2", "signup"]]


async def test_csv_stream_transformer_keeps_every_column_by_default() -> None:
    transformer = CSVStreamTransformer(field_names=FIELD_NAMES)

    chunks = await _collect(transformer.iter(_batches(_record_batch())))

    rows = list(csv.reader(io.StringIO(b"".join(c.data for c in chunks).decode())))
    assert [row[2] for row in rows] == ["2026-01-01 00:00:00+00:00", "2026-01-02 00:00:00+00:00"]


async def test_jsonl_stream_transformer_decodes_json_columns() -> None:
    transformer = JSONLStreamTransformer(max_workers=1, exclude_columns=("loaded_at",))

    chunks = await _collect(transformer.iter(_batches(_record_batch())))

    lines = [json.loads(line) for line in b"".join(c.data for c in chunks).decode().splitlines()]
    assert lines == [
        {"id": 1, "event": "pageview", "properties": {"path": "/", "count": 1}},
        {"id": 2, "event": "signup", "properties": {}},
    ]


@pytest.mark.parametrize("record", [True, False])
async def test_parquet_stream_transformer_writes_rows(record: bool) -> None:
    calls: list[dict[str, typing.Any]] = []
    transformer = ParquetStreamTransformer(
        max_buffered_arrow_bytes=1,
        exclude_columns=("loaded_at",),
        execution_time_recorder=_recording_factory(calls) if record else None,
    )
    batch = _record_batch()

    chunks = await _collect(transformer.iter(_batches(batch, batch)))

    assert chunks[-1].is_eof
    table = pq.read_table(io.BytesIO(b"".join(c.data for c in chunks)))
    assert table.column_names == ["id", "event", "properties"]
    assert table.column("properties").to_pylist() == ['{"path": "/", "count": 1}', "{}"] * 2
    if record:
        assert [call["histogram_name"] for call in calls] == [
            "parquet_stream_transformer_record_batch_transform_duration"
        ] * 2
        assert all(call["exited"] and call["bytes"] > 0 for call in calls)
    else:
        assert calls == []


async def test_serialized_stream_transformer_records_each_batch() -> None:
    calls: list[dict[str, typing.Any]] = []
    batch = _record_batch()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        transformer = SerializedStreamTransformer(
            pool=pool,  # type: ignore[arg-type]
            execution_time_recorder=_recording_factory(calls),
        )
        chunks = await _collect(transformer.iter(_batches(batch, batch)))

    restored = [pa.ipc.read_record_batch(pa.py_buffer(c.data), batch.schema) for c in chunks if c.data]
    assert [b.column("id").to_pylist() for b in restored] == [[1, 2], [1, 2]]
    assert [call["bytes"] for call in calls] == [batch.nbytes, batch.nbytes]
    assert all(call["histogram_name"] == "serialized_transformer_record_batch_transform_duration" for call in calls)


@pytest.mark.parametrize(
    "list_formatter, expected",
    [
        (None, '["a", "b"]'),
        (lambda values: "{" + ",".join(values) + "}", "{a,b}"),
    ],
)
async def test_csv_stream_transformer_renders_lists_with_the_formatter(list_formatter, expected: str) -> None:
    kwargs = {} if list_formatter is None else {"list_formatter": list_formatter}
    transformer = CSVStreamTransformer(field_names=["tags"], **kwargs)
    batch = pa.RecordBatch.from_pylist([{"tags": ["a", "b"]}])

    chunks = await _collect(transformer.iter(_batches(batch)))

    assert list(csv.reader(io.StringIO(b"".join(c.data for c in chunks).decode()), escapechar="\\")) == [[expected]]


@pytest.mark.parametrize(
    "properties_type, json_columns",
    [
        (JsonType(), ()),
        (pa.json_(), ()),
        (pa.string(), ("properties",)),
    ],
)
async def test_parquet_stream_transformer_skips_statistics_for_json_columns(
    properties_type: pa.DataType, json_columns: tuple[str, ...]
) -> None:
    batch = pa.RecordBatch.from_pydict(
        {"id": [1], "properties": pa.array(['{"a": 1}'], type=pa.string()).cast(properties_type)}
    )
    transformer = ParquetStreamTransformer(json_columns=json_columns)

    chunks = await _collect(transformer.iter(_batches(batch)))

    row_group = pq.ParquetFile(io.BytesIO(b"".join(c.data for c in chunks))).metadata.row_group(0)
    assert row_group.column(0).statistics is not None
    assert row_group.column(1).statistics is None
