import contextlib
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import botocore.exceptions
from parameterized import parameterized

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports import util as util_module
from products.warehouse_sources.backend.temporal.data_imports.util import (
    NonRetryableException,
    _is_transient_s3_connection_error,
    prepare_s3_files_for_querying,
)

_UTIL_MODULE = "products.warehouse_sources.backend.temporal.data_imports.util"


def test_non_retryable_exception_is_non_reportable_error():
    # Every NonRetryableException raise site (handle_non_retryable_error, custom-source config
    # errors, CDC failure classification) already vetted the error as a known customer/upstream
    # condition before raising it. Subclassing NonReportableError is what keeps that already-known
    # condition out of error tracking; without it, the activity interceptor reports a fresh
    # "bug" for every occurrence of an error a source already classified as non-retryable.
    assert issubclass(NonRetryableException, NonReportableError)


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

    async def test_retries_with_fresh_listing_when_source_file_vanishes_mid_copy(self):
        # A concurrent compact/vacuum pass on the same Delta table can delete a source file
        # between get_file_uris() listing it and this copy step reading it, raising
        # FileNotFoundError. Regression for that race: https://github.com/PostHog/posthog
        vanished_file = "s3://bucket/job/my_table/part-0.parquet"
        cp_file = AsyncMock(side_effect=[FileNotFoundError(vanished_file), None])
        s3 = _fake_s3(_cp_file=cp_file)
        refresh_file_uris = AsyncMock(return_value=["s3://bucket/job/my_table/part-1.parquet"])

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=[vanished_file],
                delete_existing=False,
                refresh_file_uris=refresh_file_uris,
            )

        refresh_file_uris.assert_awaited_once()
        assert cp_file.await_args_list[-1].args[0] == "s3://bucket/job/my_table/part-1.parquet"

    async def test_retries_past_a_second_consecutive_vanished_file(self):
        # Regression for a race where a zombie compact/vacuum pass outlived a single retry:
        # the source file vanished on both the first attempt and the retry (a different file
        # each time), which a retry-once loop would give up on instead of trying a third time.
        cp_file = AsyncMock(
            side_effect=[
                FileNotFoundError("s3://bucket/job/my_table/part-0.parquet"),
                FileNotFoundError("s3://bucket/job/my_table/part-1.parquet"),
                None,
            ]
        )
        s3 = _fake_s3(_cp_file=cp_file)
        refresh_file_uris = AsyncMock(
            side_effect=[
                ["s3://bucket/job/my_table/part-1.parquet"],
                ["s3://bucket/job/my_table/part-2.parquet"],
            ]
        )

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                delete_existing=False,
                refresh_file_uris=refresh_file_uris,
            )

        assert refresh_file_uris.await_count == 2
        assert cp_file.await_args_list[-1].args[0] == "s3://bucket/job/my_table/part-2.parquet"

    async def test_gives_up_after_max_attempts_exhausted(self):
        # The retry loop is bounded: a source file that keeps vanishing on every attempt must
        # eventually raise instead of retrying forever.
        cp_file = AsyncMock(side_effect=FileNotFoundError("s3://bucket/job/my_table/part-0.parquet"))
        s3 = _fake_s3(_cp_file=cp_file)
        refresh_file_uris = AsyncMock(return_value=["s3://bucket/job/my_table/part-0.parquet"])

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(FileNotFoundError):
                await prepare_s3_files_for_querying(
                    folder_path="job",
                    table_name="my_table",
                    file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                    delete_existing=False,
                    refresh_file_uris=refresh_file_uris,
                )

        assert cp_file.await_count == util_module._COPY_FILES_MAX_ATTEMPTS
        assert refresh_file_uris.await_count == util_module._COPY_FILES_MAX_ATTEMPTS - 1

    async def test_retry_backoff_outlasts_documented_worst_case_compaction_time(self):
        # A zombie compact+vacuum pass can keep deleting source files for as long as its own
        # rewrite takes - documented up to ~45s for a pathological table in
        # core/delta/maintenance.py. Regression for the retry budget silently falling back under
        # that documented worst case (it did: 4 attempts only covered ~14s of backoff).
        cp_file = AsyncMock(side_effect=FileNotFoundError("s3://bucket/job/my_table/part-0.parquet"))
        s3 = _fake_s3(_cp_file=cp_file)
        refresh_file_uris = AsyncMock(return_value=["s3://bucket/job/my_table/part-0.parquet"])
        sleeps: list[float] = []

        async def _record_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", side_effect=_record_sleep),
        ):
            with pytest.raises(FileNotFoundError):
                await prepare_s3_files_for_querying(
                    folder_path="job",
                    table_name="my_table",
                    file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                    delete_existing=False,
                    refresh_file_uris=refresh_file_uris,
                )

        assert sum(sleeps) > 45

    async def test_propagates_vanished_source_file_without_refresh_callback(self):
        # Callers that don't pass refresh_file_uris keep today's behavior: the race still
        # surfaces as an error instead of being retried blindly.
        s3 = _fake_s3(_cp_file=AsyncMock(side_effect=FileNotFoundError("gone")))

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            with pytest.raises(FileNotFoundError):
                await prepare_s3_files_for_querying(
                    folder_path="job",
                    table_name="my_table",
                    file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                    delete_existing=False,
                )

    async def test_retries_transient_s3_internal_error_during_copy(self):
        # S3's CopyObject can return its own InternalError after boto's own request retries are
        # already exhausted, which s3fs surfaces as a bare OSError. Regression for that surfacing
        # straight through the activity instead of retrying the (idempotent) copy batch.
        transient_error = OSError("[Errno 121] We encountered an internal error. Please try again.")
        cp_file = AsyncMock(side_effect=[transient_error, None])
        s3 = _fake_s3(_cp_file=cp_file)

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                delete_existing=False,
            )

        assert cp_file.await_count == 2

    async def test_propagates_non_transient_os_error_without_retry(self):
        # A genuine OSError that isn't a recognized transient S3 blip must surface immediately -
        # otherwise a real bug would burn through the retry budget before being reported.
        cp_file = AsyncMock(side_effect=OSError("Permission denied: bucket policy forbids this operation"))
        s3 = _fake_s3(_cp_file=cp_file)

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            with pytest.raises(OSError):
                await prepare_s3_files_for_querying(
                    folder_path="job",
                    table_name="my_table",
                    file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                    delete_existing=False,
                )

        assert cp_file.await_count == 1

    async def test_tolerates_job_folder_missing_on_first_materialization(self):
        # A brand new table/model has no prior content in S3, so listing the job folder to
        # find old timestamped query folders to clean up raises FileNotFoundError (s3fs's
        # `_ls` behavior for a prefix with zero objects under it). That's an expected first-run
        # state, not a failure - regresses the crash this caused on first materialization.
        s3 = _fake_s3(_ls=AsyncMock(side_effect=FileNotFoundError("job")))

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=["s3://bucket/job/my_table/part-0.parquet"],
                delete_existing=True,
                use_timestamped_folders=True,
            )

        s3._cp_file.assert_awaited_once()


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
