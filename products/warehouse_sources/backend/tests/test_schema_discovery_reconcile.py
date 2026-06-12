import uuid

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


# Managed/scheduled discovery calls sync_old_schemas_with_new_schemas with no rename step, so a
# qualified/bare name mismatch against the stored row used to flip the live row to should_sync=False.
class TestSchemaDiscoveryReconcile(BaseTest):
    def _make_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )

    def _make_synced_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        table = DataWarehouseTable.objects.create(
            name=f"postgres_{name}".replace(".", "_"),
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="https://bucket/team_1/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name=name,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            table=table,
        )

    @parameterized.expand(
        [
            # (stored name on the live synced row, the single name discovery currently emits)
            ("stored_qualified_discovery_bare", "public.campaign_runs", "campaign_runs"),
            ("stored_bare_discovery_qualified", "campaign_runs", "public.campaign_runs"),
        ]
    )
    def test_discovery_does_not_disable_live_synced_schema_on_qualification_mismatch(
        self, _name: str, stored_name: str, discovered_name: str
    ) -> None:
        source = self._make_source()
        synced_schema = self._make_synced_schema(source, stored_name)

        # Discovery returns the same physical table under the other qualification.
        sync_old_schemas_with_new_schemas(
            {discovered_name: None},
            source_id=str(source.pk),
            team_id=self.team.pk,
        )

        synced_schema.refresh_from_db()
        assert synced_schema.should_sync is True, (
            f"live synced schema {stored_name!r} was disabled when discovery emitted {discovered_name!r} "
            "— qualification mismatch must not be treated as a removed table"
        )
        assert synced_schema.table_id is not None

    def test_multi_schema_same_named_tables_stay_distinct(self) -> None:
        # Multi-schema mode (no single schema configured) emits everything qualified. A new
        # same-named table in another schema must be created, not collapsed onto the existing one.
        source = self._make_source()
        existing = self._make_synced_schema(source, "public.users")

        created, _deleted = sync_old_schemas_with_new_schemas(
            {"public.users": None, "analytics.users": None},
            source_id=str(source.pk),
            team_id=self.team.pk,
        )

        existing.refresh_from_db()
        assert existing.should_sync is True
        assert "analytics.users" in created
        assert ExternalDataSchema.objects.filter(source_id=source.pk, name="analytics.users").exists()


SERVICE = "products.data_warehouse.backend.data_load.service"


class TestSchemaDiscoveryScheduleCleanup(BaseTest):
    def _make_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )

    def test_vanished_schema_with_table_is_disabled_and_schedule_converged(self) -> None:
        source = self._make_source()
        table = DataWarehouseTable.objects.create(
            name="postgres_orders",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="https://bucket/team_1/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="orders",
            should_sync=True,
            table=table,
        )

        with mock.patch(f"{SERVICE}.sync_schema_schedule_state") as converge_mock:
            sync_old_schemas_with_new_schemas({}, source_id=str(source.pk), team_id=self.team.pk)

        schema.refresh_from_db()
        assert schema.should_sync is False
        assert schema.deleted is False
        assert converge_mock.call_count == 1
        assert converge_mock.call_args.args[0].id == schema.id

    def test_vanished_schema_without_table_deletes_schedule_then_soft_deletes(self) -> None:
        source = self._make_source()
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="orders",
            should_sync=True,
        )

        with mock.patch(f"{SERVICE}.delete_external_data_schedule") as delete_mock:
            _, deleted = sync_old_schemas_with_new_schemas({}, source_id=str(source.pk), team_id=self.team.pk)

        schema.refresh_from_db()
        assert schema.deleted is True
        assert deleted == ["orders"]
        delete_mock.assert_called_once_with(str(schema.id))

    def test_vanished_schema_kept_when_schedule_delete_fails(self) -> None:
        source = self._make_source()
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="orders",
            should_sync=True,
        )

        with mock.patch(f"{SERVICE}.delete_external_data_schedule", side_effect=Exception("temporal down")):
            _, deleted = sync_old_schemas_with_new_schemas({}, source_id=str(source.pk), team_id=self.team.pk)

        # The row must survive so the next discovery run retries the schedule delete —
        # soft-deleting now would orphan the live schedule forever.
        schema.refresh_from_db()
        assert schema.deleted is False
        assert deleted == []

    def test_vanished_schema_with_table_still_disabled_when_schedule_converge_fails(self) -> None:
        source = self._make_source()
        table = DataWarehouseTable.objects.create(
            name="postgres_orders",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="https://bucket/team_1/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="orders",
            should_sync=True,
            table=table,
        )

        with mock.patch(f"{SERVICE}.sync_schema_schedule_state", side_effect=Exception("temporal down")):
            sync_old_schemas_with_new_schemas({}, source_id=str(source.pk), team_id=self.team.pk)

        # The disable sticks and discovery survives — still-missing schemas are re-walked
        # every run, so the failed pause is retried on the next cycle.
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert schema.deleted is False
