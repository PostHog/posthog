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

    def test_strict_match_creates_qualified_row_alongside_legacy_bare_row(self) -> None:
        # GitHub keeps its legacy repo's rows bare forever, so a second repo's qualified rows
        # coexist with them. Without strict matching, `acme/other.issues` tail-matches the bare
        # `issues` row and repo #2's rows are silently never created.
        source = self._make_source()
        legacy = self._make_synced_schema(source, "issues")

        created, _deleted = sync_old_schemas_with_new_schemas(
            {"issues": None, "acme/other.issues": "acme/other · issues"},
            source_id=str(source.pk),
            team_id=self.team.pk,
            strict_name_match=True,
            schema_metadata_by_name={
                "acme/other.issues": {"source_repository": "acme/other", "source_endpoint": "issues"}
            },
        )

        legacy.refresh_from_db()
        assert legacy.should_sync is True
        assert created == ["acme/other.issues"]
        new_row = ExternalDataSchema.objects.get(source_id=source.pk, name="acme/other.issues")
        assert new_row.sync_type_config.get("schema_metadata") == {
            "source_repository": "acme/other",
            "source_endpoint": "issues",
        }

    def test_strict_match_retires_removed_repo_rows(self) -> None:
        # Removing a repo drops its names from discovery: synced rows keep their table but stop
        # syncing; never-synced rows soft-delete. The legacy bare row must survive untouched.
        source = self._make_source()
        legacy = self._make_synced_schema(source, "issues")
        synced_removed = self._make_synced_schema(source, "acme/other.issues")
        unsynced_removed = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="acme/other.commits", should_sync=False
        )

        sync_old_schemas_with_new_schemas(
            {"issues": None},
            source_id=str(source.pk),
            team_id=self.team.pk,
            strict_name_match=True,
        )

        legacy.refresh_from_db()
        synced_removed.refresh_from_db()
        unsynced_removed.refresh_from_db()
        assert legacy.should_sync is True
        assert synced_removed.should_sync is False
        assert synced_removed.deleted is False
        assert unsynced_removed.deleted is True
