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
    handle_reset_or_full_refresh,
    persist_primary_keys,
    report_heartbeat_timeout,
    resolve_primary_keys,
    run_pre_write_defensive_compact,
)

_EXTRACT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract"


class TestResolvePrimaryKeys:
    @parameterized.expand(
        [
            # A persisted key (user override or earlier detection) always wins over live detection.
            ("persisted_wins_over_live", ["user_pk"], ["live_pk"], {"columns": [{"name": "id"}]}, ["user_pk"]),
            # No persisted key -> use what the source detected live this run.
            ("live_used_when_no_persisted", None, ["live_pk"], {"columns": [{"name": "id"}]}, ["live_pk"]),
            # Neither persisted nor live, but the table has `id` -> mirror the discovery-time fallback.
            ("id_fallback_when_neither", None, None, {"columns": [{"name": "id"}, {"name": "name"}]}, ["id"]),
            # Nothing to fall back on -> None, so the keyless-table guardrail still fires.
            ("none_when_no_id_and_nothing_else", None, None, {"columns": [{"name": "name"}]}, None),
            # Snowflake uppercases unquoted identifiers: the fallback must match `ID`
            # case-insensitively AND return the actual stored casing — the merge indexes batches
            # by the real column name, so a hardcoded lowercase `id` would fail it just the same.
            ("uppercase_id_matched_with_actual_casing", None, None, {"columns": [{"name": "ID"}]}, ["ID"]),
        ]
    )
    def test_precedence(
        self,
        _name: str,
        persisted: list[str] | None,
        live: list[str] | None,
        schema_metadata: dict,
        expected: list[str] | None,
    ):
        schema = MagicMock(primary_key_columns=persisted, schema_metadata=schema_metadata)
        resource = MagicMock(primary_keys=live)
        assert resolve_primary_keys(schema, resource) == expected


class TestPersistPrimaryKeys:
    @parameterized.expand(
        [
            # name, is_incremental, persisted_pk, resource_pks, db_config_before, expected_written (None = no write attempted)
            # Full-refresh schemas don't merge on a PK — never touch sync_type_config.
            ("skips_when_not_incremental", False, None, ["id"], {}, None),
            # A stored PK is already the source of truth — nothing to backfill.
            ("skips_when_already_persisted", True, ["existing"], ["id"], {}, None),
            # No resolvable PK -> leave it empty so the keyless-table guardrail still fires.
            ("skips_when_no_resolved_pk", True, None, None, {}, None),
            # The fix: an incremental schema with no stored PK backfills the resolved one.
            ("backfills_when_incremental_and_empty", True, None, ["id"], {}, {"primary_key_columns": ["id"]}),
            # A concurrent API edit that landed a PK first must not be clobbered inside the lock.
            (
                "does_not_clobber_concurrent_write",
                True,
                None,
                ["id"],
                {"primary_key_columns": ["already"]},
                {"primary_key_columns": ["already"]},
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_persists_only_when_incremental_and_empty(
        self,
        _name: str,
        is_incremental: bool,
        persisted: list[str] | None,
        resource_pks: list[str] | None,
        db_config_before: dict,
        expected_written: dict | None,
    ):
        schema = MagicMock(id="s1", team_id=1, primary_key_columns=persisted)
        resource = MagicMock(primary_keys=resource_pks)

        captured: dict = {}

        def fake_pool(fn):
            async def _call(schema_id, team_id, *, mutate=None, **kwargs):
                config = dict(db_config_before)
                if mutate is not None:
                    mutate(config)
                captured["config"] = config
                return config

            return _call

        with patch(f"{_EXTRACT_MODULE}.database_sync_to_async_pool", fake_pool):
            await persist_primary_keys(schema, resource, is_incremental, AsyncMock())

        assert captured.get("config") == expected_written

    @pytest.mark.asyncio
    async def test_persistence_failure_does_not_raise(self):
        # Best-effort: a DB failure while backfilling the PK must not fail an otherwise good sync.
        schema = MagicMock(id="s1", team_id=1, primary_key_columns=None)
        resource = MagicMock(primary_keys=["id"])
        logger = AsyncMock()

        def fake_pool(fn):
            async def _call(*args, **kwargs):
                raise RuntimeError("pooler dropped the connection")

            return _call

        with patch(f"{_EXTRACT_MODULE}.database_sync_to_async_pool", fake_pool):
            await persist_primary_keys(schema, resource, True, logger)

        logger.aexception.assert_awaited_once()


class TestRunPreWriteDefensiveCompact:
    @parameterized.expand(
        [
            # (schema_partition_count, resource_partition_count, expected_passed_to_run_maintenance)
            ("schema_value_wins", 10, 72, 10),
            ("falls_back_to_resource", None, 72, 72),
            ("both_none_passes_none", None, None, None),
        ]
    )
    @pytest.mark.asyncio
    async def test_resolves_partition_count_schema_over_resource(
        self, _name: str, schema_count: int | None, resource_count: int | None, expected: int | None
    ):
        run_maintenance = AsyncMock(return_value=None)
        helper = MagicMock(run_maintenance=run_maintenance)

        await run_pre_write_defensive_compact(
            helper,
            MagicMock(partition_count=schema_count, sync_type_config={}),
            MagicMock(partition_count=resource_count),
            MagicMock(aexception=AsyncMock()),
        )

        assert run_maintenance.await_args is not None
        assert run_maintenance.await_args.kwargs["partition_count"] == expected

    @pytest.mark.asyncio
    async def test_swallows_maintenance_failure(self):
        # The whole point of the wrapper: a maintenance error must never propagate and
        # block the sync — it's captured and logged instead.
        helper = MagicMock(run_maintenance=AsyncMock(side_effect=RuntimeError("maintenance blew up")))
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

        with patch(f"{_EXTRACT_MODULE}.posthoganalytics") as ph:
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is False
        helper.reset_table.assert_not_awaited()
        job.refresh_from_db()
        assert job.billable is True
        ph.capture.assert_not_called()  # no revival event for a healthy table

    def test_corrupt_table_without_salvage_resets_non_billable(self, team):
        # A corrupt table with no recoverable repartition swap is reset for an in-run rebuild, and the job
        # is marked non-billable — the corruption is our fault, so the customer isn't charged for the rebuild.
        schema, job = self._schema_and_job(team)  # sync_type_config has no repartition_swap → no salvage path
        helper = MagicMock(is_table_corrupted=AsyncMock(return_value=True), reset_table=AsyncMock())

        with patch(f"{_EXTRACT_MODULE}.posthoganalytics") as ph:
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is True
        helper.reset_table.assert_awaited_once()
        job.refresh_from_db()
        assert job.billable is False
        # A revival must be observable, tagged with how it recovered and that the rebuild was made non-billable.
        assert ph.capture.call_args.kwargs["event"] == "warehouse_delta_revived"
        assert ph.capture.call_args.kwargs["properties"]["outcome"] == "reset_rebuild"
        assert ph.capture.call_args.kwargs["properties"]["made_non_billable"] is True

    def test_revive_marker_resets_readable_table(self, team):
        # A hollow table — log opens fine but references data files gone from S3 — is invisible to
        # is_table_corrupted; the repartition scan marks it instead. The marker alone must trigger the
        # reset + non-billable rebuild and be cleared so the revive can't loop.
        schema, job = self._schema_and_job(team)
        schema.sync_type_config = {
            "delta_revive_required": {"reason": "repartition_scan_missing_data_file", "missing_path": "x/p.parquet"}
        }
        schema.save(update_fields=["sync_type_config"])
        helper = MagicMock(is_table_corrupted=AsyncMock(return_value=False), reset_table=AsyncMock())

        with patch(f"{_EXTRACT_MODULE}.posthoganalytics") as ph:
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is True
        helper.reset_table.assert_awaited_once()
        job.refresh_from_db()
        assert job.billable is False
        # The in-memory copy must be refreshed too: the pipeline keeps saving this same schema
        # object for the rest of the run (incremental staging, partition bookkeeping), and a stale
        # copy writes the marker back — re-arming a non-billable full rebuild on every sync.
        assert "delta_revive_required" not in schema.sync_type_config
        schema.stage_incremental_field_value("run-1", 5)
        schema.refresh_from_db()
        assert "delta_revive_required" not in schema.sync_type_config
        assert ph.capture.call_args.kwargs["properties"]["outcome"] == "reset_rebuild"

    def test_corrupt_table_with_ready_swap_is_salvaged(self, team):
        # A corrupt table whose interrupted repartition swap left a `ready` temp table is finished from temp
        # rather than reset — the customer's data is recovered without a rebuild, so reset_table never runs
        # and the job stays billable. Guards the salvage-from-temp branch against regressing to a reset.
        schema, job = self._schema_and_job(team)
        # A hollow-table marker can coexist with the interrupted swap (the repartition scan set it
        # before the swap crashed) — the salvage must clear it in memory as well as in the DB.
        schema.sync_type_config = {
            "repartition_swap": {"state": "ready", "temp_uri": "s3://bucket/temp", "live_uri": "s3://bucket/live"},
            "delta_revive_required": {"reason": "repartition_scan_missing_data_file", "missing_path": "x/p.parquet"},
        }
        schema.save(update_fields=["sync_type_config"])
        helper = MagicMock(
            is_table_corrupted=AsyncMock(return_value=True),
            reset_table=AsyncMock(),
            _get_credentials=MagicMock(return_value={}),
        )

        repartition_module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition"
        repartition_table_module = (
            "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table"
        )
        resume = AsyncMock(return_value={"outcome": "completed"})
        with (
            patch(f"{repartition_module}._resume_swap_with_missing_live", resume),
            patch(f"{repartition_table_module}._target_from_schema", return_value=MagicMock()),
            patch(f"{_EXTRACT_MODULE}.posthoganalytics") as ph,
        ):
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        assert result is True
        resume.assert_awaited_once()
        helper.reset_table.assert_not_awaited()
        job.refresh_from_db()
        assert job.billable is True
        # Same stale-copy guard as the reset path: a later full-config save off this schema object
        # must not write the cleared marker back.
        assert "delta_revive_required" not in schema.sync_type_config
        schema.stage_incremental_field_value("run-1", 5)
        schema.refresh_from_db()
        assert "delta_revive_required" not in schema.sync_type_config
        # A salvage must be observable too, tagged as recovered-from-temp with the rebuild left billable.
        assert ph.capture.call_args.kwargs["event"] == "warehouse_delta_revived"
        assert ph.capture.call_args.kwargs["properties"]["outcome"] == "salvaged"
        assert ph.capture.call_args.kwargs["properties"]["made_non_billable"] is False


# transaction=True: the webhook-first branch clears the reset flag via update_sync_type_config_keys,
# which writes from the async thread pool and can't see an atomic TestCase's uncommitted rows.
@pytest.mark.django_db(transaction=True)
class TestHandleResetOrFullRefresh:
    def _webhook_schema(self, team) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Github"
        )
        return ExternalDataSchema.objects.create(
            name="workflow_jobs",
            team=team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"reset_pipeline": True, "incremental_field_last_value": "2026-01-01T00:00:00"},
            initial_sync_complete=True,
        )

    def test_webhook_only_reset_preserves_table_and_state(self, team):
        # The data-loss regression: a reset on a webhook-only schema must not wipe the Delta
        # table (the poll can't rebuild webhook-accumulated rows). The reset request is consumed,
        # while the watermark and initial_sync_complete survive so webhook ingestion resumes.
        schema = self._webhook_schema(team)
        helper = MagicMock(reset_table=AsyncMock())

        async_to_sync(handle_reset_or_full_refresh)(
            True, False, schema, helper, MagicMock(adebug=AsyncMock()), webhook_only=True
        )

        helper.reset_table.assert_not_awaited()
        # In-memory config is cleared too — otherwise a later watermark save re-persists
        # reset_pipeline and every subsequent run is treated as a reset.
        assert "reset_pipeline" not in schema.sync_type_config
        schema.refresh_from_db()
        assert "reset_pipeline" not in schema.sync_type_config
        assert schema.sync_type_config["incremental_field_last_value"] == "2026-01-01T00:00:00"
        assert schema.initial_sync_complete is True

    def test_poll_backfillable_reset_still_wipes(self, team):
        # Guard against over-correction: a reset on a schema whose poll CAN rebuild the data
        # must keep wiping so the re-crawl starts from a clean table.
        schema = self._webhook_schema(team)
        helper = MagicMock(reset_table=AsyncMock())

        async_to_sync(handle_reset_or_full_refresh)(
            True, False, schema, helper, MagicMock(adebug=AsyncMock()), webhook_only=False
        )

        helper.reset_table.assert_awaited_once()
        schema.refresh_from_db()
        assert "reset_pipeline" not in schema.sync_type_config
