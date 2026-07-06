import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql import (
    MSSQLColumn,
    MSSQLImplementation,
    _filter_qualified_tables,
    _non_system_schema_clause,
)


def _make_config(**overrides) -> MSSQLSourceConfig:
    defaults: dict = {
        "host": "localhost",
        "port": 1433,
        "database": "warehouse",
        "user": "u",
        "password": "p",
        "schema": "dbo",
    }
    defaults.update(overrides)
    return MSSQLSourceConfig.from_dict(defaults)


def _make_inputs(schema_name: str = "messages", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


def _conn_with_rows(rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
    """A mock connection whose single cursor yields `rows` for both iteration and fetchall."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__iter__.return_value = iter(rows)
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


@pytest.fixture
def impl() -> MSSQLImplementation:
    return MSSQLImplementation()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestNonSystemSchemaClause:
    def test_excludes_system_schemas_and_db_roles(self):
        clause, params = _non_system_schema_clause("table_schema")
        assert "table_schema NOT IN" in clause
        # `db[_]%%` brackets the underscore (literal match) and doubles the `%` for pyformat.
        assert "table_schema NOT LIKE 'db[_]%%'" in clause
        assert set(params.values()) == {"sys", "guest", "INFORMATION_SCHEMA"}


class TestFilterQualifiedTables:
    def test_matches_qualified_name_directly(self):
        all_tables = {"dbo.users": [("id", "int", False)], "sales.users": [("uid", "int", False)]}
        assert _filter_qualified_tables(all_tables, ["dbo.users"]) == {"dbo.users": [("id", "int", False)]}

    def test_legacy_bare_name_matches_every_namespace(self):
        all_tables = {"dbo.users": [("id", "int", False)], "sales.users": [("uid", "int", False)]}
        assert set(_filter_qualified_tables(all_tables, ["users"]).keys()) == {"dbo.users", "sales.users"}

    def test_unknown_name_dropped(self):
        all_tables = {"dbo.users": [("id", "int", False)]}
        assert _filter_qualified_tables(all_tables, ["dbo.missing"]) == {}


# ---------------------------------------------------------------------------
# Discovery — blank namespace vs single-namespace fast path
# ---------------------------------------------------------------------------


class TestGetColumns:
    def test_multi_schema_qualifies_and_keeps_duplicates_distinct(self, impl):
        rows = [
            ("dbo", "users", "id", "int", "NO"),
            ("dbo", "users", "email", "varchar", "YES"),
            ("sales", "users", "id", "bigint", "NO"),
        ]
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_columns(conn, _make_config(schema=""), None)
        assert set(result.keys()) == {"dbo.users", "sales.users"}
        assert result["dbo.users"] == [("id", "int", False), ("email", "varchar", True)]
        assert result["sales.users"] == [("id", "bigint", False)]
        sql, params = cursor.execute.call_args.args
        assert "table_schema NOT LIKE 'db[_]%%'" in sql
        assert set(params.values()) == {"sys", "guest", "INFORMATION_SCHEMA"}

    def test_single_schema_keeps_bare_names(self, impl):
        rows = [("dbo", "users", "id", "int", "NO")]
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_columns(conn, _make_config(schema="dbo"), None)
        assert set(result.keys()) == {"users"}
        sql, params = cursor.execute.call_args.args
        assert "table_schema = %(schema)s" in sql
        assert params["schema"] == "dbo"

    def test_single_schema_pushes_names_filter(self, impl):
        rows = [("dbo", "users", "id", "int", "NO")]
        conn, cursor = _conn_with_rows(rows)
        impl.get_columns(conn, _make_config(schema="dbo"), ["users"])
        sql, params = cursor.execute.call_args.args
        assert "table_name IN %(names)s" in sql
        assert params["names"] == ("users",)

    def test_multi_schema_filters_qualified_names_in_python(self, impl):
        rows = [
            ("dbo", "users", "id", "int", "NO"),
            ("sales", "users", "uid", "int", "NO"),
        ]
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_columns(conn, _make_config(schema=""), ["sales.users"])
        assert set(result.keys()) == {"sales.users"}
        # Names aren't pushed into SQL in multi-schema mode (they arrive qualified).
        sql, _params = cursor.execute.call_args.args
        assert "table_name IN" not in sql


class TestGetSourceMetadata:
    @pytest.mark.parametrize(
        "schema,tables,expected_schema,expected_table",
        [
            (
                "",
                ["dbo.users", "sales.orders"],
                {"dbo.users": "dbo", "sales.orders": "sales"},
                {"dbo.users": "users", "sales.orders": "orders"},
            ),
            ("dbo", ["users"], {"users": "dbo"}, {"users": "users"}),
        ],
    )
    def test_splits_namespace(self, impl, schema, tables, expected_schema, expected_table):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema=schema), tables)
        assert meta.schema_by_table == expected_schema
        assert meta.table_name_by_table == expected_table
        assert meta.catalog_by_table == dict.fromkeys(tables, "warehouse")


class TestGetPrimaryKeys:
    def test_multi_schema_keys_by_qualified_name(self, impl):
        rows = [("dbo", "users", "id"), ("sales", "users", "uid")]
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_primary_keys(conn, _make_config(schema=""), ["dbo.users", "sales.users"])
        assert result == {"dbo.users": ["id"], "sales.users": ["uid"]}
        sql, params = cursor.execute.call_args.args
        assert "db[_]" in sql
        # Scan is bounded server-side by the unqualified table names.
        assert "t.name IN %(names)s" in sql
        assert params["names"] == ("users",)

    def test_single_schema_keys_by_bare_name(self, impl):
        rows = [("dbo", "users", "id"), ("dbo", "users", "email")]
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_primary_keys(conn, _make_config(schema="dbo"), ["users"])
        assert result == {"users": ["id", "email"]}
        sql, params = cursor.execute.call_args.args
        assert "s.name = %(schema)s" in sql
        assert params["schema"] == "dbo"


class TestGetLeadingIndexColumns:
    @pytest.mark.parametrize(
        "schema,tables,rows,expected",
        [
            (
                "",
                ["dbo.users", "sales.orders"],
                [("dbo", "users", "created_at"), ("sales", "orders", "ts")],
                {"dbo.users": {"created_at"}, "sales.orders": {"ts"}},
            ),
            ("dbo", ["users"], [("dbo", "users", "created_at")], {"users": {"created_at"}}),
        ],
    )
    def test_keys_by_namespace(self, impl, schema, tables, rows, expected):
        conn, cursor = _conn_with_rows(rows)
        result = impl.get_leading_index_columns(conn, _make_config(schema=schema), tables)
        assert result == expected
        sql, _params = cursor.execute.call_args.args
        assert "t.name IN %(names)s" in sql


# ---------------------------------------------------------------------------
# Per-row routing in build_pipeline
# ---------------------------------------------------------------------------


@pytest.fixture
def routing_mocks(mocker):
    """Capture the (schema, table) the streaming-metadata methods receive, mocking the connection."""
    captured: dict[str, tuple[str, str]] = {}

    def fake_metadata(self, cursor, schema, table_name):
        captured["metadata"] = (schema, table_name)
        return Table(
            name=table_name,
            parents=(schema,),
            columns=[MSSQLColumn(name="id", data_type="int", nullable=False)],
        )

    def fake_pks(self, cursor, schema, table_name):
        captured["pks"] = (schema, table_name)
        return ["id"]

    mocker.patch.object(MSSQLImplementation, "get_table_metadata", fake_metadata)
    mocker.patch.object(MSSQLImplementation, "get_primary_keys_for_table", fake_pks)
    mocker.patch.object(MSSQLImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(MSSQLImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(MSSQLImplementation, "get_partition_settings", return_value=None)

    streaming_cursor = MagicMock()
    streaming_cursor.__enter__.return_value = streaming_cursor
    streaming_cursor.description = [("id",)]
    streaming_cursor.fetchmany.return_value = []

    metadata_cursor = MagicMock()
    metadata_cursor.__enter__.return_value = metadata_cursor

    state = {"metadata_done": False}

    def cursor_factory(*args, **kwargs):
        if not state["metadata_done"]:
            state["metadata_done"] = True
            return metadata_cursor
        return streaming_cursor

    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.cursor.side_effect = cursor_factory

    mocker.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.pymssql.connect",
        return_value=mock_connection,
    )
    return captured


class TestBuildPipelineRouting:
    def test_routes_per_row_namespace_from_metadata(self, routing_mocks):
        inputs = _make_inputs(
            schema_name="analytics.users",
            schema_metadata={"source_schema": "analytics", "source_table_name": "users"},
        )
        response = MSSQLImplementation().build_pipeline(_make_config(schema=""), inputs)
        assert routing_mocks["metadata"] == ("analytics", "users")
        assert routing_mocks["pks"] == ("analytics", "users")
        # S3 subdir is the single-underscore normalization of the dotted display name.
        assert response.name == "analytics_users"

    def test_self_heals_dotted_name_without_metadata(self, routing_mocks):
        inputs = _make_inputs(schema_name="analytics.users")
        MSSQLImplementation().build_pipeline(_make_config(schema=""), inputs)
        assert routing_mocks["metadata"] == ("analytics", "users")

    def test_preserves_legacy_storage_key(self, routing_mocks):
        # A migrated single-schema row keeps its old Delta subdir via s3_folder_name.
        inputs = _make_inputs(
            schema_name="analytics.users",
            schema_metadata={"source_schema": "analytics", "source_table_name": "users"},
            s3_folder_name="users",
        )
        response = MSSQLImplementation().build_pipeline(_make_config(schema=""), inputs)
        assert response.name == "users"

    def test_legacy_single_schema_fallback(self, routing_mocks):
        inputs = _make_inputs(schema_name="messages")
        response = MSSQLImplementation().build_pipeline(_make_config(schema="dbo"), inputs)
        assert routing_mocks["metadata"] == ("dbo", "messages")
        assert response.name == "messages"

    def test_raises_when_namespace_indeterminate(self, routing_mocks):
        # Blank config schema, no metadata, bare name — nothing resolves a namespace, so the
        # row is broken: fail loudly rather than guess.
        inputs = _make_inputs(schema_name="messages")
        with pytest.raises(ValueError, match="Schema is missing"):
            MSSQLImplementation().build_pipeline(_make_config(schema=""), inputs)
