import uuid

from posthog.test.base import BaseTest

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
