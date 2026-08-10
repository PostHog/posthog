from posthog.test.base import BaseTest

from posthog.schema import HogQLQuery

from posthog.hogql.database.database import Database

from products.endpoints.backend.logic.validation import validate_hogql_query
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectConnectionValidation(BaseTest):
    def _dual_mode_source(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="synced_pg_source",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            direct_query_enabled=True,
            prefix="pg",
            job_inputs={"schema": "public"},
        )
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        synced_table = DataWarehouseTable.objects.create(
            name="pg_users",
            format="Parquet",
            team=self.team,
            credential=credential,
            external_data_source=source,
            url_pattern="s3://bucket/users/*",
            columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name="public.users",
            source=source,
            table=synced_table,
            should_sync=True,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "source_schema": "public",
                    "source_table_name": "users",
                }
            },
        )
        return source

    def test_connection_selection_renames_the_same_table(self):
        source = self._dual_mode_source()

        with_connection = Database._build_from_sources(
            Database._fetch_sources(team=self.team, connection_id=str(source.id))
        )
        without_connection = Database._build_from_sources(Database._fetch_sources(team=self.team))

        assert with_connection.has_table("public.users")
        assert not with_connection.has_table("postgres.pg.pg_users")

        assert without_connection.has_table("postgres.pg.pg_users")
        assert not without_connection.has_table("public.users")

    def test_endpoint_validation_accepts_a_query_the_editor_resolves(self):
        self._dual_mode_source()

        # The editor resolves this against the selected connection; endpoint creation must too.
        validate_hogql_query(HogQLQuery(query="SELECT id FROM public.users"), self.team, self.user)
