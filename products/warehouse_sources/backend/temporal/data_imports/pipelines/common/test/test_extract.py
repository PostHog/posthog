from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.temporal.common.errors import is_expected_error

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    NON_RETRYABLE_ERROR_RETRY_LIMIT,
    handle_non_retryable_error,
    run_pre_write_defensive_compact,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

_EXTRACT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract"


def _fake_redis(attempts: int):
    redis = MagicMock()
    redis.incr = AsyncMock(return_value=attempts)
    redis.expire = AsyncMock()

    @asynccontextmanager
    async def _cm():
        yield redis

    return _cm


class TestHandleNonRetryableError:
    @staticmethod
    def _job_inputs() -> MagicMock:
        return MagicMock(team_id=1, source_id="src", run_id="run")

    @staticmethod
    def _logger() -> MagicMock:
        return MagicMock(adebug=AsyncMock())

    @pytest.mark.asyncio
    async def test_under_retry_limit_reraises_error_flagged_expected(self) -> None:
        # Below the limit the raw error is re-raised so Temporal retries it — but it must be flagged
        # expected so the interceptor stops reporting the (already customer-surfaced) config failure
        # on every attempt. That flag suppression is the whole point of this path.
        original = PermissionError("share the sheet with our service account")
        with patch(f"{_EXTRACT_MODULE}._get_redis", _fake_redis(1)):
            with pytest.raises(PermissionError) as exc_info:
                await handle_non_retryable_error(self._job_inputs(), "denied", self._logger(), original)

        assert exc_info.value is original
        assert is_expected_error(original) is True

    @pytest.mark.asyncio
    async def test_over_retry_limit_raises_non_retryable(self) -> None:
        # Past the limit we give up with NonRetryableException so Temporal stops retrying (it's in
        # the activity's non_retryable_error_types) rather than looping forever.
        with patch(f"{_EXTRACT_MODULE}._get_redis", _fake_redis(NON_RETRYABLE_ERROR_RETRY_LIMIT + 1)):
            with pytest.raises(NonRetryableException):
                await handle_non_retryable_error(
                    self._job_inputs(), "denied", self._logger(), PermissionError("denied")
                )


class TestRunPreWriteDefensiveCompact:
    @parameterized.expand(
        [
            # (schema_partition_count, resource_partition_count, expected_passed_to_compact)
            ("schema_value_wins", 10, 72, 10),
            ("falls_back_to_resource", None, 72, 72),
            ("both_none_passes_none", None, None, None),
        ]
    )
    @pytest.mark.asyncio
    async def test_resolves_partition_count_schema_over_resource(
        self, _name: str, schema_count: int | None, resource_count: int | None, expected: int | None
    ):
        compact = AsyncMock(return_value=False)
        helper = MagicMock(compact_if_fragmented=compact)

        await run_pre_write_defensive_compact(
            helper,
            MagicMock(partition_count=schema_count),
            MagicMock(partition_count=resource_count),
            MagicMock(aexception=AsyncMock()),
        )

        compact.assert_awaited_once_with(partition_count=expected)

    @pytest.mark.asyncio
    async def test_swallows_compaction_failure(self):
        # The whole point of the wrapper: a compaction error must never propagate and
        # block the sync — it's captured and logged instead.
        compact = AsyncMock(side_effect=RuntimeError("compaction blew up"))
        helper = MagicMock(compact_if_fragmented=compact)
        logger = MagicMock(aexception=AsyncMock())

        with patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture:
            await run_pre_write_defensive_compact(
                helper, MagicMock(partition_count=5), MagicMock(partition_count=None), logger
            )

        mock_capture.assert_called_once()
        logger.aexception.assert_awaited_once()
