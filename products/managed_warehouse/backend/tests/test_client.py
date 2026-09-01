import pytest
from unittest import mock

from django.apps import apps

from parameterized import parameterized
from psycopg import sql as psql

from posthog.schema import HogQLQuery, HogQLVariable

from products.managed_warehouse.backend.client import (
    _SEARCH_PATH_SCHEMAS,
    _configure_s3_secrets,
    _s3_secrets_for_database,
    compile_hogql_to_ducklake_sql,
    execute_ducklake_create_table,
    execute_ducklake_query,
    make_duckgres_conninfo,
)
from products.managed_warehouse.backend.facade.contracts import DuckLakeCompiledQuery


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

        compiled = compile_hogql_to_ducklake_sql(team.pk, query)

        assert "purchase" in compiled.values.values()
        assert "variables" not in compiled.sql


class TestDuckLakeModelRedirect:
    def test_materialized_model_resolves_to_ducklake_table_not_s3(self):
        from posthog.models import Organization, Team

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-redirect")
        team = Team.objects.create(organization=org)
        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        source_table = DataWarehouseTable.objects.create(
            name="vitally_source",
            team=team,
            columns={"org_id": "String"},
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/vitally/*.parquet",
            format="Parquet",
        )
        DataWarehouseSavedQuery.objects.create(
            team=team,
            name="vitally_org",
            query={"query": "SELECT org_id FROM vitally_source"},
            columns={"org_id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
            table=source_table,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

        query = HogQLQuery(query="SELECT org_id FROM vitally_org")
        compiled = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-materialized model, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in compiled.sql.lower()
        assert f"shadow_{team.pk}_models" in compiled.sql

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
        compiled = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-copied source table, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in compiled.sql.lower()
        assert duckgres_data_imports_schema(team.pk) in compiled.sql
        assert duckgres_data_imports_table_name(schema) in compiled.sql

    def test_self_managed_parquet_resolves_to_native_reader(self) -> None:
        from posthog.models import Organization, Team

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-self-managed")
        team = Team.objects.create(organization=org)
        credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key="access-key",
            access_secret="access-secret",
        )
        DataWarehouseTable.objects.create(
            name="self_managed_orders",
            format="Parquet",
            team=team,
            credential=credential,
            url_pattern="https://my-bucket.s3.amazonaws.com/data/*.parquet",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        compiled = compile_hogql_to_ducklake_sql(
            team.pk,
            HogQLQuery(query="SELECT id FROM self_managed_orders"),
        )

        assert "s3(" not in compiled.sql.lower()
        assert "read_parquet(" in compiled.sql.lower()
        assert "s3://my-bucket/data/*.parquet" in compiled.values.values()
        assert "access-key" not in compiled.sql
        assert "access-secret" not in compiled.sql
        assert "access-key" not in compiled.values.values()
        assert "access-secret" not in compiled.values.values()


class TestSelfManagedS3Secrets:
    def test_credentials_are_bound_to_a_path_scoped_secret(self) -> None:
        from posthog.models import Organization, Team

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-self-managed-secret")
        team = Team.objects.create(organization=org)
        credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key="access-key",
            access_secret="access-secret",
        )
        table = DataWarehouseTable.objects.create(
            name="self_managed_orders",
            format="Parquet",
            team=team,
            credential=credential,
            url_pattern="http://objectstorage:19000/my-bucket/data/*.parquet",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True}},
        )
        cursor = mock.MagicMock()
        connection = mock.MagicMock()
        connection.cursor.return_value.__enter__ = mock.Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = mock.Mock(return_value=False)

        compiled = compile_hogql_to_ducklake_sql(team.pk, HogQLQuery(query="SELECT id FROM self_managed_orders"))
        _configure_s3_secrets(connection, compiled.s3_secrets)

        statement, values = cursor.execute.call_args.args
        rendered_statement = statement.as_string()
        assert rendered_statement.startswith(f'CREATE OR REPLACE TEMPORARY SECRET "self_managed_{table.id.hex}"')
        assert "KEY_ID %s" in rendered_statement
        assert "SECRET %s" in rendered_statement
        assert "SCOPE %s" in rendered_statement
        assert "access-key" not in rendered_statement
        assert "access-secret" not in rendered_statement
        assert values == [
            "access-key",
            "access-secret",
            "us-east-1",
            "objectstorage:19000",
            False,
            "path",
            "s3://my-bucket/data/",
        ]

    def test_a_table_access_control_removed_gets_no_secret(self) -> None:
        from posthog.hogql.database.database import Database

        from posthog.models import Organization, Team

        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-self-managed-restricted")
        team = Team.objects.create(organization=org)
        columns = {"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True}}
        allowed_credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key="allowed-key",
            access_secret="allowed-secret",
        )
        restricted_credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key="restricted-key",
            access_secret="restricted-secret",
        )
        allowed = DataWarehouseTable.objects.create(
            name="allowed_orders",
            format="Parquet",
            team=team,
            credential=allowed_credential,
            url_pattern="https://my-bucket.s3.amazonaws.com/data/*.parquet",
            columns=columns,
        )
        DataWarehouseTable.objects.create(
            name="restricted_orders",
            format="Parquet",
            team=team,
            credential=restricted_credential,
            url_pattern="https://my-bucket.s3.amazonaws.com/data/*.parquet",
            columns=columns,
        )

        database = Database.create_for(team.pk)
        # Access control prunes the schema through this same entry point.
        database.prune_to_table_names({"allowed_orders"})

        secrets = _s3_secrets_for_database(database)

        assert [secret.name for secret in secrets] == [f"self_managed_{allowed.id.hex}"]
        assert [secret.key_id for secret in secrets] == ["allowed-key"]


class TestDuckgresShadowCompilation:
    @mock.patch("products.managed_warehouse.backend.client.compile_hogql_to_ducklake_sql")
    def test_materialization_compile_bypasses_warehouse_access_control(self, mock_compile):
        from posthog.temporal.data_modeling.activities.materialize_view_duckgres import _compile_hogql_for_ducklake

        mock_compile.return_value = DuckLakeCompiledQuery(
            sql="SELECT * FROM source", values={}, hogql="SELECT * FROM source"
        )

        _compile_hogql_for_ducklake("SELECT * FROM source", 1)

        query = mock_compile.call_args.args[1]
        assert query.query == "SELECT * FROM source"
        kwargs = mock_compile.call_args.kwargs
        assert kwargs["bypass_warehouse_access_control"] is True
        # Userless shadow materialization: no actor is threaded through.
        assert kwargs.get("team") is None
        assert kwargs.get("user") is None


class TestMakeDuckgresConninfoApplicationName:
    @parameterized.expand(
        [
            ("default", {}, "posthog"),
            ("explicit_override", {"application_name": "ducklake-register"}, "ducklake-register"),
        ]
    )
    def test_application_name_on_org_root_path(self, _name, kwargs, expected):
        with mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True):
            conninfo = make_duckgres_conninfo(1, **kwargs)

        assert f"application_name={expected}" in conninfo


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
        mock_compile.return_value = DuckLakeCompiledQuery(
            sql="SELECT count(*) FROM events", values={}, hogql="SELECT count() FROM events"
        )
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
        # Lets duckgres analytics tell this shadow-query caller apart from the
        # materialization path and from customer connections.
        conninfo = mock_psycopg.connect.call_args.args[0]
        assert "application_name=endpoints-shadow" in conninfo


class TestExecuteDuckLakeCreateTable:
    @mock.patch("products.managed_warehouse.backend.client.psycopg")
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True)
    def test_uses_materialization_application_name(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        execute_ducklake_create_table(1, "SELECT 1", "shadow", "model")

        conninfo = mock_psycopg.connect.call_args_list[0].args[0]
        assert "application_name=materialization" in conninfo
