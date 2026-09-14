import os

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
    MotherduckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    DEFAULT_MOTHERDUCK_FETCH_SIZE,
    DUCKDB_LOCAL_CONFIG,
    MOTHERDUCK_SYSTEM_DATABASES,
    MotherDuckImplementation,
    build_motherduck_connection_string,
    connect,
    filter_motherduck_incremental_fields,
    translate_motherduck_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.source import MotherduckSource
from products.warehouse_sources.backend.types import IncrementalFieldType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck"
_CONNECT_PATH = f"{_MODULE}.duckdb.connect"


def _make_config(**overrides) -> MotherduckSourceConfig:
    defaults: dict = {"access_token": "md-token", "database": "my_db", "schema": "analytics"}
    defaults.update(overrides)
    return MotherduckSourceConfig.from_dict(defaults)


def _make_inputs(schema_name: str = "users", **overrides) -> SourceInputs:
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


def _conn() -> MagicMock:
    """A DuckDB-shaped connection: `execute()` returns the connection itself."""
    conn = MagicMock()
    conn.execute.return_value = conn
    conn.fetchall.return_value = []
    conn.fetchone.return_value = None
    return conn


@pytest.fixture
def impl() -> MotherDuckImplementation:
    return MotherDuckImplementation()


class TestMotherDuck:
    # ------------------------------------------------------------------
    # Connection string
    # ------------------------------------------------------------------

    def test_connection_string_url_encodes_the_token(self):
        assert (
            build_motherduck_connection_string(" my_db ", "to ken/+=")
            == "md:my_db?motherduck_token=to+ken%2F%2B%3D&saas_mode=true"
        )

    @pytest.mark.parametrize("database", ["", "   ", None])
    def test_connection_string_without_a_database_is_account_wide(self, database):
        # A blank database attaches every database the token can see, rather than failing.
        assert (
            build_motherduck_connection_string(database, "md-token") == "md:?motherduck_token=md-token&saas_mode=true"
        )

    def test_connection_string_pins_saas_mode(self):
        # DuckDB runs in-process here, so the DSN must deny local file access and extension installs.
        assert "saas_mode=true" in build_motherduck_connection_string("my_db", "md-token")

    @pytest.mark.parametrize(
        "database",
        [
            # Anything that could append its own connection parameters or split the DSN.
            "my_db?motherduck_token=attacker",
            "my_db&motherduck_token=attacker",
            "my db",
            "my_db#frag",
            "my/db",
        ],
    )
    def test_connection_string_rejects_unsafe_database_names(self, database):
        with pytest.raises(ValueError):
            build_motherduck_connection_string(database, "md-token")

    def test_connection_string_requires_a_token(self):
        with pytest.raises(ValueError):
            build_motherduck_connection_string("my_db", "")

    @pytest.mark.parametrize(
        "raw,expected_fragment",
        [
            ("UNAUTHENTICATED: jwt expired", "Invalid MotherDuck token"),
            (
                "Error: You've reached the daily compute limit for this plan. Upgrade to get more capacity.",
                "reached its compute limit",
            ),
            ("Catalog Error: Table with name nope does not exist", "Can't find that database or schema"),
            # Unmapped errors surface their first line only (DuckDB appends candidate/hint blocks).
            ("Parser Error: syntax error at or near\nCandidate bindings: ...", "Parser Error: syntax error at or near"),
        ],
    )
    def test_translate_error_maps_driver_failures_to_user_messages(self, raw, expected_fragment):
        assert expected_fragment in translate_motherduck_error(Exception(raw))

    # ------------------------------------------------------------------
    # Incremental field types
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "data_type,expected",
        [
            ("TIMESTAMP", IncrementalFieldType.Timestamp),
            ("TIMESTAMP WITH TIME ZONE", IncrementalFieldType.Timestamp),
            ("TIMESTAMP_NS", IncrementalFieldType.Timestamp),
            ("DATE", IncrementalFieldType.Date),
            ("BIGINT", IncrementalFieldType.Numeric),
            ("INTEGER", IncrementalFieldType.Numeric),
            ("HUGEINT", IncrementalFieldType.Numeric),
            ("UBIGINT", IncrementalFieldType.Numeric),
            # DuckDB reports the parameterized form, so an equality match would drop these.
            ("DECIMAL(18,3)", IncrementalFieldType.Numeric),
        ],
    )
    def test_incremental_filter_picks_up_supported_types(self, data_type, expected):
        assert filter_motherduck_incremental_fields([("c", data_type, True)]) == [("c", expected, True)]

    @pytest.mark.parametrize("data_type", ["VARCHAR", "BOOLEAN", "DOUBLE", "FLOAT", "BLOB", "JSON", "INTEGER[]"])
    def test_incremental_filter_drops_unsupported_types(self, data_type):
        # Floats are deliberately excluded — an imprecise cursor skips or re-reads rows at the boundary.
        assert filter_motherduck_incremental_fields([("c", data_type, True)]) == []

    # ------------------------------------------------------------------
    # connect()
    # ------------------------------------------------------------------

    def test_connect_bounds_duckdb_resources_and_passes_the_dsn(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config()):
                pass
        assert mock_connect.call_args.args[0] == "md:my_db?motherduck_token=md-token&saas_mode=true"
        # DuckDB shares this process, so it must not size itself against the whole host.
        assert mock_connect.call_args.kwargs["config"] == DUCKDB_LOCAL_CONFIG
        # Neither imports nor direct queries write, so writes are refused engine-side.
        assert mock_connect.call_args.kwargs["read_only"] is True

    def test_connect_pins_the_catalog_when_given_one(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config(database=None), catalog="other_db"):
                pass
        # `USE` lets every catalog-scoped discovery query stay written against current_database().
        mock_connect.return_value.execute.assert_called_once_with('USE "other_db"')

    def test_connect_without_a_catalog_does_not_switch_database(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config()):
                pass
        mock_connect.return_value.execute.assert_not_called()

    def test_config_redirects_extension_storage_off_the_home_directory(self):
        # `home_directory` alone leaves extension storage at `~/.duckdb`, so it needs its own key.
        assert DUCKDB_LOCAL_CONFIG["extension_directory"] != DUCKDB_LOCAL_CONFIG["home_directory"]
        assert DUCKDB_LOCAL_CONFIG["extension_directory"].startswith(DUCKDB_LOCAL_CONFIG["home_directory"])

    def test_connect_creates_the_configured_extension_store(self, tmp_path):
        # Regression: extension autoload creates `~/.duckdb` on connect, which raised
        # `Failed to create directory "/root/.duckdb": Permission denied` in a locked-down worker.
        # connect() must create the store it configures, so driving it against a fresh base (rather
        # than pre-making the directories) is what catches a dropped or reordered makedirs.
        base = tmp_path / "duckdb-home"
        config = {
            **DUCKDB_LOCAL_CONFIG,
            "home_directory": str(base),
            "extension_directory": str(base / "extensions"),
        }
        with patch(f"{_MODULE}.DUCKDB_LOCAL_CONFIG", config), patch(_CONNECT_PATH) as mock_connect:
            assert not base.exists()
            connect("md-token", "my_db")
        assert os.path.isdir(config["extension_directory"])
        assert os.access(config["extension_directory"], os.W_OK)
        assert mock_connect.call_args.kwargs["config"]["extension_directory"] == config["extension_directory"]

    def test_connect_closes_on_exit(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config()):
                mock_connect.return_value.close.assert_not_called()
            mock_connect.return_value.close.assert_called_once()

    def test_connect_closes_on_error(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with pytest.raises(RuntimeError):
                with impl.connect(_make_config()):
                    raise RuntimeError("boom")
            mock_connect.return_value.close.assert_called_once()

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def test_get_columns_groups_columns_by_table(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [
            ("my_db", "analytics", "users", "id", "BIGINT", "NO"),
            ("my_db", "analytics", "users", "email", "VARCHAR", "YES"),
            ("my_db", "analytics", "orders", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(conn, _make_config(), names=None)
        # Single-schema source keeps bare table names.
        assert set(result.keys()) == {"users", "orders"}
        assert result["users"] == [("id", "BIGINT", False), ("email", "VARCHAR", True)]

    def test_get_columns_scopes_to_the_configured_schema(self, impl):
        conn = _conn()
        impl.get_columns(conn, _make_config(schema="sales"), names=None)
        sql, params = conn.execute.call_args.args
        assert "table_schema = ?" in sql
        # The client also holds `memory`, `system` and `temp` catalogs that are not customer data.
        assert "table_catalog = current_database()" in sql
        assert params == ["sales"]

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_get_columns_blank_schema_discovers_all_namespaces_qualified(self, impl, blank):
        conn = _conn()
        conn.fetchall.return_value = [
            ("my_db", "analytics", "users", "id", "BIGINT", "NO"),
            ("my_db", "sales", "users", "id", "BIGINT", "NO"),
            ("my_db", "sales", "orders", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(conn, _make_config(schema=blank), names=None)
        # Same table name in two schemas must stay distinct and qualified.
        assert set(result.keys()) == {"analytics.users", "sales.users", "sales.orders"}
        sql, params = conn.execute.call_args.args
        assert "table_schema NOT IN (?, ?)" in sql
        assert params == ["information_schema", "pg_catalog"]

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_get_columns_blank_database_spans_catalogs_fully_qualified(self, impl, blank):
        conn = _conn()
        conn.fetchall.return_value = [
            ("warehouse", "sales", "users", "id", "BIGINT", "NO"),
            ("staging", "sales", "users", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(conn, _make_config(database=blank, schema=""), names=None)
        # Same schema and table in two catalogs must stay distinct.
        assert set(result.keys()) == {"warehouse.sales.users", "staging.sales.users"}

    def test_get_columns_blank_database_excludes_bookkeeping_catalogs(self, impl):
        # MotherDuck and the client attach `system`, `temp` and friends — never customer data.
        conn = _conn()
        impl.get_columns(conn, _make_config(database="", schema=""), names=None)
        sql, params = conn.execute.call_args.args
        assert "c.table_catalog NOT IN (" in sql
        assert params[: len(MOTHERDUCK_SYSTEM_DATABASES)] == list(MOTHERDUCK_SYSTEM_DATABASES)

    def test_get_columns_excludes_views(self, impl):
        # A view's definition runs inside this worker at query time — e.g. over a locally-executed
        # DuckDB table function reading the filesystem — so only `BASE TABLE` entries are ever
        # offered for discovery/sync.
        conn = _conn()
        impl.get_columns(conn, _make_config(), names=None)
        sql = conn.execute.call_args.args[0]
        assert "t.table_type = 'BASE TABLE'" in sql

    def test_get_columns_filters_by_names(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [
            ("my_db", "analytics", "users", "id", "BIGINT", "NO"),
            ("my_db", "analytics", "orders", "id", "BIGINT", "NO"),
        ]
        assert list(impl.get_columns(conn, _make_config(), names=["users"]).keys()) == ["users"]

    def test_get_columns_qualified_name_falls_back_to_bare_discovery_key(self, impl):
        # Mid-migration a row may be requested qualified while a configured-schema source still
        # discovers it bare — keep the requested (qualified) key, mapped to the bare columns.
        conn = _conn()
        conn.fetchall.return_value = [("my_db", "analytics", "users", "id", "BIGINT", "NO")]
        result = impl.get_columns(conn, _make_config(schema="analytics"), names=["analytics.users"])
        assert result == {"analytics.users": [("id", "BIGINT", False)]}

    def test_get_primary_keys_returns_constraint_columns_in_order(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [("my_db", "analytics", "users", ["id", "tenant_id"])]
        out = impl.get_primary_keys(conn, _make_config(), tables=["users", "orders"])
        assert out == {"users": ["id", "tenant_id"], "orders": None}
        # One batched catalog query, not one per table.
        assert conn.execute.call_count == 1

    def test_get_primary_keys_routes_to_qualified_display_names(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [
            ("my_db", "analytics", "users", ["id"]),
            ("my_db", "sales", "users", ["uuid"]),
        ]
        out = impl.get_primary_keys(conn, _make_config(schema=""), tables=["analytics.users", "sales.users"])
        assert out == {"analytics.users": ["id"], "sales.users": ["uuid"]}

    def test_get_primary_keys_swallows_failure(self, impl):
        # Discovery must keep working without keys — the base falls back to an `id` column.
        conn = _conn()
        conn.execute.side_effect = Exception("Catalog Error: duckdb_constraints does not exist")
        assert impl.get_primary_keys(conn, _make_config(), tables=["users"]) == {"users": None}

    def test_get_row_counts_reads_catalog_estimates(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [
            ("my_db", "analytics", "users", 1_200),
            ("my_db", "analytics", "orders", None),
            ("my_db", "analytics", "unrequested", 5),
        ]
        out = impl.get_row_counts(conn, _make_config(), tables=["users", "orders"])
        assert out == {"users": 1_200, "orders": None}

    def test_get_row_counts_swallows_failure(self, impl):
        conn = _conn()
        conn.execute.side_effect = Exception("Catalog Error: duckdb_tables does not exist")
        assert impl.get_row_counts(conn, _make_config(), tables=["users"]) == {"users": None}

    def test_get_source_metadata_single_schema_pins_configured_namespace(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema="analytics"), tables=["users"])
        assert meta.catalog_by_table == {"users": "my_db"}
        assert meta.schema_by_table == {"users": "analytics"}
        assert meta.table_name_by_table == {"users": "users"}

    def test_get_source_metadata_multi_schema_splits_qualified_names(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema=""), tables=["analytics.users", "sales.users"])
        assert meta.schema_by_table == {"analytics.users": "analytics", "sales.users": "sales"}
        assert meta.table_name_by_table == {"analytics.users": "users", "sales.users": "users"}

    def test_get_source_metadata_account_wide_stamps_each_rows_catalog(self, impl):
        # Without a per-row catalog the pipeline could not tell which database to `USE`.
        meta = impl.get_source_metadata(
            MagicMock(),
            _make_config(database="", schema=""),
            tables=["warehouse.sales.users", "staging.sales.users"],
        )
        assert meta.catalog_by_table == {"warehouse.sales.users": "warehouse", "staging.sales.users": "staging"}
        assert meta.schema_by_table == {"warehouse.sales.users": "sales", "staging.sales.users": "sales"}
        assert meta.table_name_by_table == {"warehouse.sales.users": "users", "staging.sales.users": "users"}

    def test_get_primary_keys_for_table_scopes_the_lookup(self, impl):
        conn = _conn()
        conn.fetchall.return_value = [(["id", "tenant_id"],)]
        assert impl.get_primary_keys_for_table(conn, "analytics", "users") == ["id", "tenant_id"]
        _sql, params = conn.execute.call_args.args
        assert params == ["analytics", "users"]

    @pytest.mark.parametrize("rows", [[], [(None,)], [([],)]])
    def test_get_primary_keys_for_table_returns_none_without_a_key(self, impl, rows):
        conn = _conn()
        conn.fetchall.return_value = rows
        assert impl.get_primary_keys_for_table(conn, "analytics", "users") is None

    def test_get_primary_keys_for_table_returns_none_when_lookup_fails(self, impl):
        # A failing lookup must degrade to None so the pipeline falls back instead of crashing.
        conn = _conn()
        conn.execute.side_effect = Exception("Catalog Error")
        assert impl.get_primary_keys_for_table(conn, "analytics", "users") is None

    # ------------------------------------------------------------------
    # build_pipeline
    # ------------------------------------------------------------------

    def _pipeline_mocks(self, primary_key_rows, rows_to_sync, batches):
        metadata_conn = _conn()
        metadata_conn.fetchall.return_value = primary_key_rows
        metadata_conn.fetchone.return_value = (rows_to_sync,)

        streaming_conn = _conn()
        schema = batches[0].schema
        streaming_conn.to_arrow_reader.return_value = pa.RecordBatchReader.from_batches(schema, batches)
        return metadata_conn, streaming_conn

    def test_build_pipeline_streams_bounded_arrow_batches(self, impl):
        batches = [pa.RecordBatch.from_pydict({"id": [1, 2]}), pa.RecordBatch.from_pydict({"id": [3]})]
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 3, batches)

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(_make_config(), _make_inputs(schema_name="users"))
            assert response.name == "users"
            assert response.primary_keys == ["id"]
            assert response.rows_to_sync == 3
            tables = list(response.items())

        assert [t.num_rows for t in tables] == [2, 1]
        sql, params = streaming_conn.execute.call_args.args
        assert sql == 'SELECT * FROM "analytics"."users"'
        assert params == []
        # DuckDB runs in-process, so the reader must be asked for bounded batches.
        streaming_conn.to_arrow_reader.assert_called_once_with(DEFAULT_MOTHERDUCK_FETCH_SIZE)

    def test_build_pipeline_incremental_query_filters_and_orders(self, impl):
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 1, [pa.RecordBatch.from_pydict({"id": [1]})])
        inputs = _make_inputs(
            schema_name="users",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(_make_config(), inputs)
            list(response.items())

        sql, params = streaming_conn.execute.call_args.args
        assert 'WHERE "updated_at" > ?' in sql
        # `sort_mode` defaults to ascending, so the query must actually order that way.
        assert sql.endswith('ORDER BY "updated_at" ASC')
        assert params == ["2026-01-01T00:00:00"]

    def test_build_pipeline_projection_retains_the_primary_key(self, impl):
        # Dropping the PK from the projection would break the Delta merge on every later sync.
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 1, [pa.RecordBatch.from_pydict({"id": [1]})])

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(_make_config(), _make_inputs(enabled_columns=["email"]))
            list(response.items())

        sql, _params = streaming_conn.execute.call_args.args
        assert sql.startswith('SELECT "email", "id" FROM "analytics"."users"')

    def test_build_pipeline_multi_schema_row_routes_to_its_own_namespace(self, impl):
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 1, [pa.RecordBatch.from_pydict({"id": [1]})])

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(_make_config(schema=""), _make_inputs(schema_name="sales.users"))
            # Delta subdir keeps the qualified, normalized name so cross-schema duplicates stay distinct.
            assert response.name == "sales_users"
            list(response.items())

        sql, _params = streaming_conn.execute.call_args.args
        assert 'FROM "sales"."users"' in sql
        # The PK probe targets the resolved namespace too.
        assert metadata_conn.execute.call_args_list[0].args[1] == ["sales", "users"]

    def test_build_pipeline_account_wide_row_switches_to_its_own_catalog(self, impl):
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 1, [pa.RecordBatch.from_pydict({"id": [1]})])

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(
                _make_config(database="", schema=""), _make_inputs(schema_name="warehouse.sales.users")
            )
            assert response.name == "warehouse_sales_users"
            list(response.items())

        # The catalog is pinned per row, so the table reference itself stays two-part.
        assert metadata_conn.execute.call_args_list[0].args[0] == 'USE "warehouse"'
        assert 'FROM "sales"."users"' in streaming_conn.execute.call_args.args[0]

    def test_build_pipeline_prefers_the_stamped_catalog_over_the_display_name(self, impl):
        # Discovery stamps the real location; a renamed row must follow the stamp, not its label.
        metadata_conn, streaming_conn = self._pipeline_mocks([(["id"],)], 1, [pa.RecordBatch.from_pydict({"id": [1]})])

        with patch(_CONNECT_PATH, side_effect=[metadata_conn, streaming_conn]):
            response = impl.build_pipeline(
                _make_config(database="", schema=""),
                _make_inputs(
                    schema_name="stale.label.users",
                    schema_metadata={
                        "source_catalog": "warehouse",
                        "source_schema": "sales",
                        "source_table_name": "users",
                    },
                ),
            )
            list(response.items())

        assert metadata_conn.execute.call_args_list[0].args[0] == 'USE "warehouse"'
        assert 'FROM "sales"."users"' in streaming_conn.execute.call_args.args[0]

    def test_build_pipeline_rejects_an_unresolvable_catalog(self, impl):
        # Account-wide with nothing naming a catalog: `USE` would be a guess, and the sync would
        # silently read whichever database DuckDB happens to resolve to.
        with patch(_CONNECT_PATH) as mock_connect:
            with pytest.raises(ValueError):
                impl.build_pipeline(_make_config(database=""), _make_inputs(schema_name="users"))
            mock_connect.assert_not_called()

    def test_build_pipeline_rejects_an_unresolvable_namespace(self, impl):
        # A blank config namespace plus a bare row name leaves nothing to qualify the table with,
        # and an unqualified `FROM users` would silently read whichever schema DuckDB resolves to.
        with patch(_CONNECT_PATH) as mock_connect:
            with pytest.raises(ValueError):
                impl.build_pipeline(_make_config(schema=""), _make_inputs(schema_name="users"))
            mock_connect.assert_not_called()

    # ------------------------------------------------------------------
    # Source-level behavior
    # ------------------------------------------------------------------

    @pytest.fixture
    def source(self) -> MotherduckSource:
        return MotherduckSource()

    def test_source_is_visible_and_marked_alpha(self, source):
        # `unreleasedSource` hides a source from users entirely — a finished source must not set it.
        config = source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_schema_field_is_optional_for_multi_schema_support(self, source):
        # `is_multi_schema_capable_sql_source` keys off the schema field being optional.
        schema_field = next(f for f in source.get_source_config.fields if f.name == "schema")
        assert isinstance(schema_field, SourceFieldInputConfig)
        assert schema_field.required is False

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Catalog Error: Table with name users does not exist!",
            "Binder Error: Referenced column email not found in FROM clause!",
            "Invalid Input Error: The following options were not recognized: motherduck_token",
            "Source column type changed",
        ],
    )
    def test_permanent_failures_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable), f"Error should be non-retryable: {error_msg}"

    def test_validate_credentials_requires_an_access_token(self, source):
        ok, message = source.validate_credentials(_make_config(access_token=""), team_id=1)
        assert ok is False
        assert message is not None and "access token" in message

    @pytest.mark.parametrize("database", ["", "   ", None])
    def test_validate_credentials_accepts_a_blank_database(self, source, database):
        # Blank means "every database in the account", so it must not be rejected up front.
        with patch.object(MotherduckSource, "get_schemas", return_value=[]):
            ok, message = source.validate_credentials(_make_config(database=database), team_id=1)
        assert ok is True
        assert message is None

    @pytest.mark.parametrize(
        "error,expected_fragment",
        [
            (Exception("IO Error: MotherDuck token is invalid"), "access token"),
            (Exception("Catalog Error: Database with name nope does not exist!"), "database and schema names"),
            (Exception("Binder Error: Referenced column not found"), "rejected the query"),
            (Exception("Invalid Input Error: bad option"), "connection details"),
            (ValueError("Invalid MotherDuck database name: 'my db'"), "Invalid MotherDuck database name"),
            (Exception("something totally unexpected"), "Could not connect to MotherDuck"),
        ],
    )
    def test_validate_credentials_maps_connection_errors(self, source, error, expected_fragment):
        with patch.object(MotherduckSource, "get_schemas", side_effect=error):
            ok, message = source.validate_credentials(_make_config(), team_id=1)
        assert ok is False
        assert message is not None and expected_fragment in message

    def test_validate_credentials_success(self, source):
        with patch.object(MotherduckSource, "get_schemas", return_value=[MagicMock()]):
            assert source.validate_credentials(_make_config(), team_id=1) == (True, None)
