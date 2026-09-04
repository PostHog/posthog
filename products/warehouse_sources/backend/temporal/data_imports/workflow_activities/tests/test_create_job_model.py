import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    _create_job,
    _enrichment_pending,
    _statistics_stale,
    _verify_v3_lock_still_held,
    create_external_data_job_model_activity,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model"
DB_RETRY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"


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
    @patch(f"{MODULE}.activity")
    def test_lock_guard(
        self,
        _name: str,
        holder: str | None,
        expect_raise: bool,
        mock_activity: MagicMock,
        mock_get_holder: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = self.RUN_ID
        mock_get_holder.return_value = holder

        if expect_raise:
            with pytest.raises(ApplicationError) as exc_info:
                _verify_v3_lock_still_held(1, self.SCHEMA_ID)
            assert exc_info.value.non_retryable is True
        else:
            _verify_v3_lock_still_held(1, self.SCHEMA_ID)


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


@pytest.mark.django_db
class TestCreateJob:
    # Guards the deadlock we saw in production: Postgres can abort the ExternalDataJob INSERT with
    # "deadlock detected" while taking its FK lock on posthog_team. The INSERT leaves no row behind,
    # so retrying from scratch is safe — this activity has no Temporal-level retry (a retry after the
    # job row exists would create a duplicate), so the retry has to happen around the INSERT itself.
    @patch(f"{DB_RETRY_MODULE}.close_old_connections")
    @patch(f"{DB_RETRY_MODULE}.time.sleep")
    @patch(f"{MODULE}.activity")
    def test_retries_once_on_deadlock_then_succeeds(
        self, mock_activity: MagicMock, mock_sleep: MagicMock, mock_close_connections: MagicMock
    ) -> None:
        mock_activity.info.return_value.workflow_id = "wf-1"
        mock_activity.info.return_value.workflow_run_id = "run-1"

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
                pipeline_version=ExternalDataJob.PipelineVersion.V2,
                billable=True,
                schema_snapshot={},
            )

        assert mock_create.call_count == 2
        assert ExternalDataJob.objects.filter(schema_id=schema.id).count() == 1
        assert job.id is not None
        mock_sleep.assert_called_once()


@pytest.mark.django_db
class TestCreateJobActivityStatusOrdering:
    # The Running status must only be persisted once the job row exists: a Running schema with no
    # job behind it can never be finalized, so it stays stuck on Running forever and blocks cancel.
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}._create_job", side_effect=OperationalError("insert failed"))
    def test_schema_not_left_running_when_job_creation_fails(
        self, _mock_create: MagicMock, _mock_close_connections: MagicMock
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
            create_external_data_job_model_activity(inputs)

        schema.refresh_from_db()
        assert schema.status == ExternalDataSchema.Status.FAILED
