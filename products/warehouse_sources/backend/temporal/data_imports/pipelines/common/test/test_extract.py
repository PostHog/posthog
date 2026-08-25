import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from redis import exceptions as redis_exceptions

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    NON_RETRYABLE_ERROR_RETRY_LIMIT,
    _get_redis,
    handle_corrupted_delta_log,
    handle_non_retryable_error,
    handle_reset_or_full_refresh,
    persist_primary_keys,
    report_heartbeat_timeout,
    reset_rows_synced_if_needed,
    resolve_primary_keys,
    trim_source_job_inputs,
    validate_incremental_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    MissingPrimaryKeysException,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

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
            # name, is_incremental, is_cdc, persisted_pk, resource_pks, db_config_before, expected_written (None = no write attempted)
            # Full-refresh schemas don't merge on a PK — never touch sync_type_config.
            ("skips_when_not_incremental", False, False, None, ["id"], {}, None),
            # A CDC schema snapshots as full_refresh but streams incrementally, so its key must be
            # persisted during that first run — otherwise the streaming phase has no merge key and
            # trips the keyless-table guardrail.
            ("backfills_for_cdc_snapshot", False, True, None, ["id"], {}, {"primary_key_columns": ["id"]}),
            # A stored PK is already the source of truth — nothing to backfill.
            ("skips_when_already_persisted", True, False, ["existing"], ["id"], {}, None),
            # No resolvable PK -> leave it empty so the keyless-table guardrail still fires.
            ("skips_when_no_resolved_pk", True, False, None, None, {}, None),
            # The fix: an incremental schema with no stored PK backfills the resolved one.
            ("backfills_when_incremental_and_empty", True, False, None, ["id"], {}, {"primary_key_columns": ["id"]}),
            # A concurrent API edit that landed a PK first must not be clobbered inside the lock.
            (
                "does_not_clobber_concurrent_write",
                True,
                False,
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
        is_cdc: bool,
        persisted: list[str] | None,
        resource_pks: list[str] | None,
        db_config_before: dict,
        expected_written: dict | None,
    ):
        schema = MagicMock(id="s1", team_id=1, primary_key_columns=persisted, is_cdc=is_cdc)
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


class TestTrimSourceJobInputs:
    @parameterized.expand(
        [
            # A non-empty string decoded out of the EncryptedJSONField used to reach `.items()` and
            # raise AttributeError — it must be skipped, not crash the whole import activity.
            ("bare_string_is_skipped", "not-a-dict"),
            ("list_is_skipped", ["a", "b"]),
            ("none_is_skipped", None),
            ("empty_dict_is_skipped", {}),
        ]
    )
    @pytest.mark.asyncio
    async def test_non_dict_job_inputs_is_a_noop(self, _name: str, job_inputs) -> None:
        source = MagicMock(job_inputs=job_inputs, save=MagicMock())
        with patch(f"{_EXTRACT_MODULE}.database_sync_to_async_pool") as pool:
            await trim_source_job_inputs(source)
        pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_dict_job_inputs_is_trimmed_and_saved(self) -> None:
        source = MagicMock(job_inputs={"host": " example.com ", "port": "5432"}, save=MagicMock())
        saved = AsyncMock()
        with patch(f"{_EXTRACT_MODULE}.database_sync_to_async_pool", return_value=saved):
            await trim_source_job_inputs(source)
        assert source.job_inputs["host"] == "example.com"
        assert source.job_inputs["port"] == "5432"
        saved.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dict_job_inputs_without_padding_does_not_save(self) -> None:
        source = MagicMock(job_inputs={"host": "example.com"}, save=MagicMock())
        with patch(f"{_EXTRACT_MODULE}.database_sync_to_async_pool") as pool:
            await trim_source_job_inputs(source)
        pool.assert_not_called()


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
            # No workload reports were seeded, so evidence must be honestly absent (fails open), not 0.
            assert event.self_phase is None and event.self_peak_buffer_bytes is None
            assert event.self_report_age_at_death_seconds is None

    def test_row_snapshots_workload_evidence_without_co_tenant_identifiers(self) -> None:
        # The whole point of the stack: the dead attempt's own self-report and its pod's aggregates
        # must survive onto the durable row (the Redis source expires in hours), and nothing on the
        # row may carry another team's schema or run ids — this is a team-scoped table.
        import json as _json

        from django.forms.models import model_to_dict

        from products.warehouse_sources.backend.temporal.data_imports import workload_report

        schema = self._schema()
        inputs = MagicMock(team_id=self.team.pk, schema_id=schema.id, source_id=str(uuid.uuid4()), run_id="run-1")
        redis = workload_report._redis_client()
        assert redis is not None
        # Reports flushed 5s before the last heartbeat: fresh, so the rules may act on the evidence.
        heartbeat_ts = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC).timestamp() - 300
        for run_id, schema_id, phase, peak, ts in (
            ("run-1", str(schema.id), "merge", 900, heartbeat_ts - 5),
            ("run-neighbour", "other-team-schema", "merge", 700_000, heartbeat_ts - 5),
            # A neighbour that crashed an hour before the death: its lingering key must not
            # reach the row's culprit evidence, however large its historical peak.
            ("run-ancient", "other-team-schema-2", "merge", 9_000_000, heartbeat_ts - 3600),
        ):
            redis.setex(
                workload_report.run_key(run_id),
                60,
                _json.dumps(
                    {
                        "run_id": run_id,
                        "schema_id": schema_id,
                        "host": "pod-abc",
                        "phase": phase,
                        "buffer_bytes": peak,
                        "peak_buffer_bytes": peak,
                        "ts": ts,
                    }
                ),
            )
            redis.sadd(workload_report.host_key("pod-abc"), run_id)

        with (
            patch(f"{_EXTRACT_MODULE}.activity.info", return_value=self._info(attempt=2, gap_seconds=300)),
            patch(f"{_EXTRACT_MODULE}.posthoganalytics"),
        ):
            report_heartbeat_timeout(inputs, MagicMock())

        event = ExternalDataSchemaOOMEvent.objects.for_team(self.team.pk).get(schema_id=schema.id)
        assert event.self_phase == "merge"
        assert event.self_report_age_at_death_seconds == pytest.approx(5.0)
        assert event.self_peak_buffer_bytes == 900
        assert event.co_tenant_correlated_max_peak_buffer_bytes == 700_000, (
            "stale neighbour peak must not reach the row"
        )
        assert event.co_tenant_report_count == 2
        # The serialized row is what any admin, API or export surface would expose: no field on it
        # may carry the co-tenant's identifiers, only the aggregates asserted above.
        serialized_row = _json.dumps({field: str(value) for field, value in model_to_dict(event).items()})
        assert "other-team-schema" not in serialized_row and "run-neighbour" not in serialized_row
        # The culprit rule then discounts this row: a strictly larger co-tenant makes us the victim.
        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 0


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

    def test_reset_failure_routes_through_non_retryable_handler(self, team):
        # A reset that can't even complete (e.g. the storage backend rejects the delete) must not
        # propagate unguarded — the revive markers would stay set, so every subsequent sync would
        # repeat the exact same failing reset forever. It must go through the same give-up-after-
        # N-attempts policy as any other import error, rather than looping and flooding error tracking.
        schema, job = self._schema_and_job(team)
        reset_error = RuntimeError("An error occurred (InvalidAccessKeyId) when calling ListObjectsV2")
        helper = MagicMock(
            is_table_corrupted=AsyncMock(return_value=True), reset_table=AsyncMock(side_effect=reset_error)
        )

        with (
            patch(f"{_EXTRACT_MODULE}.posthoganalytics"),
            patch(
                f"{_EXTRACT_MODULE}.handle_non_retryable_error",
                new=AsyncMock(side_effect=NonRetryableException()),
            ) as handle_mock,
        ):
            with pytest.raises(NonRetryableException):
                async_to_sync(handle_corrupted_delta_log)(schema, job, helper, self._logger())

        handle_mock.assert_awaited_once()
        assert handle_mock.await_args is not None
        assert handle_mock.await_args.args[0] == schema.team_id
        assert handle_mock.await_args.args[1] == str(job.pipeline_id)
        assert handle_mock.await_args.args[2] == str(job.id)
        assert handle_mock.await_args.args[-1] is reset_error
        # The reset itself failed, so the non-billable flip (which only happens after a successful
        # reset) must never be reached.
        job.refresh_from_db()
        assert job.billable is True

    def test_reset_transient_object_store_error_retries_next_sync(self, team):
        # An S3 rate-limit blip purging the old table's prefix (see `_purge_s3_prefix`) is not a bug:
        # it must skip the non-retryable-error escalation above (which would burn through its attempt
        # budget on pure throttling) and leave the revive markers set so the next sync retries the
        # reset from scratch, instead of minting an error-tracking issue for a self-healing blip.
        schema, job = self._schema_and_job(team)
        reset_error = OSError("[Errno 16] Please reduce your request rate.")
        helper = MagicMock(
            is_table_corrupted=AsyncMock(return_value=True), reset_table=AsyncMock(side_effect=reset_error)
        )
        logger = self._logger()

        with (
            patch(f"{_EXTRACT_MODULE}.posthoganalytics"),
            patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture,
            patch(f"{_EXTRACT_MODULE}.handle_non_retryable_error") as handle_mock,
        ):
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, logger)

        assert result is False
        mock_capture.assert_not_called()
        handle_mock.assert_not_called()
        logger.awarning.assert_awaited()
        job.refresh_from_db()
        assert job.billable is True

    def test_is_table_corrupted_transient_object_store_error_skips_without_capturing(self, team):
        # `is_table_corrupted` opens the table via `DeltaTable.is_deltatable`, which can raise the
        # same IMDS/STS credential-provider blip as any other delta-rs object-store call. That isn't
        # evidence of corruption — it must be treated like the reset-path blip above (skip, log a
        # warning, no error-tracking capture) rather than unconditionally reported as a defect.
        schema, job = self._schema_and_job(team)
        corrupt_check_error = OSError(
            "Operation not supported: an error occurred while loading credentials: dispatch failure: "
            "timeout: client error (Connect): HTTP connect timeout occurred after 3.1s: timed out"
        )
        helper = MagicMock(is_table_corrupted=AsyncMock(side_effect=corrupt_check_error), reset_table=AsyncMock())
        logger = self._logger()

        with (
            patch(f"{_EXTRACT_MODULE}.posthoganalytics"),
            patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture,
        ):
            result = async_to_sync(handle_corrupted_delta_log)(schema, job, helper, logger)

        assert result is False
        mock_capture.assert_not_called()
        helper.reset_table.assert_not_awaited()
        logger.awarning.assert_awaited()
        job.refresh_from_db()
        assert job.billable is True

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

        repartition_module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition"
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


# transaction=True: the helper saves the job via the async thread pool, which can't see an
# atomic TestCase's uncommitted rows.
@pytest.mark.django_db(transaction=True)
class TestResetRowsSyncedIfNeeded:
    def _job_with_leftover_count(self, team) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Postgres"
        )
        schema = ExternalDataSchema.objects.create(name="orders", team=team, source=source, sync_type_config={})
        return ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=1234,
            billable=True,
        )

    @pytest.mark.parametrize(
        "_name,is_incremental,reset_pipeline,should_resume,incremental_cursor_staged,expect_reset",
        [
            # Staged-cursor (v3) incremental retry re-extracts the whole window from batch 0, so a
            # leftover count from the previous attempt would double-count every re-read row — and
            # rows_synced feeds billed usage. This is the regression case.
            ("staged_cursor_incremental_retry_resets", True, False, False, True, True),
            # A resumable source picks up the previous attempt's staged batches, so its rows stay counted.
            ("resumable_source_keeps_count", True, False, True, True, False),
            # Durable-cursor (v2) incremental retry resumes past the rows already counted.
            ("durable_cursor_incremental_retry_keeps_count", True, False, False, False, False),
            ("full_refresh_restart_resets", False, False, False, False, True),
            ("reset_pipeline_resets", True, True, False, False, True),
        ],
    )
    def test_reset_conditions(
        self,
        _name: str,
        is_incremental: bool,
        reset_pipeline: bool,
        should_resume: bool,
        incremental_cursor_staged: bool,
        expect_reset: bool,
        team,
    ) -> None:
        job = self._job_with_leftover_count(team)

        async_to_sync(reset_rows_synced_if_needed)(
            job,
            is_incremental,
            reset_pipeline,
            should_resume,
            incremental_cursor_staged=incremental_cursor_staged,
        )

        job.refresh_from_db()
        assert job.rows_synced == (0 if expect_reset else 1234)


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
        # An explicit reset redoes the initial sync, so the latch must drop (CDC's snapshot->
        # streaming flip fires on the False->True transition).
        assert schema.initial_sync_complete is False

    def test_full_refresh_sync_keeps_initial_sync_complete(self, team):
        # The prod regression: routine full-refresh runs cleared the latch at extraction start,
        # and a zero-row run never reaches post-load to re-set it, so the flag read false
        # between runs on ~1k schemas despite daily completed syncs.
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Clickhouse"
        )
        schema = ExternalDataSchema.objects.create(
            name="events",
            team=team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"incremental_field_last_value": "2026-01-01T00:00:00"},
            initial_sync_complete=True,
        )
        helper = MagicMock(reset_table=AsyncMock())

        async_to_sync(handle_reset_or_full_refresh)(
            False, False, schema, helper, MagicMock(adebug=AsyncMock()), webhook_only=False
        )

        helper.reset_table.assert_awaited_once()
        assert schema.initial_sync_complete is True
        schema.refresh_from_db()
        assert schema.initial_sync_complete is True
        assert "incremental_field_last_value" not in schema.sync_type_config


class TestValidateIncrementalSync:
    @parameterized.expand(
        [
            # The failure this guard exists for: a keyless incremental table can never merge into
            # the Delta table that an earlier run already wrote.
            ("keyless_incremental_after_first_sync_raises", True, False, None, True),
            # The first run writes the whole table, so it doesn't need a merge key. Raising here
            # would break every initial sync of a keyless table.
            ("keyless_incremental_first_sync_allowed", True, True, None, False),
            # Full refresh overwrites, so it never merges on a key.
            ("keyless_full_refresh_allowed", False, False, None, False),
            ("incremental_with_key_allowed", True, False, ["id"], False),
        ]
    )
    def test_missing_primary_keys(
        self,
        _name: str,
        is_incremental: bool,
        is_first_sync: bool,
        primary_keys: list[str] | None,
        expect_raise: bool,
    ):
        resource = MagicMock(primary_keys=primary_keys, has_duplicate_primary_keys=False)

        if not expect_raise:
            validate_incremental_sync(is_incremental, resource, is_first_sync=is_first_sync)
            return

        with pytest.raises(MissingPrimaryKeysException):
            validate_incremental_sync(is_incremental, resource, is_first_sync=is_first_sync)

    def test_message_stays_classified_as_non_retryable(self):
        # The message is what pauses the schema: without a matching Any_Source_Errors entry the
        # run is retried on every schedule even though only the user can resolve it.
        message = str(MissingPrimaryKeysException())
        assert [key for key in Any_Source_Errors if key in message]


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_yields_none_when_ping_fails(self):
        # `handle_non_retryable_error` only takes its Redis-unreachable fast-fail path when the
        # yielded client is None; otherwise it calls `.incr()` on the broken client, which raises
        # the same connection error uncaught instead of failing fast as NonRetryableException.
        # `get_async_client` only builds a lazy client, so a failed ping is the only signal that
        # the client is unusable - it must reset the client to None rather than yield it as-is.
        broken_client = AsyncMock(ping=AsyncMock(side_effect=ConnectionError("Connect call failed")))

        with (
            patch(f"{_EXTRACT_MODULE}.settings") as mock_settings,
            patch(f"{_EXTRACT_MODULE}.get_async_client", return_value=broken_client),
            patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture,
        ):
            mock_settings.DATA_WAREHOUSE_REDIS_HOST = "localhost"
            mock_settings.DATA_WAREHOUSE_REDIS_PORT = 6379

            async with _get_redis() as redis_client:
                assert redis_client is None

        mock_capture.assert_called_once()


class TestHandleNonRetryableError:
    def _fake_get_redis(self, incr_return: int):
        redis_client = MagicMock(incr=AsyncMock(return_value=incr_return), expire=AsyncMock())

        @asynccontextmanager
        async def _get_redis():
            yield redis_client

        return _get_redis

    def test_retry_attempt_is_not_reported_to_error_tracking(self):
        # `handle_non_retryable_error` only runs once a source has already classified `error` as
        # a known non-retryable condition (e.g. Meta Ads' "Ad account owner has NOT granted
        # ads_read permission"). Re-raising the raw `error` on a below-limit attempt reported that
        # already-understood error to error tracking on every retry; it must come back as a
        # NonReportableError so the activity interceptor skips capturing it.
        original_error = ValueError("Ad account owner has NOT granted ads_read permission")

        with patch(f"{_EXTRACT_MODULE}._get_redis", self._fake_get_redis(incr_return=1)):
            with pytest.raises(NonReportableError) as exc_info:
                async_to_sync(handle_non_retryable_error)(
                    1, "source-1", "run-1", str(original_error), MagicMock(adebug=AsyncMock()), original_error
                )

        assert not isinstance(exc_info.value, NonRetryableException)
        assert exc_info.value.__cause__ is original_error

    def test_gives_up_after_retry_limit_without_reporting(self):
        # Past the retry budget, the give-up exception is the exact same already-classified
        # condition and must stay out of error tracking too.
        original_error = ValueError("Ad account owner has NOT granted ads_read permission")

        with patch(
            f"{_EXTRACT_MODULE}._get_redis", self._fake_get_redis(incr_return=NON_RETRYABLE_ERROR_RETRY_LIMIT + 1)
        ):
            with pytest.raises(NonRetryableException) as exc_info:
                async_to_sync(handle_non_retryable_error)(
                    1, "source-1", "run-1", str(original_error), MagicMock(adebug=AsyncMock()), original_error
                )

        assert isinstance(exc_info.value, NonReportableError)
        assert exc_info.value.__cause__ is original_error

    def test_redis_error_after_successful_ping_fails_fast(self):
        # A successful ping doesn't guarantee `.incr()` still reaches Redis - if it raises, this
        # must take the same fast-fail path as a `None` client instead of surfacing unwrapped and
        # masking the already-classified `error` behind an ordinary retryable activity failure.
        original_error = ValueError("Ad account owner has NOT granted ads_read permission")
        redis_client = MagicMock(
            incr=AsyncMock(side_effect=redis_exceptions.ConnectionError("Connect call failed")),
            expire=AsyncMock(),
        )

        @asynccontextmanager
        async def fake_get_redis():
            yield redis_client

        with (
            patch(f"{_EXTRACT_MODULE}._get_redis", fake_get_redis),
            patch(f"{_EXTRACT_MODULE}.capture_exception") as mock_capture,
        ):
            with pytest.raises(NonRetryableException) as exc_info:
                async_to_sync(handle_non_retryable_error)(
                    1, "source-1", "run-1", str(original_error), MagicMock(adebug=AsyncMock()), original_error
                )

        assert isinstance(exc_info.value, NonRetryableException)
        assert exc_info.value.__cause__ is original_error
        mock_capture.assert_called_once()
