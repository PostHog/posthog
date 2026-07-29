import io
import random
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    CDCBufferWriter,
    build_buffer_file_name,
    get_buffer_prefix,
    parse_buffer_file_name,
)


class TestBufferFileName:
    def test_roundtrip(self):
        name = build_buffer_file_name(256, 512, 3)
        assert parse_buffer_file_name(name) == (256, 512, 3)

    def test_rejects_foreign_names(self):
        assert parse_buffer_file_name("part-0000.parquet") is None
        assert parse_buffer_file_name("schema.json") is None
        assert parse_buffer_file_name("256-512-3.parquet") is None  # unpadded
        assert parse_buffer_file_name(build_buffer_file_name(1, 2, 3).removesuffix(".parquet")) is None

    def test_lexicographic_sort_equals_numeric_sort(self):
        # The consumer's only ordering primitive is a filename sort — padding must
        # make that equal to numeric (start, end, index) order across magnitudes.
        ranges = [(1, 9, 0), (10, 15, 0), (15, 15, 1), (15, 15, 2), (16, 2**63 - 1, 0), (2**40, 2**41, 5)]
        names = [build_buffer_file_name(*r) for r in ranges]
        shuffled = names[:]
        random.Random(42).shuffle(shuffled)
        assert sorted(shuffled) == [build_buffer_file_name(*r) for r in sorted(ranges)]


class TestCDCBufferWriter:
    def _writer_with_captured_files(self) -> tuple[CDCBufferWriter, dict[str, io.BytesIO]]:
        files: dict[str, io.BytesIO] = {}

        @contextmanager
        def fake_open(path, mode):
            buf = io.BytesIO()
            files[path] = buf
            yield buf

        mock_s3 = MagicMock()
        mock_s3.open = fake_open
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.get_s3_client",
                return_value=mock_s3,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.ensure_bucket"),
        ):
            writer = CDCBufferWriter(MagicMock())
        return writer, files

    def _table(self, seqs: list[int]) -> pa.Table:
        return pa.table(
            {
                "id": pa.array(range(len(seqs)), type=pa.int64()),
                CDC_SEQ_COLUMN: pa.array(seqs, type=pa.int64()),
            }
        )

    def test_writes_window_file_with_range_from_seq_column(self):
        writer, files = self._writer_with_captured_files()
        result = writer.write_batch(team_id=1, schema_id="abc", table=self._table([512, 256, 300]), file_index=2)

        assert result.start_seq == 256
        assert result.end_seq == 512
        assert result.row_count == 3
        assert result.s3_path == f"{get_buffer_prefix(1, 'abc')}/{build_buffer_file_name(256, 512, 2)}"

        assert len(files) == 1
        written = pq.read_table(io.BytesIO(next(iter(files.values())).getvalue()))
        assert written.column(CDC_SEQ_COLUMN).to_pylist() == [512, 256, 300]

    def test_rejects_empty_table(self):
        writer, _files = self._writer_with_captured_files()
        with pytest.raises(ValueError, match="empty"):
            writer.write_batch(team_id=1, schema_id="abc", table=self._table([]), file_index=0)

    def test_rejects_table_without_seq_column(self):
        writer, _files = self._writer_with_captured_files()
        table = pa.table({"id": pa.array([1], type=pa.int64())})
        with pytest.raises(ValueError, match=CDC_SEQ_COLUMN):
            writer.write_batch(team_id=1, schema_id="abc", table=table, file_index=0)
