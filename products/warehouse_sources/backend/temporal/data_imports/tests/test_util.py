import contextlib
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import botocore.exceptions
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports import util as util_module
from products.warehouse_sources.backend.temporal.data_imports.util import (
    _is_transient_s3_connection_error,
    prepare_s3_files_for_querying,
)

_UTIL_MODULE = "products.warehouse_sources.backend.temporal.data_imports.util"


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


@parameterized.expand(
    [
        (
            "connect_timeout",
            botocore.exceptions.ConnectTimeoutError(endpoint_url="https://example.s3.amazonaws.com"),
            True,
        ),
        (
            "endpoint_connection_error",
            botocore.exceptions.EndpointConnectionError(endpoint_url="https://example.s3.amazonaws.com"),
            True,
        ),
        (
            "read_timeout",
            botocore.exceptions.ReadTimeoutError(endpoint_url="https://example.s3.amazonaws.com"),
            True,
        ),
        (
            "connection_closed",
            botocore.exceptions.ConnectionClosedError(endpoint_url="https://example.s3.amazonaws.com"),
            True,
        ),
        (
            "client_error_access_denied",
            botocore.exceptions.ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject"),
            False,
        ),
        ("generic_value_error", ValueError("some other cleanup failure"), False),
    ]
)
def test_is_transient_s3_connection_error(name: str, error: BaseException, expected: bool) -> None:
    assert _is_transient_s3_connection_error(error) is expected


@contextlib.contextmanager
def _mock_s3_context(mock_s3: AsyncMock):
    """Patch aget_s3_client to yield a mock async context manager wrapping mock_s3."""
    with patch(f"{_UTIL_MODULE}.aget_s3_client") as mock_get_s3:
        mock_get_s3.return_value.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_get_s3.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_get_s3


def _mock_s3() -> AsyncMock:
    s3 = AsyncMock()
    s3.invalidate_cache = MagicMock()
    s3._exists = AsyncMock(return_value=True)
    s3._copy = AsyncMock()
    return s3


@pytest.mark.asyncio
@patch(f"{_UTIL_MODULE}.capture_exception")
async def test_delete_folder_swallows_transient_s3_connection_error(mock_capture_exception: MagicMock) -> None:
    # A best-effort old-folder delete hitting a connect timeout must not mint an error-tracking
    # issue - the folder is timestamped and gets picked up by the next sync's cleanup pass anyway.
    s3 = _mock_s3()
    s3._rm = AsyncMock(
        side_effect=botocore.exceptions.ConnectTimeoutError(endpoint_url="https://example.s3.amazonaws.com")
    )

    with _mock_s3_context(s3):
        await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="events",
            file_uris=[],
            use_timestamped_folders=False,
            delete_existing=True,
        )

    s3._rm.assert_awaited_once()
    mock_capture_exception.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_UTIL_MODULE}.capture_exception")
async def test_delete_folder_still_captures_non_transient_error(mock_capture_exception: MagicMock) -> None:
    # A genuine cleanup failure (not a network blip) must still be reported.
    s3 = _mock_s3()
    s3._rm = AsyncMock(side_effect=ValueError("unexpected failure"))

    with _mock_s3_context(s3):
        await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="events",
            file_uris=[],
            use_timestamped_folders=False,
            delete_existing=True,
        )

    s3._rm.assert_awaited_once()
    mock_capture_exception.assert_called_once()
