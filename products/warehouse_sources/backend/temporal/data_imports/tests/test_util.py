import re
import errno
import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import (
    OperationalError as DjangoOperationalError,
    ProgrammingError,
)

import psycopg
import botocore.exceptions
import deltalake.exceptions
from parameterized import parameterized

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports import util as util_module
from products.warehouse_sources.backend.temporal.data_imports.query_folder_state import QueryFolderPointerHistory
from products.warehouse_sources.backend.temporal.data_imports.util import (
    _INTERNAL_DB_MAX_ATTEMPTS,
    NonRetryableException,
    S3OperationError,
    _is_transient_s3_connection_error,
    prepare_s3_files_for_querying,
    retry_internal_db_operation,
    with_internal_db_retries,
)

# An S3 throttling response, in the two shapes it reaches these helpers in: translated by s3fs into
# an OSError carrying errno EBUSY, and as the untranslated botocore ClientError.
_THROTTLING_ERRORS = [
    ("os_error_ebusy", OSError(errno.EBUSY, "Reduce your request rate for this prefix.")),
    (
        "untranslated_client_error",
        botocore.exceptions.ClientError(
            {"Error": {"Code": "SlowDown", "Message": "Reduce your request rate for this prefix."}}, "DeleteObjects"
        ),
    ),
]

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
        "_find": AsyncMock(return_value={}),
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

    async def test_retries_when_refresh_file_uris_hits_the_same_table_race(self):
        # `refresh_file_uris` reopens the same Delta table it's re-listing, so it can lose the same
        # compact/vacuum race the copy above did - delta-rs raises that as `TableNotFoundError`
        # ("No files in log segment"), not `FileNotFoundError`/`OSError`, so it used to escape this
        # loop uncaught on the very first unlucky refresh instead of being retried like the race above.
        vanished_file = "s3://bucket/job/my_table/part-0.parquet"
        cp_file = AsyncMock(side_effect=[FileNotFoundError(vanished_file), FileNotFoundError(vanished_file), None])
        s3 = _fake_s3(_cp_file=cp_file)
        refresh_file_uris = AsyncMock(
            side_effect=[
                deltalake.exceptions.TableNotFoundError("Generic delta kernel error: No files in log segment"),
                [vanished_file],
            ]
        )

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=[vanished_file],
                delete_existing=False,
                refresh_file_uris=refresh_file_uris,
            )

        assert refresh_file_uris.await_count == 2
        assert cp_file.await_count == 3

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

    @parameterized.expand(
        [
            # S3's CopyObject can return its own InternalError after boto's own request retries are
            # already exhausted, which s3fs surfaces as a bare OSError.
            ("internal_error", OSError("[Errno 121] We encountered an internal error. Please try again.")),
            # A throttled CopyObject is the same class of blip. It is recognized by the errno s3fs
            # translates every back-off response code to, so a store whose wording the message
            # needles don't match is still retried rather than failing the sync.
            ("throttled", OSError(errno.EBUSY, "Reduce your request rate for this prefix.")),
            # AWS omits the error code from a HeadObject response body, so s3fs's _cp_file (which
            # HEADs the destination) raises the same bare PermissionError for a brief
            # credential-resolution race as it does for a genuine denial. Regression: this used to
            # fail the whole sync on the first attempt instead of retrying, unlike the identical
            # ambiguity _purge_s3_prefix already retries.
            ("credential_resolution_race", PermissionError("Forbidden")),
        ]
    )
    async def test_retries_transient_s3_error_during_copy(self, name: str, transient_error: OSError):
        # Regression for these surfacing straight through the activity instead of retrying the
        # (idempotent) copy batch.
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

    @parameterized.expand(
        [
            # s3fs maps every S3 auth-failure code onto PermissionError, with the server's own
            # message and no errno.
            ("access_denied", PermissionError("Access Denied: s3://example-bucket/job/widgets/part-0.parquet")),
            # An object store with no free space rejects the CopyObject under a code s3fs has no
            # mapping for, so it arrives as a bare OSError with errno EIO.
            (
                "storage_backend_full",
                OSError(
                    errno.EIO,
                    "An error occurred (StorageFull) when calling the CopyObject operation on "
                    "s3://example-bucket/job/widgets/part-0.parquet: the storage backend is out of free space.",
                ),
            ),
        ]
    )
    async def test_reports_fatal_copy_failure_without_the_bucket_or_key(self, name: str, fatal_error: OSError):
        # A failure a retry can't fix must surface immediately rather than burning the retry budget,
        # and it must not surface as the raw s3fs text: that text names our bucket and one team's
        # object key, and an unclassified activity failure's message is both the error the customer
        # reads and the title error tracking groups on.
        cp_file = AsyncMock(side_effect=fatal_error)
        s3 = _fake_s3(_cp_file=cp_file)

        with patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            with pytest.raises(S3OperationError) as raised:
                await prepare_s3_files_for_querying(
                    folder_path="job",
                    table_name="widgets",
                    file_uris=["s3://example-bucket/job/widgets/part-0.parquet"],
                    delete_existing=False,
                )

        assert cp_file.await_count == 1
        assert "query folder" in str(raised.value)
        assert "example-bucket" not in str(raised.value)
        assert raised.value.__cause__ is fatal_error

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


_JOB_URI = f"{settings.BUCKET_URL}/job"
_JOB_KEY = _JOB_URI.split("://", 1)[-1]
_TIMESTAMPED_FOLDER = re.compile(r"^my_table__query_\d+_[0-9a-f]{8}$")


def _live(*names: str) -> list[str]:
    return [f"{_JOB_URI}/my_table/{name}" for name in names]


def _standby_listing(folder: str, *names: str) -> dict[str, dict]:
    return {
        f"{_JOB_KEY}/{folder}/{name}": {"Key": f"{_JOB_KEY}/{folder}/{name}", "type": "file", "size": 1}
        for name in names
    }


def _job_folder_listing(*folders: str) -> list[dict]:
    return [{"Key": f"{_JOB_KEY}/{folder}", "type": "directory"} for folder in folders]


def _stale_epoch() -> int:
    return int((datetime.now(UTC) - timedelta(seconds=util_module.S3_DELETE_TIME_BUFFER * 2)).timestamp())


_LONG_AGO = datetime.now(UTC) - timedelta(seconds=util_module.S3_DELETE_TIME_BUFFER * 2)
_MOMENTS_AGO = datetime.now(UTC) - timedelta(seconds=30)
_SLOT_A, _SLOT_B, _SLOT_C = "my_table__query_a", "my_table__query_b", "my_table__query_c"


def _history(
    active: str | None,
    *,
    inactive: dict[str, datetime] | None = None,
    history_since: datetime = _LONG_AGO,
) -> QueryFolderPointerHistory:
    return QueryFolderPointerHistory(
        active=active,
        active_since=_MOMENTS_AGO,
        active_job_id="job",
        history_since=history_since,
        inactive_since=inactive or {},
    )


def _find_returning(listings: dict[str, dict[str, dict]]) -> AsyncMock:
    async def _find(path: str, detail: bool = True) -> dict[str, dict]:
        folder = path.rstrip("/").split("/")[-1]
        if folder not in listings:
            raise FileNotFoundError(path)
        return listings[folder]

    return AsyncMock(side_effect=_find)


async def _prepare_double_buffered(
    s3: SimpleNamespace,
    *,
    existing: str | None,
    history: QueryFolderPointerHistory | None,
    file_uris: list[str],
    double_buffer: bool = True,
) -> str:
    with (
        patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        return await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="my_table",
            file_uris=file_uris,
            existing_queryable_folder=existing,
            double_buffer=double_buffer,
            pointer_history=history,
        )


class TestDoubleBufferedQueryFolders:
    def _copied(self, s3: SimpleNamespace) -> set[str]:
        return {call.args[1] for call in s3._cp_file.await_args_list}

    @parameterized.expand(
        [
            # A table with no pointer yet, and one still on a timestamped folder, both start on slot a.
            ("new_table", None, None, _SLOT_A),
            (
                "migrating_from_timestamped_folder",
                "my_table__query_1700000000_0badf00d",
                _history("my_table__query_1700000000_0badf00d"),
                _SLOT_A,
            ),
            # The rotation fills every empty slot before it rewrites one that held a generation.
            ("second_sync_fills_b", _SLOT_A, _history(_SLOT_A), _SLOT_B),
            (
                "third_sync_fills_c_before_reusing_a",
                _SLOT_B,
                _history(_SLOT_B, inactive={_SLOT_A: _MOMENTS_AGO}),
                _SLOT_C,
            ),
        ]
    )
    async def test_fills_the_least_recently_used_empty_slot_in_full(
        self, _name: str, existing: str | None, history: QueryFolderPointerHistory | None, expected: str
    ):
        s3 = _fake_s3(_find=_find_returning({}))

        folder = await _prepare_double_buffered(s3, existing=existing, history=history, file_uris=_live("p0", "p1"))

        assert folder == expected
        assert self._copied(s3) == {f"{_JOB_URI}/{expected}/p0", f"{_JOB_URI}/{expected}/p1"}
        s3._rm.assert_not_awaited()

    async def test_reconciles_the_slot_that_stopped_being_read_longest_ago(self):
        # Steady-state rotation a -> b -> c -> a: with c active, a stopped being the pointer when b
        # took over, one whole sync interval before c did, so a is the slot to rewrite. The rewrite
        # pays for the files that changed, not for every live file, and a file that stopped being live
        # leaves the slot before readers are pointed at it, or the glob returns its rows twice.
        s3 = _fake_s3(
            _find=_find_returning(
                {_SLOT_A: _standby_listing(_SLOT_A, "p1", "stale"), _SLOT_B: _standby_listing(_SLOT_B, "p1")}
            )
        )
        history = _history(_SLOT_C, inactive={_SLOT_A: _LONG_AGO, _SLOT_B: _MOMENTS_AGO})

        folder = await _prepare_double_buffered(s3, existing=_SLOT_C, history=history, file_uris=_live("p1", "p2"))

        assert folder == _SLOT_A
        assert self._copied(s3) == {f"{_JOB_URI}/{_SLOT_A}/p2"}
        s3._rm.assert_awaited_once_with([f"s3://{_JOB_KEY}/{_SLOT_A}/stale"])

    @parameterized.expand(
        [
            ("stopped_just_past_the_buffer", util_module.S3_DELETE_TIME_BUFFER + 1, _SLOT_A),
            ("stopped_just_inside_the_buffer", util_module.S3_DELETE_TIME_BUFFER - 1, None),
        ]
    )
    async def test_reuses_a_populated_slot_only_once_it_is_older_than_the_buffer(
        self, _name: str, seconds_since_a_stopped: int, expected_slot: str | None
    ):
        # The age that matters is when the slot stopped being the pointer (its successor took over),
        # not when it became the pointer: a reader that started just before the flip may still be
        # globbing it for up to the buffer.
        s3 = _fake_s3(
            _find=_find_returning({_SLOT_A: _standby_listing(_SLOT_A, "p1"), _SLOT_B: _standby_listing(_SLOT_B, "p1")})
        )
        a_stopped = datetime.now(UTC) - timedelta(seconds=seconds_since_a_stopped)
        history = _history(_SLOT_C, inactive={_SLOT_A: a_stopped, _SLOT_B: _MOMENTS_AGO})

        folder = await _prepare_double_buffered(s3, existing=_SLOT_C, history=history, file_uris=_live("p1", "p2"))

        if expected_slot is None:
            assert _TIMESTAMPED_FOLDER.match(folder)
            assert self._copied(s3) == {f"{_JOB_URI}/{folder}/p1", f"{_JOB_URI}/{folder}/p2"}
        else:
            assert folder == expected_slot
            assert self._copied(s3) == {f"{_JOB_URI}/{expected_slot}/p2"}

    async def test_skips_a_recently_read_populated_slot_for_an_empty_one(self):
        # After an unrecorded pointer move the history restarts, so a populated slot with no record
        # is as suspect as one read moments ago. An empty slot has no prefix in S3 and nothing can be
        # reading it, so it is still usable even when it sorts behind the suspect one.
        s3 = _fake_s3(_find=_find_returning({_SLOT_B: _standby_listing(_SLOT_B, "p1")}))
        history = _history(_SLOT_A, inactive={_SLOT_B: _MOMENTS_AGO}, history_since=_MOMENTS_AGO)

        folder = await _prepare_double_buffered(s3, existing=_SLOT_A, history=history, file_uris=_live("p1"))

        assert folder == _SLOT_C
        assert self._copied(s3) == {f"{_JOB_URI}/{_SLOT_C}/p1"}

    async def test_reconcile_diffs_against_a_refreshed_listing_after_a_vanished_source_file(self):
        # A zombie compaction can replace live files between the listing and the copy. The retry must
        # diff the fresh listing against the standby again, otherwise it copies the vanished file
        # forever or leaves the compacted file behind.
        cp_file = AsyncMock(side_effect=[FileNotFoundError("p2"), None])
        s3 = _fake_s3(_cp_file=cp_file, _find=_find_returning({_SLOT_A: _standby_listing(_SLOT_A, "p1")}))
        refresh = AsyncMock(return_value=_live("p1", "compacted"))

        with (
            patch.object(util_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            folder = await prepare_s3_files_for_querying(
                folder_path="job",
                table_name="my_table",
                file_uris=_live("p1", "p2"),
                existing_queryable_folder=_SLOT_C,
                double_buffer=True,
                pointer_history=_history(_SLOT_C, inactive={_SLOT_A: _LONG_AGO, _SLOT_B: _MOMENTS_AGO}),
                refresh_file_uris=refresh,
            )

        assert folder == _SLOT_A
        assert cp_file.await_args_list[-1].args[1] == f"{_JOB_URI}/{_SLOT_A}/compacted"
        s3._rm.assert_not_awaited()

    @parameterized.expand(
        [
            # No record at all: nothing says when a populated slot was last read.
            ("no_history_and_populated_slots", None, None),
            # Every other slot stopped being read within the buffer.
            (
                "all_slots_read_recently",
                _SLOT_C,
                _history(_SLOT_C, inactive={_SLOT_A: _MOMENTS_AGO, _SLOT_B: _MOMENTS_AGO}),
            ),
            # A move this record missed (a crash between pointer write and record, or a schema reset)
            # restarts the history, and unrecorded populated slots are not trusted until it is old.
            ("history_restarted_recently", _SLOT_A, _history(_SLOT_A, history_since=_MOMENTS_AGO)),
        ]
    )
    async def test_falls_back_to_a_fresh_timestamped_folder_when_every_slot_may_still_be_read(
        self, _name: str, existing: str | None, history: QueryFolderPointerHistory | None
    ):
        s3 = _fake_s3(
            _find=_find_returning({slot: _standby_listing(slot, "p1") for slot in (_SLOT_A, _SLOT_B, _SLOT_C)})
        )

        folder = await _prepare_double_buffered(s3, existing=existing, history=history, file_uris=_live("p1", "p2"))

        assert _TIMESTAMPED_FOLDER.match(folder)
        assert self._copied(s3) == {f"{_JOB_URI}/{folder}/p1", f"{_JOB_URI}/{folder}/p2"}
        s3._rm.assert_not_awaited()

    @parameterized.expand([("flag_on", True), ("flag_off", False)])
    async def test_age_based_cleanup_never_removes_the_slot_folders(self, _name: str, double_buffer: bool):
        # Turning the flag off after a table moved onto the slots returns it to timestamped folders;
        # the cleanup must still take the stale timestamped folders and must leave every slot alone,
        # because one of them is what readers are on right now.
        stale = f"my_table__query_{_stale_epoch()}_0badf00d"
        s3 = _fake_s3(
            _ls=AsyncMock(return_value=_job_folder_listing(_SLOT_A, _SLOT_B, _SLOT_C, stale)),
            _find=_find_returning({}),
        )

        folder = await _prepare_double_buffered(
            s3, existing=_SLOT_A, history=_history(_SLOT_A), file_uris=_live("p1"), double_buffer=double_buffer
        )

        if double_buffer:
            assert folder == _SLOT_B
        else:
            assert _TIMESTAMPED_FOLDER.match(folder)
        s3._rm.assert_awaited_once_with(f"{_JOB_KEY}/{stale}", recursive=True)

    async def test_a_failed_stale_file_delete_raises_instead_of_returning_the_standby(self):
        # The old-folder cleanup is best effort because nobody is pointed at those folders. A stale
        # file left in the standby is different: the caller flips readers to it next, so swallowing
        # the failure would publish duplicate rows. Raising keeps the pointer where it is.
        s3 = _fake_s3(
            _find=_find_returning({_SLOT_A: _standby_listing(_SLOT_A, "p1", "stale")}),
            _rm=AsyncMock(side_effect=PermissionError("Access Denied")),
        )
        history = _history(_SLOT_C, inactive={_SLOT_A: _LONG_AGO, _SLOT_B: _MOMENTS_AGO})

        with pytest.raises(S3OperationError):
            await _prepare_double_buffered(s3, existing=_SLOT_C, history=history, file_uris=_live("p1"))


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
async def test_delete_folder_swallows_s3_clock_skew_error(mock_capture_exception: MagicMock) -> None:
    # S3 rejects a signed request whose clock has drifted too far from its own with
    # RequestTimeTooSkewed, which s3fs maps onto the same generic PermissionError as a real access
    # denial. The worker's own clock resyncs and the identical delete succeeds later, so this must
    # not mint an error-tracking issue any more than a connection blip would.
    s3 = _mock_s3()
    s3._rm = AsyncMock(
        side_effect=PermissionError("The difference between the request time and the current time is too large.")
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


@parameterized.expand(_THROTTLING_ERRORS)
@pytest.mark.asyncio
async def test_delete_folder_retries_a_throttled_delete(name: str, throttling_error: BaseException) -> None:
    # One recursive delete of a query folder is a list plus a batched DeleteObjects against a single
    # prefix, which S3 answers with a back-off response when a bulk cleanup outruns its request-rate
    # limit. The delete is idempotent, so it must be retried rather than reported as a failure.
    s3 = _mock_s3()
    s3._rm = AsyncMock(side_effect=[throttling_error, None])

    with (
        _mock_s3_context(s3),
        patch(f"{_UTIL_MODULE}.capture_exception") as mock_capture_exception,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="widgets",
            file_uris=[],
            use_timestamped_folders=False,
            delete_existing=True,
        )

    assert s3._rm.await_count == 2
    mock_capture_exception.assert_not_called()


@pytest.mark.asyncio
async def test_delete_folder_reports_throttling_that_outlasts_the_retry_budget() -> None:
    # The retries are bounded, and a store that keeps throttling us is no longer a blip that clears
    # on its own. Guards the silent-cleanup regression the other direction: the budget running out
    # must still report, and report the sanitized error rather than the raw path.
    throttling_error = OSError(errno.EBUSY, "Reduce your request rate for this prefix.")
    s3 = _mock_s3()
    s3._rm = AsyncMock(side_effect=throttling_error)

    with (
        _mock_s3_context(s3),
        patch(f"{_UTIL_MODULE}.capture_exception") as mock_capture_exception,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="widgets",
            file_uris=[],
            use_timestamped_folders=False,
            delete_existing=True,
        )

    assert s3._rm.await_count == util_module._DELETE_FOLDER_MAX_ATTEMPTS
    mock_capture_exception.assert_called_once()
    captured = mock_capture_exception.call_args.args[0]
    assert isinstance(captured, S3OperationError)
    assert captured.__cause__ is throttling_error


@pytest.mark.asyncio
@patch(f"{_UTIL_MODULE}.capture_exception")
async def test_delete_folder_treats_an_already_deleted_folder_as_done(mock_capture_exception: MagicMock) -> None:
    # Two cleanup passes can pick the same timestamped folder, and s3fs raises FileNotFoundError for
    # a prefix with no objects under it. The folder being gone is what this delete wanted, so it is
    # not worth an error-tracking issue.
    s3 = _mock_s3()
    s3._rm = AsyncMock(side_effect=FileNotFoundError("s3://example-bucket/job/widgets__query_1700000000"))

    with _mock_s3_context(s3):
        await prepare_s3_files_for_querying(
            folder_path="job",
            table_name="widgets",
            file_uris=[],
            use_timestamped_folders=False,
            delete_existing=True,
        )

    s3._rm.assert_awaited_once()
    mock_capture_exception.assert_not_called()


@parameterized.expand(
    [
        (
            "dns_name_not_known",
            DjangoOperationalError("connection failed: [Errno -2] Name or service not known"),
            True,
        ),
        (
            "dns_temporary_failure",
            DjangoOperationalError("connection failed: [Errno -3] Temporary failure in name resolution"),
            True,
        ),
        (
            "dns_no_address_for_hostname",
            DjangoOperationalError("[Errno -5] No address associated with hostname"),
            True,
        ),
        (
            "unwrapped_psycopg_dns_failure",
            psycopg.OperationalError("[Errno -2] Name or service not known"),
            True,
        ),
        (
            "connection_refused",
            DjangoOperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: Connection refused'
            ),
            True,
        ),
        (
            "dropped_backend_connection",
            DjangoOperationalError("server closed the connection unexpectedly"),
            True,
        ),
        (
            "rejected_password",
            DjangoOperationalError('connection failed: FATAL:  password authentication failed for user "fake_user"'),
            False,
        ),
        (
            "missing_column",
            ProgrammingError('column "invented_column" does not exist'),
            False,
        ),
    ]
)
@patch("time.sleep")
@patch(f"{_UTIL_MODULE}.close_stale_db_connections")
def test_retry_internal_db_operation_only_retries_transient_failures(
    _name: str,
    error: Exception,
    is_transient: bool,
    mock_close_connections: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    # Reaching our own database can fail because the host stops resolving for a moment, or
    # refuses the connection while infrastructure moves, and a later attempt gets past it. A
    # rejected password and a missing column arrive through the same psycopg classes and never
    # get better, so they have to fail on the first attempt instead of holding the activity open
    # for the whole backoff budget.
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(type(error)):
        retry_internal_db_operation(operation)

    assert attempts == (_INTERNAL_DB_MAX_ATTEMPTS if is_transient else 1)


@patch("time.sleep")
@patch(f"{_UTIL_MODULE}.close_stale_db_connections")
def test_retry_internal_db_operation_returns_the_result_of_a_later_attempt(
    mock_close_connections: MagicMock, mock_sleep: MagicMock
) -> None:
    # A blip that clears has to leave nothing behind for error tracking, which means the result
    # comes back from the attempt that succeeded. The broken connection is evicted first, so the
    # next attempt reconnects instead of reusing it.
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise DjangoOperationalError("connection failed: [Errno -2] Name or service not known")
        return "resolved"

    assert retry_internal_db_operation(operation) == "resolved"
    assert attempts == 3
    assert mock_close_connections.call_count == 2


@patch("time.sleep")
@patch(f"{_UTIL_MODULE}.close_stale_db_connections")
def test_with_internal_db_retries_retries_with_the_original_arguments(
    mock_close_connections: MagicMock, mock_sleep: MagicMock
) -> None:
    # Activities whose whole body is database work use the decorator form, so the retried attempt
    # has to run with the activity's own inputs rather than with none.
    attempts = 0

    @with_internal_db_retries
    def activity_body(team_id: int) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DjangoOperationalError("connection failed: [Errno -2] Name or service not known")
        return team_id

    assert activity_body(team_id=1234) == 1234
    assert attempts == 2
