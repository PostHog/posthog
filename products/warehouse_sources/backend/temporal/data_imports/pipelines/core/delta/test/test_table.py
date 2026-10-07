import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import deltalake
import deltalite
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.deltalite_handles import (
    DeltaLiteHandleCache,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    _PURGE_S3_PREFIX_MAX_ATTEMPTS,
    DeltaTableRef,
    _purge_s3_prefix,
    live_row_count,
    live_size_mib,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
    make_logger,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    _live_delta_size_mib,
)

_TABLE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"


def table_ref():
    return DeltaTableRef(resource_name="test_resource", job=MagicMock(), logger=make_logger())


def _openable_table_ref(delta_uri: str) -> DeltaTableRef:
    ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
    patch.object(ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)).start()
    patch.object(ref, "_get_credentials", MagicMock(return_value={})).start()
    return ref


class TestGetDeltaTableCache:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    @pytest.mark.asyncio
    async def test_one_ref_cannot_evict_another_refs_handle(self):
        # A loader process has several tables in flight. When they shared one cache slot, every
        # interleaved call re-opened its table (a full Delta-log replay against object storage).
        first = _openable_table_ref("s3://bucket/team/job/first")
        second = _openable_table_ref("s3://bucket/team/job/second")

        with patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table:
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = lambda table_uri, storage_options: MagicMock(uri=table_uri)

            first_handle = await first.get_delta_table()
            await second.get_delta_table()
            assert await first.get_delta_table() is first_handle
            assert await second.get_delta_table() is not first_handle

        assert mock_delta_table.call_count == 2

    @parameterized.expand([("invalidate", "invalidate_cached_table"), ("pop", "pop_cached_table")])
    @pytest.mark.asyncio
    async def test_dropping_the_handle_forces_a_fresh_open(self, _name: str, method: str):
        # Reset and repartition rewrite the files under the table, so a caller that drops the handle
        # must get the live log on its next read rather than the pre-swap snapshot.
        ref = _openable_table_ref("s3://bucket/team/job/t")

        with patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table:
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = lambda table_uri, storage_options: MagicMock(
                version=MagicMock(return_value=1)
            )

            stale = await ref.get_delta_table()
            ref.note_deltalite_commit(9)
            getattr(ref, method)()
            fresh = cast(MagicMock, await ref.get_delta_table())

        assert fresh is not stale
        assert mock_delta_table.call_count == 2
        # The deltalite commit belonged to the dropped incarnation: the fresh open is current as is,
        # and the old version must not outrank the new table's own.
        fresh.update_incremental.assert_not_called()
        assert ref.latest_known_version(fresh) == 1

    @pytest.mark.asyncio
    async def test_a_deltalite_commit_is_caught_up_on_the_next_read_only(self):
        # deltalite commits past the delta-rs handle. A reader of the version or the file list
        # (post-load, maintenance) must see that commit; a reader that opts out must not pay the
        # log read for it; and the catch-up happens once, not on every later call.
        ref = _openable_table_ref("s3://bucket/team/job/t")

        with patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table:
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = lambda table_uri, storage_options: MagicMock(
                version=MagicMock(return_value=3)
            )

            handle = cast(MagicMock, await ref.get_delta_table())
            ref.note_deltalite_commit(4)

            assert await ref.get_delta_table(allow_stale=True) is handle
            handle.update_incremental.assert_not_called()
            assert ref.latest_known_version(handle) == 4

            assert await ref.get_delta_table() is handle
            handle.update_incremental.assert_called_once()
            await ref.get_delta_table()
            handle.update_incremental.assert_called_once()

        assert mock_delta_table.call_count == 1

    @parameterized.expand(
        [
            ("transient_blip", OSError("Generic S3 error: connection reset"), TransientObjectStoreError, False),
            ("other_error", RuntimeError("something else went wrong"), RuntimeError, True),
        ]
    )
    @pytest.mark.asyncio
    async def test_a_failed_catch_up_keeps_the_handle_behind(
        self, _name: str, error: Exception, expected: type[Exception], captured: bool
    ):
        # A refresh that fails must not clear the mark, or the next reader would trust a snapshot
        # that is known to be behind the log. Classification mirrors the open path so a transient
        # blip is not reported as a defect.
        ref = _openable_table_ref("s3://bucket/team/job/t")

        with (
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{self._MODULE}.capture_exception") as capture,
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = lambda table_uri, storage_options: MagicMock()

            handle = cast(MagicMock, await ref.get_delta_table())
            handle.update_incremental.side_effect = [error, None]
            ref.note_deltalite_commit(4)

            with pytest.raises(expected):
                await ref.get_delta_table()
            assert await ref.get_delta_table() is handle

        assert handle.update_incremental.call_count == 2
        assert capture.called is captured

    @pytest.mark.asyncio
    async def test_pop_never_opens_the_table(self):
        # End-of-run cleanup pops the handle. If the table was never fetched, a pop that opened it
        # would make an object-storage call whose failure could mask the import error being handled.
        ref = _openable_table_ref("s3://bucket/team/job/t")

        with patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table:
            assert ref.pop_cached_table() is None

        mock_delta_table.is_deltatable.assert_not_called()
        mock_delta_table.assert_not_called()


def _no_table(path: Path) -> None:
    pass


def _data_file_only(path: Path) -> None:
    path.mkdir(parents=True)
    pq.write_table(pa.table({"id": [1]}), path / "part-0.parquet")


def _stray_log_file(path: Path) -> None:
    (path / "_delta_log").mkdir(parents=True)
    (path / "_delta_log" / "_commit_0.json.tmp").write_text("{}")


def _checkpoint_hint_only(path: Path) -> None:
    (path / "_delta_log").mkdir(parents=True)
    (path / "_delta_log" / "_last_checkpoint").write_text('{"version": 5, "size": 10}')


def _commit_without_metadata(path: Path) -> None:
    (path / "_delta_log").mkdir(parents=True)
    (path / "_delta_log" / "00000000000000000000.json").write_text('{"commitInfo": {"timestamp": 1}}\n')


def _files_under(path: Path) -> set[str]:
    return {str(file.relative_to(path)) for file in path.rglob("*") if file.is_file()}


class TestOpenWithoutExistenceCheck:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    @parameterized.expand(
        [
            # (name, expect_missing, table_exists, existence_checks, opens)
            ("existing_table_opens_with_no_check", False, True, 0, 1),
            ("expected_missing_table_costs_one_check", True, False, 1, 0),
            ("unexpected_missing_table_falls_back_to_the_check", False, False, 1, 1),
            ("expected_missing_but_present_checks_then_opens", True, True, 1, 1),
        ]
    )
    @pytest.mark.asyncio
    async def test_object_store_calls_for_one_open(
        self, _name: str, expect_missing: bool, table_exists: bool, existence_checks: int, opens: int
    ) -> None:
        ref = DeltaTableRef("t", MagicMock(), make_logger(), expect_missing=expect_missing)
        handle = MagicMock()

        with (
            patch.object(ref, "_get_delta_table_uri", AsyncMock(return_value="s3://bucket/team/job/t")),
            patch.object(ref, "_get_credentials", MagicMock(return_value={})),
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table,
        ):
            mock_delta_table.is_deltatable.return_value = table_exists
            if table_exists:
                mock_delta_table.return_value = handle
            else:
                mock_delta_table.side_effect = deltalake.exceptions.TableNotFoundError(
                    "Generic delta kernel error: No files in log segment"
                )

            table = await ref.get_delta_table()

        assert table is (handle if table_exists else None)
        assert ref.is_first_sync is not table_exists
        assert mock_delta_table.is_deltatable.call_count == existence_checks
        assert mock_delta_table.call_count == opens

    @parameterized.expand(
        [
            (f"{layout.__name__.strip('_')}_{'expected' if expect_missing else 'unexpected'}", layout, expect_missing)
            for layout in (_no_table, _data_file_only, _stray_log_file, _checkpoint_hint_only)
            for expect_missing in (False, True)
        ]
    )
    @pytest.mark.asyncio
    async def test_a_prefix_that_holds_no_table_reads_as_no_table_and_keeps_its_files(
        self, _name: str, layout: Callable[[Path], None], expect_missing: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table"
            layout(path)
            before = _files_under(path)
            ref = DeltaTableRef("t", MagicMock(), make_logger(), expect_missing=expect_missing)

            with (
                patch.object(ref, "_get_delta_table_uri", AsyncMock(return_value=str(path))),
                patch.object(ref, "_get_credentials", MagicMock(return_value={})),
                patch(f"{self._MODULE}._purge_s3_prefix", AsyncMock()) as purge,
            ):
                assert await ref.get_delta_table() is None
                assert await ref.is_table_corrupted() is False

            assert ref.is_first_sync is True
            purge.assert_not_awaited()
            assert _files_under(path) == before

    @parameterized.expand([("unexpected", False), ("expected", True)])
    @pytest.mark.asyncio
    async def test_a_log_with_no_metadata_is_still_corrupt_and_still_healed(
        self, _name: str, expect_missing: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table"
            _commit_without_metadata(path)
            ref = DeltaTableRef("t", MagicMock(), make_logger(), expect_missing=expect_missing)
            s3_cm = MagicMock(__aenter__=AsyncMock(return_value=MagicMock()), __aexit__=AsyncMock(return_value=False))

            with (
                patch.object(ref, "_get_delta_table_uri", AsyncMock(return_value=str(path))),
                patch.object(ref, "_get_credentials", MagicMock(return_value={})),
                patch(f"{self._MODULE}.aget_s3_client", MagicMock(return_value=s3_cm)),
                patch(f"{self._MODULE}._purge_s3_prefix", AsyncMock()) as purge,
                patch(f"{self._MODULE}.capture_exception"),
            ):
                assert await ref.is_table_corrupted() is True
                assert await ref.get_delta_table() is None

            purge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_makes_the_next_open_start_with_the_existence_check(self) -> None:
        ref = DeltaTableRef("t", MagicMock(), make_logger())
        s3_cm = MagicMock(__aenter__=AsyncMock(return_value=MagicMock()), __aexit__=AsyncMock(return_value=False))

        with (
            patch.object(ref, "_get_delta_table_uri", AsyncMock(return_value="s3://bucket/team/job/t")),
            patch.object(ref, "_get_credentials", MagicMock(return_value={})),
            patch(f"{self._MODULE}.aget_s3_client", MagicMock(return_value=s3_cm)),
            patch(f"{self._MODULE}._purge_s3_prefix", AsyncMock()),
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_delta_table,
        ):
            mock_delta_table.is_deltatable.return_value = False
            await ref.reset_table()

            assert await ref.get_delta_table() is None

        mock_delta_table.assert_not_called()
        mock_delta_table.is_deltatable.assert_called_once()


class TestKnownMissingTable:
    @parameterized.expand(
        [
            # (name, allow_known_missing, step between the two reads, probes, second read finds a table)
            ("default_read_looks_again", False, "nothing", 2, False),
            ("allowed_read_reuses_the_answer", True, "nothing", 1, False),
            ("default_read_finds_a_table_another_writer_created", False, "created_elsewhere", 2, True),
            ("adopted_table_is_returned_with_no_probe", True, "adopted", 1, True),
            ("invalidate_forgets_the_answer", True, "invalidated", 2, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_second_read_of_a_missing_table(
        self, _name: str, allow_known_missing: bool, step: str, probes: int, finds_table: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            uri = str(Path(tmp) / "table")
            ref = make_local_table_ref(uri)

            with patch.object(ref, "_open_delta_table", AsyncMock(side_effect=ref._open_delta_table)) as probe:
                assert await ref.get_delta_table() is None

                if step == "created_elsewhere":
                    deltalake.write_deltalake(uri, pa.table({"id": [1]}))
                elif step == "adopted":
                    ref.adopt_created_table(deltalake.DeltaTable.create(uri, schema=pa.schema([("id", pa.int64())])))
                elif step == "invalidated":
                    ref.invalidate_cached_table()

                table = await ref.get_delta_table(allow_known_missing=allow_known_missing)

            assert (table is not None) is finds_table
            assert probe.await_count == probes


class TestStorageOptionsCommitSafety:
    # Re-adding AWS_S3_ALLOW_UNSAFE_RENAME unconditionally would silently restore
    # the legacy rename backend, which has no commit-conflict detection.
    @parameterized.expand(
        [
            ("production_default_safe", False, False),
            ("production_rollback_escape_hatch", False, True),
            ("local_default_safe", True, False),
        ]
    )
    def test_conditional_put_on_unsafe_rename_gated(
        self, _case: str, use_local_setup: bool, allow_unsafe: bool
    ) -> None:
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())

        with (
            override_settings(
                USE_LOCAL_SETUP=use_local_setup,
                DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME=allow_unsafe,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table.ensure_bucket_exists"
            ),
        ):
            options = table_ref.get_storage_options()

        assert options["conditional_put"] == "etag"
        assert ("AWS_S3_ALLOW_UNSAFE_RENAME" in options) is allow_unsafe

    # The proxy bypass and the commit-safety options are assembled in the same dict; dropping either
    # while editing the other is silent (S3 traffic quietly returns to the egress proxy, or commits
    # lose conflict detection).
    def test_proxy_bypass_options_merge_with_commit_safety(self) -> None:
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())

        # Patch the facade seam get_storage_options calls, so this stays a merge-point test and does
        # not reach into another product's internals. What the bypass dict itself contains is covered
        # by products/data_warehouse/backend/tests/test_s3_proxy.py.
        proxy_options = {
            "proxy_url": "http://egress-proxy.test:4750",
            "proxy_excludes": "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com",
            "AWS_S3_ADDRESSING_STYLE": "virtual",
            "virtual_hosted_style_request": "true",
        }
        with (
            override_settings(USE_LOCAL_SETUP=False),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table.delta_proxy_storage_options",
                return_value=proxy_options,
            ),
        ):
            options = table_ref.get_storage_options()

        assert options["conditional_put"] == "etag"
        assert options["proxy_excludes"] == "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com"


class TestGetDeltaTableUnrecoverableErrors:
    # (case_name, error_message, expect_heal) — heal = wipe the table and fall back to first-sync mode
    _ERROR_CASES: list[tuple[str, str, bool]] = [
        (
            "orphaned_delta_log",
            "Kernel error: No table metadata or protocol found in delta log.",
            True,
        ),
        (
            "empty_log_segment",
            "Generic delta kernel error: No files in log segment",
            True,
        ),
        ("bugged_decimal_data", "parse decimal overflow at column x", True),
        ("other_errors_reraise", "Generic DeltaTable error: something else went wrong", False),
    ]

    @parameterized.expand(_ERROR_CASES)
    @pytest.mark.asyncio
    async def test_open_failure_handling(self, _name: str, error_message: str, expect_heal: bool):
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3 = MagicMock()
        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=s3)
        s3_cm.__aexit__ = AsyncMock(return_value=False)
        mock_aget_s3_client = MagicMock(return_value=s3_cm)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", mock_aget_s3_client),
            patch(f"{module}._purge_s3_prefix", AsyncMock()) as mock_purge,
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception(error_message)

            if expect_heal:
                result = await table_ref.get_delta_table()
                assert result is None
                assert table_ref.is_first_sync is True
                # Regression guard: a bare recursive `_rm` (instead of the enumerate-then-delete
                # `_purge_s3_prefix`) can leave `_delta_log` strays on S3-compatible stores and
                # recreate this exact corruption on the next sync.
                mock_purge.assert_awaited_once_with(s3, delta_uri)
                mock_aget_s3_client.assert_called_once_with(fresh_instance=True)
            else:
                with pytest.raises(Exception, match="something else went wrong"):
                    await table_ref.get_delta_table()
                mock_purge.assert_not_awaited()
                assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_open_failure_heals_even_if_prefix_already_gone(self):
        """A concurrent purge (e.g. a retried Temporal attempt) can already have cleared the
        prefix by the time this one runs `_purge_s3_prefix`, which surfaces as `FileNotFoundError`.
        That's still a successful heal, not a failure to propagate."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        s3_cm.__aexit__ = AsyncMock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", MagicMock(return_value=s3_cm)),
            patch(f"{module}._purge_s3_prefix", AsyncMock(side_effect=FileNotFoundError)),
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception("Kernel error: No table metadata or protocol found in delta log.")

            result = await table_ref.get_delta_table()
            assert result is None
            assert table_ref.is_first_sync is True

    @pytest.mark.asyncio
    async def test_is_deltatable_failure_is_captured_and_reraised(self):
        """The `is_deltatable` existence check is a separate S3 call from the DeltaTable() open
        handled above, and callers span best-effort maintenance to the main write path, so a
        failure here can't be swallowed as "no table" (that would trip should_overwrite_table and
        wipe an existing table) — it must be captured for visibility and reraised."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.side_effect = OSError("unexpected end of stream while reading response")
            mock_delta_table.is_deltatable.side_effect = OSError("unexpected end of stream while reading response")

            with pytest.raises(OSError, match="unexpected end of stream"):
                await table_ref.get_delta_table()

            mock_capture.assert_called_once()
            assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_is_deltatable_transient_error_is_not_captured_but_still_reraised(self):
        """A known-transient object-store blip (e.g. an S3 LIST request timing out) must not be
        reported to error tracking as a defect — it's a self-recovering network hiccup, not a bug.
        It must still propagate (as TransientObjectStoreError, not the raw OSError) so Temporal's
        activity retry policy retries the sync. Wrapping matters, not just suppressing the inline
        capture_exception call here: a bare OSError would still reach the activity interceptor
        (posthog_client.py), which reports any uncaught activity exception that isn't a
        NonReportableError, minting a fresh error-tracking issue per blip anyway."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        original_error = OSError(
            "Generic S3 error\nError getting list response body\nHTTP error\n"
            "request or response body error\noperation timed out"
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.side_effect = original_error
            mock_delta_table.is_deltatable.side_effect = original_error

            with pytest.raises(TransientObjectStoreError, match="operation timed out") as exc_info:
                await table_ref.get_delta_table()

            assert exc_info.value.__cause__ is original_error
            mock_capture.assert_not_called()
            cast(AsyncMock, table_ref._logger.awarning).assert_awaited_once()
            assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_object_store_refusal_is_typed_and_not_captured_inline(self):
        """The bucket refusing the read is a policy condition on PostHog's own storage, not a defect
        in this code and not a corrupt table. Capturing inline here and then reraising the raw
        OSError reported the same refusal twice, once from this call and once from the activity
        interceptor, and the raw message names the `_delta_log` key it was refused on, which both
        leaks the object key into the customer's error text and fingerprints into its own
        error-tracking issue per table. Raising the typed error leaves one report, with a message
        that names no key."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        original_error = OSError(
            "Kernel error -> The operation lacked the necessary privileges to complete for path "
            "warehouse/team_42_source_7/orders/_delta_log/00000000000000000012.json"
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.side_effect = original_error
            mock_delta_table.is_deltatable.side_effect = original_error

            with pytest.raises(ObjectStorePermissionDeniedError) as exc_info:
                await table_ref.get_delta_table()

            assert exc_info.value.__cause__ is original_error
            assert "_delta_log" not in str(exc_info.value)
            mock_capture.assert_not_called()
            assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_open_transient_delta_log_race_is_not_captured_but_still_reraised(self):
        """A concurrent `reset_table` purge (a full_refresh sync, or this same open racing another
        attempt) can take a `_delta_log` checkpoint file out from under this open between `_last_checkpoint`
        pointing to it and delta-rs fetching it, surfacing as a DeltaError for a missing checkpoint object
        (see is_transient_delta_maintenance_error). That's not table corruption, so it must not be
        captured or trigger the unrecoverable-table wipe — it must propagate as TransientObjectStoreError
        so Temporal retries the sync."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        checkpoint_race_error = deltalake.exceptions.DeltaError(
            "Kernel error: Arrow error: External: Object at location "
            "dlt/team_1_source_2/table/_delta_log/00000000000000000099.checkpoint.parquet not found: "
            "Error performing GET https://s3.example.com/... - Server returned non-2xx status code: "
            "404 Not Found: NoSuchKey"
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}._purge_s3_prefix", AsyncMock()) as mock_purge,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = checkpoint_race_error

            with pytest.raises(TransientObjectStoreError):
                await table_ref.get_delta_table()

            mock_capture.assert_not_called()
            mock_purge.assert_not_awaited()
            assert table_ref.is_first_sync is False


class TestIsTableCorrupted:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    def _table_ref(self) -> DeltaTableRef:
        return DeltaTableRef("t", MagicMock(), MagicMock(adebug=AsyncMock()), False)

    @parameterized.expand(
        [
            # (is_deltatable, open_exception, expected_corrupt) — only DeltaError/FileNotFoundError on a
            # table whose _delta_log exists count as corrupt; a missing table or an unknown error must NOT,
            # so we never trigger a destructive revive on a non-existent table or a transient failure.
            ("not_a_delta_table", False, None, False),
            ("opens_fine", True, None, False),
            ("delta_error_is_corrupt", True, deltalake.exceptions.DeltaError("no protocol"), True),
            ("file_not_found_is_corrupt", True, FileNotFoundError("missing data file"), True),
            ("unknown_error_not_corrupt", True, ValueError("transient"), False),
            # A concurrent purge racing this same open (see is_transient_delta_maintenance_error) is a
            # DeltaError too, but must not read as corrupt — that would trigger a needless destructive
            # revive (full non-billable resync) for what a plain retry would have resolved on its own.
            (
                "transient_delta_log_race_not_corrupt",
                True,
                deltalake.exceptions.DeltaError(
                    "Kernel error: Arrow error: External: Object at location "
                    "dlt/team_1_source_2/table/_delta_log/00000000000000000099.checkpoint.parquet not found: "
                    "Error performing GET https://s3.example.com/... - Server returned non-2xx status code: "
                    "404 Not Found: NoSuchKey"
                ),
                False,
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_is_table_corrupted(self, _name: str, is_delta: bool, open_exc: Exception | None, expected: bool):
        table_ref = self._table_ref()
        with (
            patch.object(table_ref, "_get_delta_table_uri", new=AsyncMock(return_value="s3://b/t")),
            patch.object(table_ref, "_get_credentials", return_value={}),
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_dt,
        ):
            mock_dt.is_deltatable = MagicMock(return_value=is_delta)
            if open_exc is not None:
                mock_dt.side_effect = open_exc
            result = await table_ref.is_table_corrupted()

        assert result is expected


class TestPurgeS3PrefixPermissionErrors:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    # A HeadObject 403 never carries the underlying S3 error code in its body (AWS omits it for HEAD
    # requests), so a fresh client's brief IMDS/STS credential-resolution race surfaces identically to a
    # genuine permission problem: a bare PermissionError("Forbidden"). Before this fix, `_purge_s3_prefix`
    # only retried the needles in `is_transient_object_store_error` and raised immediately on any
    # PermissionError, failing the whole sync for what was actually a transient, self-healing race.
    @pytest.mark.asyncio
    async def test_retries_permission_error_and_succeeds_once_it_clears(self):
        with (
            patch(
                f"{self._MODULE}._purge_s3_prefix_once",
                new=AsyncMock(side_effect=[PermissionError("Forbidden"), None]),
            ) as mock_once,
            patch(f"{self._MODULE}.asyncio.sleep", new=AsyncMock()),
        ):
            await _purge_s3_prefix(MagicMock(), "s3://bucket/prefix")

        assert mock_once.await_count == 2

    @parameterized.expand(
        [
            # A bodyless 403 keeps the whole budget, because it can still be the race above.
            ("bodyless_403_spends_the_budget", "Forbidden", _PURGE_S3_PREFIX_MAX_ATTEMPTS, PermissionError),
            # S3 only returns an explicit AccessDenied code when a policy refuses the call, so the
            # remaining attempts would make the same refused DeleteObjects calls. They only delay the
            # failure by the backoff, which is why this one has to fail on the first attempt and say
            # what it is instead of surfacing as a bare PermissionError.
            ("explicit_access_denied_fails_once", "Access Denied", 1, ObjectStorePermissionDeniedError),
        ]
    )
    @pytest.mark.asyncio
    async def test_persistent_permission_error(
        self, _case: str, message: str, expected_attempts: int, expected_error: type[Exception]
    ):
        with (
            patch(
                f"{self._MODULE}._purge_s3_prefix_once",
                new=AsyncMock(side_effect=PermissionError(message)),
            ) as mock_once,
            patch(f"{self._MODULE}.asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(expected_error):
                await _purge_s3_prefix(MagicMock(), "s3://bucket/prefix")

        assert mock_once.await_count == expected_attempts


class TestInvalidateDropsTheDeltaliteHandle:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    @pytest.mark.asyncio
    async def test_invalidating_the_ref_forgets_the_process_wide_handle(self):
        # A reset or repartition swap replaces the table under the same URI. A deltalite handle
        # that survives it would refresh the old snapshot with the new log's commits.
        cache = DeltaLiteHandleCache(maxsize=2, opener=lambda uri, storage_options: MagicMock())
        ref = _openable_table_ref("s3://bucket/team/job/t")

        with patch(f"{self._MODULE}.get_handle_cache", return_value=cache):
            await ref.get_table_uri()
            with cache.lease("s3://bucket/team/job/t", storage_options={}, table_id="tid", table_version=1):
                pass
            assert "s3://bucket/team/job/t" in cache

            ref.invalidate_cached_table()

        assert "s3://bucket/team/job/t" not in cache


def _rows(ids: list[int], partition: str) -> pa.Table:
    return pa.table({"id": pa.array(ids, pa.int64()), "part": [partition] * len(ids)})


def _appended(uri: str) -> None:
    deltalake.write_deltalake(uri, _rows([5, 6], "b"), mode="append", partition_by=["part"])


def _overwritten(uri: str) -> None:
    deltalake.write_deltalake(uri, _rows([7], "c"), mode="overwrite", partition_by=["part"])


def _deleted_from(uri: str) -> None:
    deltalake.DeltaTable(uri).delete("id = 1")


def _emptied(uri: str) -> None:
    deltalake.DeltaTable(uri).delete("id > 0")


def _merged(uri: str) -> None:
    (
        deltalake.DeltaTable(uri)
        .merge(_rows([2, 9], "a"), predicate="t.id = s.id", source_alias="s", target_alias="t")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute()
    )


def _upserted_with_deltalite(uri: str) -> None:
    deltalite.DeltaLiteTable.open(uri).upsert(_rows([3, 10, 11], "a"), primary_keys=["id"], partition_key="part")


def _overwritten_without_partitions(uri: str) -> None:
    deltalake.write_deltalake(uri, _rows([7], "c"), mode="overwrite")


def _compacted_without_partitions(uri: str) -> None:
    deltalake.write_deltalake(uri, _rows([5, 6], "b"), mode="append")
    deltalake.DeltaTable(uri).optimize.compact()


def _compacted(uri: str) -> None:
    _appended(uri)
    deltalake.DeltaTable(uri).optimize.compact()


def _vacuumed(uri: str) -> None:
    _deleted_from(uri)
    deltalake.DeltaTable(uri).vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)


def _strip_add_stats(uri: str) -> None:
    for commit in sorted((Path(uri) / "_delta_log").glob("*.json")):
        actions = [json.loads(line) for line in commit.read_text().splitlines() if line]
        for action in actions:
            action.get("add", {}).pop("stats", None)
        commit.write_text("\n".join(json.dumps(action) for action in actions) + "\n")


class TestLiveRowCount:
    @staticmethod
    def _create(tmp_path: Path) -> str:
        uri = str(tmp_path / "t")
        deltalake.write_deltalake(uri, _rows([1, 2, 3, 4], "a"), partition_by=["part"])
        return uri

    @parameterized.expand(
        [
            ("append_only", lambda uri: None),
            ("append", _appended),
            ("overwrite", _overwritten),
            ("delete", _deleted_from),
            ("delete_every_row", _emptied),
            ("merge", _merged),
            ("deltalite_upsert", _upserted_with_deltalite),
            ("compaction", _compacted),
            ("vacuum", _vacuumed),
        ]
    )
    def test_matches_a_count_of_the_published_files(self, _name: str, history: Callable[[str], None]) -> None:
        # The query folder is a copy of file_uris(), so a count over it is the sum of their rows.
        uri = self._create(self.tmp_path)
        history(uri)
        table = deltalake.DeltaTable(uri)

        published_rows = sum(pq.read_metadata(path).num_rows for path in table.file_uris())

        assert live_row_count(table) == published_rows == table.to_pyarrow_table().num_rows

    def test_files_without_stats_fall_back_to_a_file_count(self) -> None:
        uri = self._create(self.tmp_path)
        _strip_add_stats(uri)

        assert live_row_count(deltalake.DeltaTable(uri)) is None

    def test_unreadable_add_actions_fall_back_to_a_file_count(self) -> None:
        table = MagicMock()
        table.get_add_actions.side_effect = Exception("Offset overflow error: 2229224676")

        assert live_row_count(table) is None

    @pytest.mark.asyncio
    async def test_ref_reads_the_count_after_a_deltalite_commit(self) -> None:
        # deltalite commits outside the cached delta-rs handle, so a stale handle would miss its rows.
        uri = self._create(self.tmp_path)
        ref = make_local_table_ref(uri)
        assert await ref.get_live_row_count() == 4

        deltalite.DeltaLiteTable.open(uri).upsert(_rows([10, 11], "a"), primary_keys=["id"], partition_key="part")
        ref.note_deltalite_commit(None)

        assert await ref.get_live_row_count() == 6

    @pytest.mark.asyncio
    async def test_ref_without_a_table_has_no_count(self) -> None:
        ref = make_local_table_ref(str(self.tmp_path / "missing"))

        assert await ref.get_live_row_count() is None
        assert await ref.get_live_size_mib() is None

    @parameterized.expand(
        [
            ("append_only", True, lambda uri: None),
            ("append", True, _appended),
            ("full_refresh", True, _overwritten),
            ("delete", True, _deleted_from),
            ("empty_table", True, _emptied),
            ("merge", True, _merged),
            ("deltalite_upsert", True, _upserted_with_deltalite),
            ("compaction", True, _compacted),
            ("vacuum", True, _vacuumed),
            ("unpartitioned", False, lambda uri: None),
            ("unpartitioned_full_refresh", False, _overwritten_without_partitions),
            ("unpartitioned_compaction", False, _compacted_without_partitions),
        ]
    )
    def test_size_matches_the_published_files_and_the_size_activity(
        self, _name: str, partitioned: bool, history: Callable[[str], None]
    ) -> None:
        # The loader records this number in place of the size activity, and billing sums it. It has
        # to be the bytes of the files the query folder holds, with no removed file counted.
        uri = self._create(self.tmp_path) if partitioned else self._create_unpartitioned(self.tmp_path)
        history(uri)
        table = deltalake.DeltaTable(uri)

        published_mib = sum(Path(path).stat().st_size for path in table.file_uris()) / (1024 * 1024)
        with patch(f"{_TABLE_MODULE}.delta_storage_options", return_value={}):
            activity_mib = _live_delta_size_mib(uri)

        assert live_size_mib(table) == published_mib == activity_mib

    @parameterized.expand(
        [
            ("a_file_without_a_size", MagicMock(return_value={"a.parquet": 10, "b.parquet": None})),
            ("an_unreadable_log", MagicMock(side_effect=Exception("Generic delta kernel error"))),
        ]
    )
    def test_no_size_when_the_log_cannot_give_every_file_size(self, _name: str, get_add_file_sizes: MagicMock) -> None:
        # None keeps the recorded size and leaves the measurement to the size activity. A partial
        # sum or a 0 would under-report the table.
        table = MagicMock()
        table._table.get_add_file_sizes = get_add_file_sizes

        assert live_size_mib(table) is None

    @pytest.mark.asyncio
    async def test_ref_reads_the_size_after_a_deltalite_commit(self) -> None:
        uri = self._create(self.tmp_path)
        ref = make_local_table_ref(uri)
        size_before = await ref.get_live_size_mib()

        deltalite.DeltaLiteTable.open(uri).upsert(_rows([10, 11], "a"), primary_keys=["id"], partition_key="part")
        ref.note_deltalite_commit(None)

        assert await ref.get_live_size_mib() == live_size_mib(deltalake.DeltaTable(uri)) != size_before

    @staticmethod
    def _create_unpartitioned(tmp_path: Path) -> str:
        uri = str(tmp_path / "t")
        deltalake.write_deltalake(uri, _rows([1, 2, 3, 4], "a"))
        return uri

    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
