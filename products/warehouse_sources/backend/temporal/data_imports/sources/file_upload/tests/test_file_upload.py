import io
from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.file_uploads import build_file_upload_s3_path
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload import (
    file_upload as file_upload_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.file_upload import (
    FILE_TOO_LARGE_ERROR,
    FileUploadSourceManager,
    _read_uploaded_table,
    _rows_from_json,
)

CSV_BYTES = b"name,count\nalpha,1\nbeta,2\n"
JSON_ARRAY_BYTES = b'[{"name":"alpha","count":1},{"name":"beta","count":2}]'
NDJSON_BYTES = b'{"name":"alpha","count":1}\n{"name":"beta","count":2}\n'

EXPECTED = {"name": ["alpha", "beta"], "count": [1, 2]}


def _parquet_bytes() -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table(EXPECTED), buf)
    return buf.getvalue()


class TestRowsFromJson:
    @parameterized.expand(
        [
            ("json_array", JSON_ARRAY_BYTES),
            ("ndjson", NDJSON_BYTES),
            ("ndjson_with_blank_lines", b'{"name":"alpha","count":1}\n\n{"name":"beta","count":2}\n\n'),
        ]
    )
    def test_parses_multi_row_shapes(self, _name: str, data: bytes) -> None:
        assert _rows_from_json(data).to_pydict() == EXPECTED

    def test_parses_single_object_as_one_row(self) -> None:
        assert _rows_from_json(b'{"name":"alpha","count":1}').to_pydict() == {"name": ["alpha"], "count": [1]}


class TestReadUploadedTable:
    @parameterized.expand(
        [
            ("csv", CSV_BYTES),
            ("json", JSON_ARRAY_BYTES),
        ]
    )
    def test_reads_format(self, file_format: str, data: bytes) -> None:
        assert _read_uploaded_table(data, file_format).to_pydict() == EXPECTED

    def test_reads_parquet(self) -> None:
        assert _read_uploaded_table(_parquet_bytes(), "parquet").to_pydict() == EXPECTED

    def test_rejects_unknown_format(self) -> None:
        with pytest.raises(ValueError, match="Unsupported file upload format"):
            _read_uploaded_table(CSV_BYTES, "xlsx")

    def test_rejects_parquet_that_decodes_past_the_size_cap(self) -> None:
        # A small (even compressed) upload can decode to far more than its stored size; the guard must
        # reject it up front rather than materialise it and exhaust the import worker.
        with patch.object(file_upload_module, "MAX_DECODED_BYTES", 1):
            with pytest.raises(ValueError, match=FILE_TOO_LARGE_ERROR):
                _read_uploaded_table(_parquet_bytes(), "parquet")


class TestFileUploadSourceManager:
    def _manager(self, *, team_id: int = 42, file_format: str = "csv") -> FileUploadSourceManager:
        return FileUploadSourceManager(
            team_id=team_id,
            upload_id="upload-abc",
            filename="data.csv",
            file_format=file_format,
            logger=structlog.get_logger(),
        )

    @staticmethod
    def _patched_s3(data: bytes) -> tuple[MagicMock, object]:
        handle = MagicMock()
        handle.read = AsyncMock(return_value=data)
        handle.__aenter__ = AsyncMock(return_value=handle)
        handle.__aexit__ = AsyncMock(return_value=False)

        s3 = MagicMock()
        s3.open_async = AsyncMock(return_value=handle)

        @asynccontextmanager
        async def fake_client():
            yield s3

        return s3, fake_client

    @pytest.mark.asyncio
    async def test_reads_only_from_its_own_teams_prefix(self) -> None:
        s3, fake_client = self._patched_s3(CSV_BYTES)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.file_upload.aget_s3_client",
            fake_client,
        ):
            batches = [batch async for batch in self._manager(team_id=42).get_items()]

        s3.open_async.assert_awaited_once()
        opened_path = s3.open_async.await_args.args[0]
        assert opened_path == build_file_upload_s3_path(42, "upload-abc", "data.csv")
        # The bucket prefix matters: without it s3fs resolves a different location than the upload
        # endpoint wrote to, and every sync reads an empty path.
        assert opened_path.endswith("/file_uploads/team_42/upload-abc/data.csv")
        assert pa.concat_tables(batches).to_pydict() == EXPECTED
