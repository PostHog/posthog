import pytest
from unittest import mock

from django.apps import apps

from psycopg import sql as psql

from posthog.schema import HogQLQuery, HogQLVariable

from products.managed_warehouse.backend.client import (
    _SEARCH_PATH_SCHEMAS,
    compile_hogql_to_ducklake_sql,
    execute_ducklake_query,
)


@pytest.fixture(autouse=True)
def _cp_no_rows():
    # Compilation resolves managed table metadata through the typed team-state facade,
    # so pin both organization policies to keep these tests independent from the control plane.
    with (
        mock.patch(
            "products.managed_warehouse.backend.facade.team_state.data_imports_schema",
            side_effect=lambda team_id: f"posthog_data_imports_team_{team_id}",
        ),
        mock.patch(
            "products.managed_warehouse.backend.facade.team_state.data_imports_table_naming_version",
            return_value="copy_v1",
        ),
    ):
        yield


pytestmark = [pytest.mark.django_db]


class TestCompileHogQLToDuckLakeSQL:
    def test_substitutes_variable_placeholders(self):
        from posthog.models import Organization, Team

        variable_model = apps.get_model("product_analytics", "InsightVariable")

        org = Organization.objects.create(name="ducklake-vars")
        team = Team.objects.create(organization=org)
        variable = variable_model.objects.create(
            team=team, name="Event name", code_name="event_name", type="String", default_value="$pageview"
        )

        query = HogQLQuery(
            query="SELECT event FROM events WHERE event = {variables.event_name} LIMIT 10",
            variables={
                str(variable.id): HogQLVariable(variableId=str(variable.id), code_name="event_name", value="purchase")
            },
        )

        postgres_sql, values, _hogql_pretty = compile_hogql_to_ducklake_sql(team.pk, query)

        assert "purchase" in values.values()
        assert "variables" not in postgres_sql

    def test_person_id_compiles_to_physical_column(self):
        from posthog.models import Organization, Team

        org = Organization.objects.create(name="ducklake-person-id")
        team = Team.objects.create(organization=org)

        query = HogQLQuery(query="SELECT person_id FROM events LIMIT 10")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # DuckLake events ducklings have a physical person_id column and no override or
        # distinct-id tables, so the compile must not emit a person join.
        assert "person_id" in postgres_sql
        assert "person_distinct_id" not in postgres_sql


class TestDuckLakeModelRedirect:
    @staticmethod
    def _create_materialized_model(
        team, name: str = "vitally_org", query_sql: str = "SELECT org_id FROM vitally_source"
    ):
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        source_table = DataWarehouseTable.objects.create(
            name="vitally_source",
            team=team,
            columns={"org_id": "String"},
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/vitally/*.parquet",
            format="Parquet",
        )
        return DataWarehouseSavedQuery.objects.create(
            team=team,
            name=name,
            query={"query": query_sql},
            columns={"org_id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
            table=source_table,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

    @staticmethod
    def _create_completed_shadow_job(team, saved_query):
        from products.data_modeling.backend.facade.models import (
            DataModelingJob,
            DataModelingJobEngine,
            DataModelingJobStatus,
        )

        return DataModelingJob.objects.create(
            team=team,
            saved_query=saved_query,
            engine=DataModelingJobEngine.DUCKGRES,
            status=DataModelingJobStatus.COMPLETED,
        )

    def test_materialized_model_resolves_to_ducklake_table_not_s3(self):
        from posthog.models import Organization, Team

        org = Organization.objects.create(name="ducklake-redirect")
        team = Team.objects.create(organization=org)
        saved_query = self._create_materialized_model(team)
        self._create_completed_shadow_job(team, saved_query)

        query = HogQLQuery(query="SELECT org_id FROM vitally_org")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-materialized model, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in postgres_sql.lower()
        assert f"shadow_{team.pk}_models" in postgres_sql

    def test_model_without_completed_shadow_job_inlines_its_definition(self):
        from posthog.models import Organization, Team

        org = Organization.objects.create(name="ducklake-unshadowed")
        team = Team.objects.create(organization=org)
        self._create_materialized_model(team, query_sql="SELECT event AS org_id FROM events")

        query = HogQLQuery(query="SELECT org_id FROM vitally_org")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # No duckgres shadow run ever completed, so the DuckLake table does not exist.
        # Binding it anyway would fail at runtime with "Table ... does not exist";
        # the model's definition must be inlined as a subquery instead.
        assert f"shadow_{team.pk}_models" not in postgres_sql
        assert "FROM events" in postgres_sql

    def test_model_binding_matches_writer_name_sanitization(self):
        from posthog.models import Organization, Team

        from products.managed_warehouse.backend.common import duckgres_data_modeling_table_name

        org = Organization.objects.create(name="ducklake-long-name")
        team = Team.objects.create(organization=org)
        long_name = "a_really_long_model_name_that_exceeds_the_sixty_three_character_identifier_limit"
        saved_query = self._create_materialized_model(team, name=long_name)
        self._create_completed_shadow_job(team, saved_query)

        query = HogQLQuery(query=f"SELECT org_id FROM {long_name}")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # The writer truncates the DuckLake table name to 63 characters; binding the
        # raw normalized name would reference a table the writer never created.
        sanitized = duckgres_data_modeling_table_name(saved_query.normalized_name)
        assert sanitized != saved_query.normalized_name
        assert f"shadow_{team.pk}_models.{sanitized}" in postgres_sql
        assert f"shadow_{team.pk}_models.{saved_query.normalized_name}" not in postgres_sql

    def test_long_model_names_sharing_a_prefix_get_distinct_tables(self) -> None:
        from products.managed_warehouse.backend.common import (
            DUCKLAKE_IDENTIFIER_MAX_LENGTH,
            duckgres_data_modeling_table_name,
        )

        # Two models a user can both create, identical for the first 63 characters. Plain
        # truncation would point them at one table, so materializing either would replace
        # the other's rows.
        shared_prefix = "a" * DUCKLAKE_IDENTIFIER_MAX_LENGTH
        first = duckgres_data_modeling_table_name(f"{shared_prefix}_orders")
        second = duckgres_data_modeling_table_name(f"{shared_prefix}_refunds")

        assert first != second
        assert len(first) <= DUCKLAKE_IDENTIFIER_MAX_LENGTH
        assert len(second) <= DUCKLAKE_IDENTIFIER_MAX_LENGTH

    def test_source_table_resolves_to_ducklake_table_not_s3(self):
        from posthog.models import Organization, Team

        from products.managed_warehouse.backend.common import (
            duckgres_data_imports_schema,
            duckgres_data_imports_table_name,
        )
        from products.warehouse_sources.backend.facade.models import (
            DataWarehouseCredential,
            DataWarehouseTable,
            ExternalDataSchema,
            ExternalDataSource,
        )
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

        org = Organization.objects.create(name="ducklake-source-redirect")
        team = Team.objects.create(organization=org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="myprefix_",
        )
        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        warehouse_table = DataWarehouseTable.objects.create(
            name="myprefix_stripe_customers",
            format="Parquet",
            team=team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/stripe/customers/*.parquet",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            name="customers",
            source=source,
            table=warehouse_table,
            should_sync=True,
        )

        query = HogQLQuery(query="SELECT id FROM myprefix_stripe_customers")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-copied source table, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in postgres_sql.lower()
        assert duckgres_data_imports_schema(team.pk) in postgres_sql
        assert duckgres_data_imports_table_name(schema) in postgres_sql


class TestDuckLakeUnsupportedTables:
    def test_self_managed_s3_table_raises_typed_error(self):
        from posthog.hogql.errors import QueryError

        from posthog.models import Organization, Team

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-self-managed-s3")
        team = Team.objects.create(organization=org)
        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            name="self_managed_parquet",
            team=team,
            columns={"org_id": "String"},
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/data/*.parquet",
            format="Parquet",
        )

        # A self-managed S3 table is never copied into DuckLake; previously the compile
        # emitted a ClickHouse s3() call that duckgres rejected with a cryptic
        # "Table Function with name s3 does not exist" at runtime.
        query = HogQLQuery(query="SELECT org_id FROM self_managed_parquet")
        with pytest.raises(QueryError, match="self_managed_parquet"):
            compile_hogql_to_ducklake_sql(team.pk, query)


class TestDuckgresShadowCompilation:
    @mock.patch("products.managed_warehouse.backend.client.compile_hogql_to_ducklake_sql")
    def test_materialization_compile_bypasses_warehouse_access_control(self, mock_compile):
        from posthog.temporal.data_modeling.activities.materialize_view_duckgres import _compile_hogql_to_postgres_sql

        mock_compile.return_value = ("SELECT * FROM source", {}, "SELECT * FROM source")

        _compile_hogql_to_postgres_sql("SELECT * FROM source", 1)

        query = mock_compile.call_args.args[1]
        assert query.query == "SELECT * FROM source"
        kwargs = mock_compile.call_args.kwargs
        assert kwargs["bypass_warehouse_access_control"] is True
        # Userless shadow materialization: no actor is threaded through.
        assert kwargs.get("team") is None
        assert kwargs.get("user") is None


class TestExecuteDuckLakeQuery:
    def test_rejects_both_sql_and_query(self):
        with pytest.raises(ValueError, match="not both"):
            execute_ducklake_query(1, sql="SELECT 1", query=HogQLQuery(query="SELECT 1"))

    def test_rejects_neither_sql_nor_query(self):
        with pytest.raises(ValueError, match="either sql or query"):
            execute_ducklake_query(1)

    @mock.patch("products.managed_warehouse.backend.client.psycopg")
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True)
    def test_sql_path_executes_directly(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [
            mock.MagicMock(name="col1", type_code=25),
            mock.MagicMock(name="col2", type_code=20),
        ]
        mock_cursor.description[0].name = "event"
        mock_cursor.description[1].name = "count"
        mock_cursor.fetchall.return_value = [("$pageview", 42)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        result = execute_ducklake_query(1, sql="SELECT event, count(*) FROM events")

        assert result.columns == ["event", "count"]
        assert result.results == [["$pageview", 42]]
        assert result.sql == "SELECT event, count(*) FROM events"
        assert result.hogql is None

    @mock.patch("products.managed_warehouse.backend.client.psycopg")
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True)
    @mock.patch("products.managed_warehouse.backend.client.compile_hogql_to_ducklake_sql")
    def test_query_path_compiles_and_executes(self, mock_compile, _mock_dev_mode, mock_psycopg):
        mock_compile.return_value = ("SELECT count(*) FROM events", {}, "SELECT count() FROM events")
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [mock.MagicMock(name="cnt", type_code=20)]
        mock_cursor.description[0].name = "cnt"
        mock_cursor.fetchall.return_value = [(42,)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        query = HogQLQuery(query="SELECT count() FROM events")
        result = execute_ducklake_query(1, query=query)

        mock_compile.assert_called_once_with(1, query, team=None, user=None, bypass_warehouse_access_control=False)
        assert result.sql == "SELECT count(*) FROM events"
        assert result.hogql == "SELECT count() FROM events"
        assert result.results == [[42]]

    @mock.patch("products.managed_warehouse.backend.client.psycopg")
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True)
    def test_sets_search_path(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.description = []
        mock_cursor.fetchall.return_value = []
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        execute_ducklake_query(1, sql="SELECT 1")

        expected_sql = psql.SQL("SET search_path TO {}").format(psql.Literal(",".join(_SEARCH_PATH_SCHEMAS)))
        mock_conn.execute.assert_called_once_with(expected_sql)

    @mock.patch("products.managed_warehouse.backend.client.psycopg")
    @mock.patch("products.managed_warehouse.backend.client.get_duckgres_config_for_org")
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_production_path_resolves_org(self, _mock_dev_mode, mock_config_for_org, mock_psycopg):
        mock_config_for_org.return_value = {
            "DUCKGRES_HOST": "prod.duckgres.com",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "warehouse",
            "DUCKGRES_USERNAME": "root",
            "DUCKGRES_PASSWORD": "secret",
        }
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [mock.MagicMock(name="cnt", type_code=20)]
        mock_cursor.description[0].name = "cnt"
        mock_cursor.fetchall.return_value = [(1,)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        with mock.patch("products.managed_warehouse.backend.common._get_org_id_for_team", return_value="org-456"):
            result = execute_ducklake_query(1, sql="SELECT 1")

        mock_config_for_org.assert_called_once_with("org-456")
        assert result.results == [[1]]
