import uuid
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    handle_corrupted_delta_log,
    report_heartbeat_timeout,
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
        # Stub the vacuum path to a clean no-op so only the compaction failure is captured.
        helper = MagicMock(compact_if_fragmented=compact, vacuum_if_stale=AsyncMock(return_value=None))
        logger = MagicMock(aexception=AsyncMock())

        schema = MagicMock(partition_count=5, sync_type_config={})
        with patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture:
            await run_pre_write_defensive_compact(helper, schema, MagicMock(partition_count=None), logger)

        mock_capture.assert_called_once()
        logger.aexception.assert_awaited_once()


class TestReportHeartbeatTimeoutRecording(BaseTest):
    def _schema(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="orders")

    def _info(self, *, attempt: int, gap_seconds: float) -> MagicMock:
        info = MagicMock()
        info.heartbeat_timeout = timedelta(minutes=2)
        info.attempt = attempt
        scheduled = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
        info.current_attempt_scheduled_time = scheduled
        info.heartbeat_details = [{"host": "pod-abc", "ts": scheduled.timestamp() - gap_seconds}]
        return info

    @parameterized.expand(
        [
            # A gap past the 2-min heartbeat timeout is a detected OOM → one durable row.
            ("oom_records_row", 300, 1),
            # Within the timeout is a normal retry: the write must stay inside the OOM branch, not fire.
            ("within_timeout_records_nothing", 30, 0),
        ]
    )
    def test_records_one_row_per_detected_oom(self, _name: str, gap_seconds: float, expected_rows: int) -> None:
        schema = self._schema()
        inputs = MagicMock(team_id=self.team.pk, schema_id=schema.id, source_id=str(uuid.uuid4()), run_id="run-1")

        with (
            patch(f"{_EXTRACT_MODULE}.activity.info", return_value=self._info(attempt=2, gap_seconds=gap_seconds)),
            patch(f"{_EXTRACT_MODULE}.posthoganalytics"),
        ):
            report_heartbeat_timeout(inputs, MagicMock())

        rows = ExternalDataSchemaOOMEvent.objects.for_team(self.team.pk).filter(schema_id=schema.id)
        assert rows.count() == expected_rows
        if expected_rows:
            event = rows.get()
            assert event.host == "pod-abc"
            assert event.run_id == "run-1"
            assert event.gap_seconds == pytest.approx(gap_seconds)


# transaction=True: handle_corrupted_delta_log writes to the DB from the async thread pool
# (database_sync_to_async_pool), which can't see an atomic TestCase's uncommitted rows.
@pytest.mark.django_db(transaction=True)
class TestHandleCorruptedDeltaLog:
    def _schema_and_job(self, team) -> tuple[ExternalDataSchema, ExternalDataJob]:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="Invoice", team=team, source=source, sync_type_config={})
        job = ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            billable=True,
        )
        return schema, job

    def _logger(self) -> MagicMock:
        return MagicMock(awarning=AsyncMock(), ainfo=AsyncMock(), aexception=AsyncMock())

    def test_healthy_table_is_a_noop(self, team):
        # Guard: a readable table must never be reset or flipped non-billable — that would nuke healthy
        # data and stop billing the customer for a legitimate sync.
        schema, job = self._schema_and_job(team)
        helper = MagicMock(is_table_corrupted=AsyncMock(return_value=False), reset_table=AsyncMock())

        result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is False
        helper.reset_table.assert_not_awaited()
        job.refresh_from_db()
        assert job.billable is True

    def test_corrupt_table_without_salvage_resets_non_billable(self, team):
        # A corrupt table with no recoverable repartition swap is reset for an in-run rebuild, and the job
        # is marked non-billable — the corruption is our fault, so the customer isn't charged for the rebuild.
        schema, job = self._schema_and_job(team)  # sync_type_config has no repartition_swap → no salvage path
        helper = MagicMock(is_table_corrupted=AsyncMock(return_value=True), reset_table=AsyncMock())

        result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is True
        helper.reset_table.assert_awaited_once()
        job.refresh_from_db()
        assert job.billable is False
