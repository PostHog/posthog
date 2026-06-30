from posthog.test.base import BaseTest

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import get_view_or_table_by_name
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGetViewOrTableByName(BaseTest):
    def _create_warehouse_table(self, *, name, url_pattern, source=None, credential=None) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=credential,
            url_pattern=url_pattern,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def test_ignores_tables_of_deleted_sources(self):
        # A table orphaned by a soft-deleted source must not shadow the live table re-created under
        # the same name — this is the path that feeds joins and series table resolution.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")

        deleted_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="old",
            connection_id="old",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://orphan/*", source=deleted_source, credential=credential
        )
        deleted_source.deleted = True
        deleted_source.save()

        live_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="new",
            connection_id="new",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        live_table = self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://live/*", source=live_source, credential=credential
        )

        resolved = get_view_or_table_by_name(self.team, "pull_requests")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == live_table.pk
        assert resolved.url_pattern == "s3://live/*"

    def test_keeps_self_managed_table_without_source(self):
        # Guards the deleted-source exclusion against the Django exclude()-with-NULL gotcha:
        # a self-managed table (no source) must still resolve.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        table = self._create_warehouse_table(name="self_managed", url_pattern="s3://self/*", credential=credential)

        resolved = get_view_or_table_by_name(self.team, "self_managed")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == table.pk

    def test_resolves_duplicate_live_table_names_to_newest(self):
        # Two live tables share a name (e.g. a re-sync produced a duplicate): newest wins.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        older = self._create_warehouse_table(name="pull_requests", url_pattern="s3://older/*", credential=credential)
        newer = self._create_warehouse_table(name="pull_requests", url_pattern="s3://newer/*", credential=credential)

        # Pin created_at explicitly (bypasses auto_now_add) so the tiebreak is deterministic.
        DataWarehouseTable.objects.filter(pk=older.pk).update(created_at="2024-01-01T00:00:00+00:00")
        DataWarehouseTable.objects.filter(pk=newer.pk).update(created_at="2024-06-01T00:00:00+00:00")

        resolved = get_view_or_table_by_name(self.team, "pull_requests")

        assert isinstance(resolved, DataWarehouseTable)
        assert resolved.pk == newer.pk
        assert resolved.url_pattern == "s3://newer/*"
