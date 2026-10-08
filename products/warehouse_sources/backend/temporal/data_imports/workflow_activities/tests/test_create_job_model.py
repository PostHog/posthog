import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, OperationalError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.temporal.common.posthog_client import is_expected_activity_failure

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
    SourceOrSchemaDeletedError,
    V2PipelineRemovedError,
    V3PipelineLockLostError,
    _build_schema_snapshot,
    _create_job,
    _enrichment_pending,
    _statistics_stale,
    _verify_v3_lock_still_held,
    create_external_data_job_model_activity,
    prepare_run,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model"
CONTROLLER_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller"
DB_RETRY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"


def _prepare(inputs: CreateExternalDataJobModelActivityInputs) -> CreateExternalDataJobModelActivityOutputs:
    return prepare_run(inputs, workflow_id="wf-1", workflow_run_id="run-1", verify_v3_lock=True)


def _team() -> Team:
    org = Organization.objects.create(name="org")
    return Team.objects.create(organization=org, name="t")


def _table(team: Team, *, columns: dict | None = None) -> DataWarehouseTable:
    credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=team)
    return DataWarehouseTable.objects.create(
        name="stripe_charge",
        format="Parquet",
        team=team,
        credential=credential,
        url_pattern="https://bucket.s3/data/*",
        columns=columns or {"amount": {"clickhouse": "Nullable(Int64)"}},
    )


def _schema(team: Team, table: DataWarehouseTable | None, *, description: str | None = None) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    return ExternalDataSchema.objects.create(
        name="Charge", team=team, source=source, table=table, description=description
    )


class TestVerifyV3LockStillHeld:
    RUN_ID = "run-abc-123"
    SCHEMA_ID = uuid.uuid4()

    @parameterized.expand(
        [
            # Own token still on the lock: the normal healthy path must proceed.
            ("holder_matches", "run-abc-123", False),
            # Redis down (or lock vanished): the guard is best-effort — availability must not regress.
            ("redis_unavailable", None, False),
            # Another run took the lock during this run's startup window: fail fast
            # instead of double-writing the Delta table alongside the new holder.
            ("lock_lost_to_other_run", "run-thief-999", True),
        ]
    )
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder")
    def test_lock_guard(
        self,
        _name: str,
        holder: str | None,
        expect_raise: bool,
        mock_get_holder: MagicMock,
    ) -> None:
        mock_get_holder.return_value = holder

        if expect_raise:
            with pytest.raises(V3PipelineLockLostError) as exc_info:
                _verify_v3_lock_still_held(1, self.SCHEMA_ID, run_id=self.RUN_ID)
            # The takeover in acquire_v3_lock.py only steals from a terminal-looking holder, so
            # this is the mechanism working as designed and must not open an error tracking issue.
            assert is_expected_activity_failure(exc_info.value)
        else:
            _verify_v3_lock_still_held(1, self.SCHEMA_ID, run_id=self.RUN_ID)


@pytest.mark.django_db
class TestStatisticsStale:
    def test_stale_when_table_is_none(self) -> None:
        # First-ever sync: the table is created during the sync, so the (post-sync) profiling should run.
        team = _team()
        assert _statistics_stale(team.id, None) is True

    def test_stale_when_no_stats_rows(self) -> None:
        team = _team()
        table = _table(team)
        assert _statistics_stale(team.id, table) is True

    @parameterized.expand(
        [
            # Guards against re-profiling a freshly-computed table on every sync (the bug we're fixing).
            ("recent_not_stale", dt.timedelta(hours=1), False),
            # Guards against never recomputing once a row exists.
            ("older_than_interval_stale", dt.timedelta(hours=25), True),
        ]
    )
    def test_staleness_by_recency(self, _name: str, age: dt.timedelta, expected: bool) -> None:
        team = _team()
        table = _table(team)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team, table=table, column_name="amount", computed_at=timezone.now() - age
        )
        assert _statistics_stale(team.id, table) is expected


@pytest.mark.django_db
class TestEnrichmentPending:
    def _annotate(self, team: Team, table: DataWarehouseTable, column_name: str) -> None:
        WarehouseColumnAnnotation.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name=column_name,
            description="desc",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

    def test_pending_when_table_is_none(self) -> None:
        # First-ever sync: nothing is annotated yet, so there is work to do.
        team = _team()
        assert _enrichment_pending(team.id, None, _schema(team, None)) is True

    def test_pending_when_a_column_is_unannotated(self) -> None:
        # New/undescribed column must re-trigger enrichment, else added columns never get described.
        team = _team()
        table = _table(team, columns={"amount": {}, "currency": {}})
        self._annotate(team, table, "amount")
        # currency has no annotation
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is True

    def test_not_pending_when_all_columns_annotated_and_table_described(self) -> None:
        # The steady state: nothing new to do — must NOT spawn a workflow every sync.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is False

    def test_not_pending_when_only_hidden_columns_unannotated(self) -> None:
        # Hidden plumbing columns (_dlt_id, partition key, …) are never enriched, so they must not
        # count as pending work — otherwise enrichment re-fires on every steady-state sync.
        team = _team()
        table = _table(
            team,
            columns={"amount": {}, "_dlt_id": {}, "_dlt_load_id": {}, "_ph_debug": {}, "_ph_partition_key": {}},
        )
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is False

    def test_pending_when_table_description_missing(self) -> None:
        # Columns all annotated, but neither a schema description nor a table-level ("") annotation exists.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description=None)) is True

    def test_not_pending_when_table_level_annotation_exists(self) -> None:
        # A table-level annotation ("" column) satisfies the table-description requirement.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        self._annotate(team, table, "")
        assert _enrichment_pending(team.id, table, _schema(team, table, description=None)) is False


class TestBuildSchemaSnapshot:
    def test_copies_the_config_without_the_column_list(self) -> None:
        config = {
            "incremental_field": "updated_at",
            "incremental_field_last_value": "2026-09-01T00:00:00+00:00",
            "reset_pipeline": True,
            "schema_metadata": {"columns": [{"name": "id", "type": "int"}]},
        }
        schema = ExternalDataSchema(name="Charge", sync_type="incremental", sync_type_config=dict(config))

        snapshot = _build_schema_snapshot(schema)

        assert snapshot["sync_type_config"] == {
            "incremental_field": "updated_at",
            "incremental_field_last_value": "2026-09-01T00:00:00+00:00",
            "reset_pipeline": True,
        }
        assert snapshot["sync_type"] == "incremental"
        assert schema.sync_type_config == config


@pytest.mark.django_db
class TestCreateJob:
    # Guards the deadlock we saw in production: Postgres can abort the ExternalDataJob INSERT with
    # "deadlock detected" while taking its FK lock on posthog_team. The INSERT leaves no row behind,
    # so retrying from scratch is safe — this activity has no Temporal-level retry (a retry after the
    # job row exists would create a duplicate), so the retry has to happen around the INSERT itself.
    @patch(f"{DB_RETRY_MODULE}.close_old_connections")
    @patch(f"{DB_RETRY_MODULE}.time.sleep")
    def test_retries_once_on_deadlock_then_succeeds(
        self, mock_sleep: MagicMock, mock_close_connections: MagicMock
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        original_create = ExternalDataJob.objects.create

        def flaky_create(*args: object, **kwargs: object) -> ExternalDataJob:
            flaky_create.calls += 1  # type: ignore[attr-defined]
            if flaky_create.calls == 1:  # type: ignore[attr-defined]
                raise OperationalError("deadlock detected")
            return original_create(*args, **kwargs)

        flaky_create.calls = 0  # type: ignore[attr-defined]

        with patch.object(ExternalDataJob.objects, "create", side_effect=flaky_create) as mock_create:
            job = _create_job(
                team_id=team.id,
                source_id=schema.source_id,
                schema_id=schema.id,
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
                billable=True,
                schema_snapshot={},
                workflow_id="wf-1",
                workflow_run_id="run-1",
            )

        assert mock_create.call_count == 2
        assert ExternalDataJob.objects.filter(schema_id=schema.id).count() == 1
        assert job.id is not None
        mock_sleep.assert_called_once()

    @parameterized.expand(
        [
            ("v2_run", False, None, False),
            ("v3_run_holding_its_lock", True, "temporal-run", False),
            ("v3_run_that_lost_its_lock", True, "another-run", True),
        ]
    )
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.activity")
    def test_the_activity_runs_under_its_own_temporal_ids(
        self,
        _name: str,
        is_v3: bool,
        holder: str | None,
        expect_lock_lost: bool,
        mock_activity: MagicMock,
        _mock_close_connections: MagicMock,
        mock_get_holder: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_id = "schema-wf"
        mock_activity.info.return_value.workflow_run_id = "temporal-run"
        mock_get_holder.return_value = holder
        team = _team()
        schema = _schema(team, None)
        inputs = CreateExternalDataJobModelActivityInputs(
            team_id=team.id, schema_id=schema.id, source_id=schema.source_id, billable=True, is_v3=is_v3
        )

        if expect_lock_lost:
            with pytest.raises(V3PipelineLockLostError):
                create_external_data_job_model_activity(inputs)
            assert not ExternalDataJob.objects.filter(schema_id=schema.id).exists()
            return

        result = create_external_data_job_model_activity(inputs)

        job = ExternalDataJob.objects.get(id=result.job_id)
        assert (job.workflow_id, job.workflow_run_id) == ("schema-wf", "temporal-run")


@pytest.mark.django_db
class TestCreateJobActivityStatusOrdering:
    # The Running status must only be persisted once the job row exists: a Running schema with no
    # job behind it can never be finalized, so it stays stuck on Running forever and blocks cancel.
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}._create_job", side_effect=OperationalError("insert failed"))
    @patch(f"{MODULE}._verify_v3_lock_still_held")
    def test_schema_not_left_running_when_job_creation_fails(
        self, _mock_verify_lock: MagicMock, _mock_create: MagicMock, _mock_close_connections: MagicMock
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        schema.status = ExternalDataSchema.Status.FAILED
        schema.save()

        inputs = CreateExternalDataJobModelActivityInputs(
            team_id=team.id,
            schema_id=schema.id,
            source_id=schema.source_id,
            billable=True,
        )

        with pytest.raises(OperationalError):
            _prepare(inputs)

        schema.refresh_from_db()
        assert schema.status == ExternalDataSchema.Status.FAILED

    # A replayed pre-patch history can still ask for a V2 job. The V2 pipeline is gone, so the
    # run must fail before it creates a job row that no pipeline can run.
    @patch(f"{MODULE}.close_old_connections")
    def test_a_v2_request_fails_without_creating_a_job(self, _mock_close_connections: MagicMock) -> None:
        team = _team()
        schema = _schema(team, None)

        with pytest.raises(V2PipelineRemovedError):
            create_external_data_job_model_activity(
                CreateExternalDataJobModelActivityInputs(
                    team_id=team.id, schema_id=schema.id, source_id=schema.source_id, billable=True, is_v3=False
                )
            )

        assert not ExternalDataJob.objects.filter(schema_id=schema.id).exists()

    @parameterized.expand([("broken", "cdc_broken"), ("paused", "cdc_extraction_paused")])
    @patch(f"{MODULE}.close_old_connections")
    def test_a_halted_cdc_schema_keeps_its_failed_status(
        self, _name: str, marker: str, _mock_close_connections: MagicMock
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        schema.status = ExternalDataSchema.Status.FAILED
        schema.sync_type_config = {marker: {"reason": "critical_lag_self_managed"}}
        schema.save()

        _prepare(
            CreateExternalDataJobModelActivityInputs(
                team_id=team.id, schema_id=schema.id, source_id=schema.source_id, billable=True
            )
        )

        schema.refresh_from_db()
        assert ExternalDataJob.objects.filter(schema_id=schema.id).exists()
        assert schema.status == ExternalDataSchema.Status.FAILED


@pytest.mark.django_db
class TestCreateJobActivityScheduledFullRefresh:
    @parameterized.expand(
        [
            ("due_on_a_scheduled_run", True, dt.timedelta(days=-1), {}, False, True),
            ("due_on_a_directly_started_run", False, dt.timedelta(days=-1), {}, False, False),
            ("not_yet_due", True, dt.timedelta(days=1), {}, False, False),
            (
                "due_with_a_staged_repartition_swap",
                True,
                dt.timedelta(days=-1),
                {"repartition_swap": {"state": "ready", "temp_uri": "s3://temp", "live_uri": "s3://live"}},
                False,
                False,
            ),
            (
                "due_with_a_held_repartition_rewrite",
                True,
                dt.timedelta(days=-1),
                {"repartition_rewrite": {"temp_uri": "s3://temp", "rows_written": 10}},
                True,
                False,
            ),
            (
                "due_with_a_rewrite_while_the_hold_flag_is_off",
                True,
                dt.timedelta(days=-1),
                {"repartition_rewrite": {"temp_uri": "s3://temp", "rows_written": 10}},
                False,
                True,
            ),
            (
                "due_with_a_queued_repartition",
                True,
                dt.timedelta(days=-1),
                {"repartition_pending": {"partition_mode": "datetime", "partition_keys": ["created_at"]}},
                False,
                True,
            ),
        ]
    )
    @patch(f"{MODULE}.close_old_connections")
    def test_only_a_due_scheduled_run_becomes_a_full_refresh(
        self,
        _name: str,
        started_by_schedule: bool,
        due_in: dt.timedelta,
        repartition_config: dict,
        hold_flag_enabled: bool,
        expect_refresh: bool,
        _mock_close_connections: MagicMock,
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        schema.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
        schema.full_refresh_interval_days = 7
        schema.next_full_refresh_at = timezone.now() + due_in
        config = {**(schema.sync_type_config or {}), **repartition_config}
        if "repartition_rewrite" in config:
            config["repartition_rewrite"] = {**config["repartition_rewrite"], "held_at": timezone.now().isoformat()}
        schema.sync_type_config = config
        schema.save()

        with patch(f"{CONTROLLER_MODULE}.is_repartition_hold_enabled", return_value=hold_flag_enabled):
            result = _prepare(
                CreateExternalDataJobModelActivityInputs(
                    team_id=team.id,
                    schema_id=schema.id,
                    source_id=schema.source_id,
                    billable=True,
                    started_by_schedule=started_by_schedule,
                )
            )

        schema.refresh_from_db()
        snapshot = ExternalDataJob.objects.get(schema_id=schema.id).schema_snapshot
        assert snapshot is not None
        assert result.scheduled_full_refresh is expect_refresh
        assert snapshot.get("scheduled_full_refresh", False) is expect_refresh
        assert schema.reset_pipeline is False


@pytest.mark.django_db
class TestCreateJobActivityDeletedSourceOrSchema:
    # Deleting a source or a schema cancels its schedule, but a run Temporal already started still
    # reaches this activity and finds the rows gone. The activity has to cancel the leftover
    # schedule and fail with an error the interceptor will not report, or the race opens an error
    # tracking issue per orphaned run.
    @parameterized.expand(
        [
            ("source_deleted", True, False),
            ("schema_deleted", False, True),
        ]
    )
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.delete_external_data_schedule")
    def test_schedule_is_cancelled_and_the_failure_is_not_reported(
        self,
        _name: str,
        delete_source: bool,
        delete_schema: bool,
        mock_delete_schedule: MagicMock,
        _mock_close_connections: MagicMock,
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        if delete_source:
            schema.source.deleted = True
            schema.source.save()
        if delete_schema:
            schema.deleted = True
            schema.save()

        inputs = CreateExternalDataJobModelActivityInputs(
            team_id=team.id,
            schema_id=schema.id,
            source_id=schema.source_id,
            billable=True,
        )

        with pytest.raises(SourceOrSchemaDeletedError) as exc_info:
            _prepare(inputs)

        assert is_expected_activity_failure(exc_info.value)
        mock_delete_schedule.assert_called_once_with(str(schema.id))
        assert ExternalDataJob.objects.filter(schema_id=schema.id).count() == 0

    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.delete_external_data_schedule")
    @patch(f"{MODULE}._create_job")
    @patch(f"{MODULE}._verify_v3_lock_still_held")
    def test_integrity_error_on_insert_is_treated_as_the_same_race(
        self,
        _mock_verify_lock: MagicMock,
        mock_create_job: MagicMock,
        mock_delete_schedule: MagicMock,
        _mock_close_connections: MagicMock,
    ) -> None:
        # The row can still vanish (e.g. a team deletion cascading to its source/schema) between
        # the existence check passing and the insert itself, surfacing as a raw IntegrityError
        # instead of the early check catching it.
        team = _team()
        schema = _schema(team, None)
        mock_create_job.side_effect = IntegrityError(
            'insert or update on table "posthog_externaldatajob" violates foreign key constraint'
        )

        inputs = CreateExternalDataJobModelActivityInputs(
            team_id=team.id,
            schema_id=schema.id,
            source_id=schema.source_id,
            billable=True,
        )

        with pytest.raises(SourceOrSchemaDeletedError) as exc_info:
            _prepare(inputs)

        assert is_expected_activity_failure(exc_info.value)
        mock_delete_schedule.assert_called_once_with(str(schema.id))


@pytest.mark.django_db
class TestCreateJobActivityPrepareRunOutputs:
    @parameterized.expand(
        [
            ("non_billable_run_is_never_limited", False, True, False),
            ("billable_run_under_quota", True, False, False),
            ("billable_run_over_quota", True, True, True),
        ]
    )
    @patch(f"{MODULE}.close_old_connections")
    def test_answers_the_billing_limit_with_the_job_row(
        self,
        _name: str,
        billable: bool,
        team_limited: bool,
        expect_hit: bool,
        _mock_close_connections: MagicMock,
    ) -> None:
        team = _team()
        schema = _schema(team, None)
        # Past the free window for a new source, so only the quota decides.
        ExternalDataSource.objects.filter(id=schema.source_id).update(created_at=timezone.now() - dt.timedelta(days=30))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits.is_team_limited",
            return_value=team_limited,
        ):
            result = _prepare(
                CreateExternalDataJobModelActivityInputs(
                    team_id=team.id, schema_id=schema.id, source_id=schema.source_id, billable=billable
                )
            )

        assert result.billing_limit_checked is True
        assert result.hit_billing_limit is expect_hit
        assert ExternalDataJob.objects.filter(schema_id=schema.id).count() == 1

    @parameterized.expand(
        [
            ("stripe_first_sync", "Stripe", False, True),
            ("stripe_after_a_completed_sync", "Stripe", True, False),
            ("other_source", "Postgres", False, False),
        ]
    )
    @patch(f"{MODULE}.close_old_connections")
    def test_source_templates_needed_only_for_a_stripe_sources_first_sync(
        self,
        _name: str,
        source_type: str,
        has_completed_job: bool,
        expected: bool,
        _mock_close_connections: MagicMock,
    ) -> None:
        team = _team()
        source = ExternalDataSource.objects.create(
            source_id="src", connection_id="conn", team=team, source_type=source_type
        )
        schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source)
        if has_completed_job:
            ExternalDataJob.objects.create(
                team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.COMPLETED, rows_synced=0
            )

        result = _prepare(
            CreateExternalDataJobModelActivityInputs(
                team_id=team.id, schema_id=schema.id, source_id=source.id, billable=False
            )
        )

        assert result.source_templates_needed is expected
