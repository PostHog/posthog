from types import SimpleNamespace

from unittest.mock import AsyncMock, patch

from products.warehouse_sources.backend.temporal.data_imports import util as util_module
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying


def _fake_s3(**kwargs):
    defaults = {
        "invalidate_cache": lambda: None,
        "_ls": AsyncMock(return_value=[]),
        "_exists": AsyncMock(return_value=False),
        "_cp_file": AsyncMock(),
        "_copy": AsyncMock(),
        "_rm": AsyncMock(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _FakeS3CM:
    def __init__(self, s3):
        self._s3 = s3

    async def __aenter__(self):
        return self._s3

    async def __aexit__(self, *exc):
        return False


class TestPrepareS3FilesForQuerying:
    async def test_copies_files_with_cp_file_not_copy(self):
        # `_copy()` globs the source and probes whether the destination is a directory,
        # each requiring its own S3 ListObjectsV2 call. Copying many files concurrently
        # through `_copy()` multiplies into enough LIST traffic to trigger S3's SlowDown
        # rate limiting (see the OSError/ClientError SlowDown pair this regresses).
        s3 = _fake_s3()

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=["s3://bucket/job/my_table/part-0.parquet", "s3://bucket/job/my_table/part-1.parquet"],
                delete_existing=False,
            )

        assert s3._cp_file.await_count == 2
        s3._copy.assert_not_awaited()
