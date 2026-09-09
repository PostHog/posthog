from posthog.test.base import APIBaseTest

from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.database.database import Database

from products.endpoints.backend.logic.validation import DIRECT_CONNECTION_UNSUPPORTED, validate_hogql_query
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectConnectionValidation(APIBaseTest):
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

    def test_a_direct_connection_query_is_refused_by_name(self):
        source = self._dual_mode_source()

        with self.assertRaises(ValidationError) as ctx:
            validate_hogql_query(
                HogQLQuery(query="SELECT id FROM public.users", connectionId=str(source.id)),
                self.team,
                self.user,
            )

        detail = ctx.exception.detail
        assert isinstance(detail, dict)
        assert str(detail["query"]) == DIRECT_CONNECTION_UNSUPPORTED

    def test_the_synced_copy_of_the_same_table_still_validates(self):
        self._dual_mode_source()

        validate_hogql_query(HogQLQuery(query="SELECT id FROM postgres.pg.pg_users"), self.team, self.user)

    def test_creating_an_endpoint_over_a_direct_connection_is_refused(self):
        source = self._dual_mode_source()

        response = self.client.post(
            f"/api/environments/{self.team.id}/endpoints/",
            {
                "name": "direct_users",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT id FROM public.users",
                    "connectionId": str(source.id),
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == DIRECT_CONNECTION_UNSUPPORTED
