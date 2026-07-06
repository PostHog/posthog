import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    run_pre_write_defensive_compact,
)

_EXTRACT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract"


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
