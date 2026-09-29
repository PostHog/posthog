from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import deltalake
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
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger


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
