import uuid
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.warehouse_sources.backend.facade import api, contracts, hogql, hooks, sources, temporal
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestWarehouseSourcesFacade(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
            prefix="stripe_",
        )
        self.table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="my_table",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/x/*",
            external_data_source=self.source,
        )
        self.schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=self.source,
            name="users",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            table=self.table,
        )

    def test_get_source_maps_to_contract(self) -> None:
        result = api.get_source(self.source.id, self.team.pk)
        assert isinstance(result, contracts.ExternalDataSource)
        assert result.id == self.source.id
        assert result.team_id == self.team.pk
        assert result.source_type == "Postgres"
        assert result.prefix == "stripe_"
        assert result.status == "Completed"
        # derived properties carried through the mapper unchanged
        assert result.is_direct_query == self.source.is_direct_query
        assert result.direct_engine == self.source.direct_engine

    def test_list_sources_excludes_deleted_by_default(self) -> None:
        deleted = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Stripe",
            deleted=True,
        )
        assert self.source.id in {s.id for s in api.list_sources(self.team.pk)}
        assert deleted.id not in {s.id for s in api.list_sources(self.team.pk)}
        assert deleted.id in {s.id for s in api.list_sources(self.team.pk, include_deleted=True)}

    def test_get_schema_maps_fields_and_source_type(self) -> None:
        result = api.get_schema(self.schema.id, self.team.pk)
        assert isinstance(result, contracts.ExternalDataSchema)
        assert result.id == self.schema.id
        assert result.name == "users"
        assert result.should_sync is True
        assert result.source_id == self.source.id
        assert result.table_id == self.table.id
        # source_type is traversed from the related source
        assert result.source_type == "Postgres"
        assert result.normalized_name == self.schema.normalized_name

    def test_list_schemas_for_source(self) -> None:
        results = api.list_schemas_for_source(self.source.id, self.team.pk)
        assert [r.id for r in results] == [self.schema.id]

    def test_get_table_maps_to_contract(self) -> None:
        result = api.get_table(self.table.id, self.team.pk)
        assert isinstance(result, contracts.DataWarehouseTable)
        assert result.name == "my_table"
        assert result.external_data_source_id == self.source.id

    def test_list_jobs_for_source_carries_source_fields(self) -> None:
        job = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=self.source,
            schema=self.schema,
            status="Completed",
            schema_snapshot={},
            rows_synced=10,
        )
        results = api.list_jobs_for_source(self.source.id, self.team.pk)
        assert [r.id for r in results] == [job.id]
        assert results[0].rows_synced == 10
        assert results[0].source_type == "Postgres"
        assert results[0].source_prefix == "stripe_"

    def test_facade_enforces_team_isolation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with self.assertRaises(ExternalDataSource.DoesNotExist):
            api.get_source(self.source.id, other_team.pk)

    def _job(
        self,
        status: str,
        *,
        finished_ago: timedelta | None = None,
        created_ago: timedelta = timedelta(hours=1),
        error: str | None = None,
        rows: int = 0,
        source: ExternalDataSource | None = None,
    ) -> ExternalDataJob:
        job = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source or self.source,
            schema=self.schema,
            status=status,
            schema_snapshot={},
            rows_synced=rows,
            latest_error=error,
            finished_at=None if finished_ago is None else timezone.now() - finished_ago,
        )
        # created_at is auto_now_add; the error-resolution rule orders on it.
        ExternalDataJob.objects.filter(id=job.id).update(created_at=timezone.now() - created_ago)
        return job

    @parameterized.expand(
        [
            ("no_jobs_is_never", [], "never", None),
            ("recent_completed_is_ok", [("Completed", timedelta(minutes=10), None)], "ok", None),
            ("old_completed_is_stale", [("Completed", timedelta(hours=25), None)], "stale", None),
            (
                "failed_after_completed_is_error",
                [("Completed", timedelta(hours=2), None), ("Failed", timedelta(hours=1), "boom")],
                "error",
                "boom",
            ),
            (
                "completed_after_failed_resolves_error",
                [("Failed", timedelta(hours=2), "boom"), ("Completed", timedelta(hours=1), None)],
                "ok",
                None,
            ),
        ]
    )
    @freeze_time("2026-06-15")
    def test_source_health_job_states(self, _name, jobs, expected_status, expected_error) -> None:
        for status, ago, error in jobs:
            self._job(status, finished_ago=ago if status == "Completed" else None, created_ago=ago, error=error)

        health = api.get_source_health(self.source.id, self.team.pk)

        assert health.sync_status == expected_status
        assert health.last_unresolved_error == expected_error

    @parameterized.expand(
        [
            ("required_name_absent_is_tables_missing", ["users", "orders"], None, True, "tables_missing"),
            (
                "required_schema_failed_is_tables_failed",
                ["users"],
                ExternalDataSchema.Status.FAILED,
                True,
                "tables_failed",
            ),
            ("required_schema_disabled_is_tables_disabled", ["users"], None, False, "tables_disabled"),
        ]
    )
    @freeze_time("2026-06-15")
    def test_source_health_required_schema_states(
        self, _name, required_names, schema_status, should_sync, expected_status
    ) -> None:
        if schema_status is not None:
            self.schema.status = schema_status
        self.schema.should_sync = should_sync
        self.schema.save()
        # A recent successful sync must NOT mask required-table problems.
        self._job("Completed", finished_ago=timedelta(minutes=10))

        health = api.get_source_health(self.source.id, self.team.pk, required_schema_names=required_names)

        assert health.sync_status == expected_status
        assert {s.schema_name for s in health.schemas} == set(required_names)

    @freeze_time("2026-06-15")
    def test_source_health_without_required_names_ignores_failed_optional_schema(self) -> None:
        self.schema.status = ExternalDataSchema.Status.FAILED
        self.schema.save()
        self._job("Completed", finished_ago=timedelta(minutes=10))

        health = api.get_source_health(self.source.id, self.team.pk)

        assert health.sync_status == "ok"
        assert [s.schema_name for s in health.schemas] == ["users"]

    @freeze_time("2026-06-15")
    def test_source_health_row_windows(self) -> None:
        self._job("Completed", finished_ago=timedelta(hours=1), rows=100)
        self._job("Completed", finished_ago=timedelta(days=3), rows=40)
        self._job("Completed", finished_ago=timedelta(days=10), rows=7)

        health = api.get_source_health(self.source.id, self.team.pk)

        assert health.rows_synced_last_24h == 100
        assert health.rows_synced_last_7d == 140

    @freeze_time("2026-06-15")
    def test_list_source_health_attributes_jobs_to_the_right_source(self) -> None:
        other = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Stripe",
        )
        self._job("Completed", finished_ago=timedelta(minutes=10), rows=100)
        self._job("Failed", created_ago=timedelta(minutes=5), error="stripe down", source=other)

        healths = {h.source_id: h for h in api.list_source_health(self.team.pk)}

        assert healths[self.source.id].sync_status == "ok"
        assert healths[self.source.id].rows_synced_last_24h == 100
        assert healths[other.id].sync_status == "error"
        assert healths[other.id].last_unresolved_error == "stripe down"

    def test_list_jobs_for_source_is_bounded_and_get_latest_job_orders_by_created(self) -> None:
        oldest = self._job("Completed", finished_ago=timedelta(hours=3), created_ago=timedelta(hours=3))
        middle = self._job("Failed", created_ago=timedelta(hours=2), error="x")
        newest = self._job("Completed", finished_ago=timedelta(hours=1), created_ago=timedelta(hours=1))

        limited = api.list_jobs_for_source(self.source.id, self.team.pk, limit=2)
        assert [j.id for j in limited] == [newest.id, middle.id]

        latest = api.get_latest_job(self.team.pk, source_id=self.source.id)
        assert latest is not None and latest.id == newest.id
        latest_completed = api.get_latest_job(self.team.pk, source_id=self.source.id, status="Completed")
        assert latest_completed is not None and latest_completed.id == newest.id
        assert oldest.id not in {j.id for j in limited}


def test_hogql_reexports_are_the_model_classes() -> None:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource as _Source
    from products.warehouse_sources.backend.models.table import DataWarehouseTable as _Table

    assert hogql.ExternalDataSource is _Source
    assert hogql.DataWarehouseTable is _Table
    assert callable(hogql.get_view_or_table_by_name)


def test_wiring_reexports_resolve() -> None:
    assert callable(hooks.register_revenue_view_sync)
    assert callable(hooks.register_emit_signals_gate)
    assert hooks.EmitSignalsActivityInputs is not None
    assert temporal.ACTIVITIES is not None and temporal.WORKFLOWS is not None
    assert isinstance(sources.CHARGE_RESOURCE_NAME, str)
    assert sources.NamingConvention is not None
