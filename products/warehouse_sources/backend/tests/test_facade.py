import uuid

from posthog.test.base import BaseTest

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
