import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.data_warehouse.backend.facade.models import ExternalDataSourceRevenueAnalyticsConfig
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

    def test_list_revenue_sources_maps_settings_schemas_and_tables(self) -> None:
        other_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
            prefix="other_",
        )
        other_table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="other_table",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/other/*",
            external_data_source=other_source,
        )
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=other_source,
            name="orders",
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            table=other_table,
        )

        with self.assertNumQueries(2):
            results = api.list_revenue_sources(self.team.pk, source_types=["Postgres"])

        assert {source.id: source for source in results} == {
            self.source.id: contracts.RevenueSource(
                id=self.source.id,
                source_type="Postgres",
                prefix="stripe_",
                enabled=False,
                include_invoiceless_charges=True,
                schemas=(
                    contracts.RevenueSourceSchema(
                        name="users",
                        table=contracts.RevenueSourceTable(id=self.table.id, name="my_table"),
                    ),
                ),
            ),
            other_source.id: contracts.RevenueSource(
                id=other_source.id,
                source_type="Postgres",
                prefix="other_",
                enabled=False,
                include_invoiceless_charges=True,
                schemas=(
                    contracts.RevenueSourceSchema(
                        name="orders",
                        table=contracts.RevenueSourceTable(id=other_table.id, name="other_table"),
                    ),
                ),
            ),
        }

    def test_list_revenue_sources_enforces_team_isolation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")

        assert api.list_revenue_sources(other_team.pk) == []

    def test_list_revenue_sources_does_not_create_missing_settings(self) -> None:
        ExternalDataSourceRevenueAnalyticsConfig.objects.filter(external_data_source=self.source).delete()

        results = api.list_revenue_sources(self.team.pk, source_types=["Postgres"])

        assert results[0].enabled is False
        assert not ExternalDataSourceRevenueAnalyticsConfig.objects.filter(external_data_source=self.source).exists()

    def test_list_revenue_source_settings_can_include_deleted_sources(self) -> None:
        self.source.deleted = True
        self.source.save(update_fields=["deleted"])

        with self.assertNumQueries(1):
            results = api.list_revenue_source_settings(
                self.team.pk,
                include_deleted=True,
                source_ids=[self.source.id],
            )

        assert results == [
            contracts.RevenueSourceSettings(
                id=self.source.id,
                source_type="Postgres",
                prefix="stripe_",
                deleted=True,
                enabled=False,
            )
        ]

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

    @parameterized.expand(
        [
            ("legacy_viewer", False, "viewer"),
            ("legacy_editor", False, "editor"),
            ("most_specific_viewer", True, "viewer"),
            ("most_specific_editor", True, "editor"),
        ]
    )
    def test_allowed_table_ids_preserves_object_and_source_grants(
        self, _name: str, most_specific: bool, required_level: AccessControlLevel
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save(update_fields=["available_product_features", "uses_most_specific_access_resolution"])
        member = self._create_user("member@example.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=str(self.source.id),
            organization_member=membership,
            access_level="viewer",
        )
        granted = DataWarehouseTable.objects.create(team=self.team, name="granted", format="Parquet")
        overridden = DataWarehouseTable.objects.create(
            team=self.team, name="overridden", format="Parquet", external_data_source=self.source
        )
        ungranted = DataWarehouseTable.objects.create(team=self.team, name="ungranted", format="Parquet")
        owned = DataWarehouseTable.objects.create(team=self.team, name="owned", format="Parquet", created_by=member)
        DataWarehouseTable.objects.create(
            team=self.team, name="deleted", format="Parquet", created_by=member, deleted=True
        )
        other_team = Team.objects.create(organization=self.organization, name="other")
        DataWarehouseTable.objects.create(team=other_team, name="other", format="Parquet", created_by=member)
        for table, level in [(granted, "editor"), (overridden, "none")]:
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_table",
                resource_id=str(table.id),
                organization_member=membership,
                access_level=level,
            )

        access = UserAccessControl(member, team=self.team)
        expected = frozenset({granted.id, owned.id} | ({self.table.id} if required_level == "viewer" else set()))
        assert api.allowed_table_ids(self.team.id, access, required_level=required_level) == expected
        with self.assertNumQueries(0):
            assert api.allowed_table_ids(self.team.id, access, required_level=required_level) == expected

        narrowed = api.allowed_table_ids(
            self.team.id, access, required_level=required_level, ids=[granted.id, ungranted.id]
        )
        assert narrowed == frozenset({granted.id})
        with self.assertNumQueries(0):
            assert api.allowed_table_ids(self.team.id, access, required_level=required_level, ids=[]) == frozenset()

        membership.level = OrganizationMembership.Level.ADMIN
        membership.save(update_fields=["level"])
        admin = UserAccessControl(member, team=self.team)
        assert api.allowed_table_ids(self.team.id, admin, required_level=required_level) == frozenset(
            {self.table.id, granted.id, overridden.id, ungranted.id, owned.id}
        )

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
