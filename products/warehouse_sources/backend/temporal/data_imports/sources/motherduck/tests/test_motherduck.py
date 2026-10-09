import pytest
from unittest.mock import MagicMock, patch

import duckdb
import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
    MotherduckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    DUCKDB_LOCAL_CONFIG,
    MotherDuckConnectionError,
    MotherDuckImplementation,
    build_motherduck_connection_string,
    connect,
    filter_motherduck_incremental_fields,
    translate_motherduck_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.source import MotherduckSource
from products.warehouse_sources.backend.types import IncrementalFieldType

_SERVICE_UNAVAILABLE_ERROR = (
    'Invalid Input Error: Initialization function "motherduck_duckdb_cpp_init" failed: '
    "Request failed: Could not connect to MotherDuck. Please try again later"
)

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
            (_SERVICE_UNAVAILABLE_ERROR, "MotherDuck is temporarily unavailable"),
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

    # ------------------------------------------------------------------
    # connect()
    # ------------------------------------------------------------------

    def test_config_redirects_extension_storage_off_the_home_directory(self):
        # `home_directory` alone leaves extension storage at `~/.duckdb`, so it needs its own key.
        assert DUCKDB_LOCAL_CONFIG["extension_directory"] != DUCKDB_LOCAL_CONFIG["home_directory"]
        assert DUCKDB_LOCAL_CONFIG["extension_directory"].startswith(DUCKDB_LOCAL_CONFIG["home_directory"])

    def test_connect_closes_on_error(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with pytest.raises(RuntimeError):
                with impl.connect(_make_config()):
                    raise RuntimeError("boom")
            mock_connect.return_value.close.assert_called_once()

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

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

    @pytest.mark.parametrize(
        "driver_error",
        [
            "Invalid Input Error: bad connection option",
            "Invalid Input Error: bad connection option, please try again later",
        ],
        ids=["bad_option", "generic_try_again_phrase"],
    )
    def test_connection_failure_is_non_retryable_end_to_end(self, source, driver_error):
        # Reproduces the real path: `connect()` wraps and translates the driver error before
        # raising, so the non-retryable match has to run against that translated text, not the
        # raw DuckDB error class. A key that only matches the raw class (as this dict used to)
        # would let a bad database name or malformed token retry indefinitely.
        with patch(_CONNECT_PATH, side_effect=duckdb.Error(driver_error)):
            with pytest.raises(MotherDuckConnectionError) as exc_info:
                connect("md-token", "my_db")

        assert error_message_matches(str(exc_info.value), source.get_non_retryable_errors())

    def test_service_outages_keep_retrying(self, source):
        # The import activity consults the non-retryable set first, so an outage has to miss that
        # set entirely or it stops the sync and asks the owner to check credentials they can't fix.
        assert not error_message_matches(_SERVICE_UNAVAILABLE_ERROR, source.get_non_retryable_errors())
        assert error_message_matches(_SERVICE_UNAVAILABLE_ERROR, source.get_retryable_errors())
        assert error_message_matches(_SERVICE_UNAVAILABLE_ERROR, source.get_retry_exhausted_errors())

    def test_an_outage_stays_retryable_once_connect_has_translated_it(self, source):
        # `connect()` replaces the driver text with our own copy, so classification runs against
        # that copy for any failure raised while opening a connection.
        with patch(_CONNECT_PATH, side_effect=duckdb.Error(_SERVICE_UNAVAILABLE_ERROR)):
            with pytest.raises(MotherDuckConnectionError) as exc_info:
                connect("md-token", "my_db")

        assert not error_message_matches(str(exc_info.value), source.get_non_retryable_errors())
        assert error_message_matches(str(exc_info.value), source.get_retryable_errors())

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
            (Exception(_SERVICE_UNAVAILABLE_ERROR), "MotherDuck is temporarily unavailable"),
            (ValueError("Invalid MotherDuck database name: 'my db'"), "Invalid MotherDuck database name"),
            (Exception("something totally unexpected"), "Could not connect to MotherDuck"),
        ],
    )
    def test_validate_credentials_maps_connection_errors(self, source, error, expected_fragment):
        with patch.object(MotherduckSource, "get_schemas", side_effect=error):
            ok, message = source.validate_credentials(_make_config(), team_id=1)
        assert ok is False
        assert message is not None and expected_fragment in message
