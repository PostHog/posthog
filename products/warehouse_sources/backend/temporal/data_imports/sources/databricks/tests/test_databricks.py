import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from databricks.sql.exc import RequestError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.databricks.databricks import (
    DatabricksImplementation,
    clean_databricks_host,
    filter_databricks_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.databricks.source import DatabricksSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.databricks import (
    DatabricksSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_CONNECT_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.databricks.databricks.databricks_sql.connect"
)
_SLEEP_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.databricks.databricks.time.sleep"

_SSL_EOF_ERROR_MSG = (
    "Error during request to server: HTTPSConnectionPool(host='x', port=443): Max retries exceeded"
    " with url: /oidc/v1/token (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING]"
    " EOF occurred in violation of protocol')))"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(auth_type: str = "access_token", **overrides) -> DatabricksSourceConfig:
    auth: dict
    if auth_type == "access_token":
        auth = {"selection": "access_token", "access_token": "dapi-token"}
    else:
        auth = {"selection": "service_principal", "client_id": "cid", "client_secret": "secret"}
    defaults: dict = {
        "host": "dbc-abc123.cloud.databricks.com",
        "http_path": "/sql/1.0/warehouses/wh123",
        "catalog": "main",
        "schema": "analytics",
        "auth_type": auth,
    }
    defaults.update(overrides)
    return DatabricksSourceConfig.from_dict(defaults)


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


def _cursor() -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.fetchall.return_value = []
    c.fetchone.return_value = None
    return c


def _conn_with_cursor(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Users paste the whole workspace URL from the browser; the connector wants a bare hostname.
        ("dbc-abc123.cloud.databricks.com", "dbc-abc123.cloud.databricks.com"),
        ("https://dbc-abc123.cloud.databricks.com", "dbc-abc123.cloud.databricks.com"),
        ("https://dbc-abc123.cloud.databricks.com/", "dbc-abc123.cloud.databricks.com"),
        ("http://adb-123.11.azuredatabricks.net/", "adb-123.11.azuredatabricks.net"),
        ("  dbc-abc123.cloud.databricks.com  ", "dbc-abc123.cloud.databricks.com"),
    ],
)
def test_clean_databricks_host(raw, expected):
    assert clean_databricks_host(raw) == expected


class TestFilterIncrementalFields:
    @pytest.mark.parametrize(
        "data_type,expected",
        [
            ("TIMESTAMP", IncrementalFieldType.Timestamp),
            ("TIMESTAMP_NTZ", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("BIGINT", IncrementalFieldType.Numeric),
            ("int", IncrementalFieldType.Numeric),
            ("SMALLINT", IncrementalFieldType.Numeric),
            ("TINYINT", IncrementalFieldType.Numeric),
            # Databricks reports the parameterized form, so an equality match would drop these.
            ("DECIMAL(10,2)", IncrementalFieldType.Numeric),
            ("decimal(38,0)", IncrementalFieldType.Numeric),
        ],
    )
    def test_picks_up_supported_types(self, data_type, expected):
        assert filter_databricks_incremental_fields([("c", data_type, True)]) == [("c", expected, True)]

    @pytest.mark.parametrize("data_type", ["STRING", "BOOLEAN", "BINARY", "DOUBLE", "FLOAT", "ARRAY<INT>", "VARIANT"])
    def test_drops_unsupported_types(self, data_type):
        # Floats are deliberately excluded — an imprecise cursor skips or re-reads rows at the boundary.
        assert filter_databricks_incremental_fields([("c", data_type, True)]) == []


# ---------------------------------------------------------------------------
# Implementation fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> DatabricksImplementation:
    return DatabricksImplementation()


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


class TestConnect:
    def test_access_token_auth_passes_token(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config()):
                pass
            kwargs = mock_connect.call_args.kwargs
            assert kwargs["access_token"] == "dapi-token"
            assert "credentials_provider" not in kwargs
            assert kwargs["server_hostname"] == "dbc-abc123.cloud.databricks.com"
            assert kwargs["http_path"] == "/sql/1.0/warehouses/wh123"
            assert kwargs["catalog"] == "main"

    def test_service_principal_auth_uses_credentials_provider(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config("service_principal")):
                pass
            kwargs = mock_connect.call_args.kwargs
            assert "access_token" not in kwargs
            assert callable(kwargs["credentials_provider"])

    def test_pasted_workspace_url_is_cleaned(self, impl):
        # A `https://…/` host reaches the connector as a bare hostname, or every request fails.
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config(host="https://dbc-abc123.cloud.databricks.com/")):
                pass
            assert mock_connect.call_args.kwargs["server_hostname"] == "dbc-abc123.cloud.databricks.com"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_schema_reaches_connector_as_none(self, impl, blank):
        # `schema=""` would make the connector try `USE SCHEMA ""` (invalid) — normalize to None.
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config(schema=blank)):
                pass
            assert mock_connect.call_args.kwargs["schema"] is None

    def test_connection_closed_on_exit(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with impl.connect(_make_config()):
                mock_connect.return_value.close.assert_not_called()
            mock_connect.return_value.close.assert_called_once()

    def test_connection_closed_on_error(self, impl):
        with patch(_CONNECT_PATH) as mock_connect:
            with pytest.raises(RuntimeError):
                with impl.connect(_make_config()):
                    raise RuntimeError("boom")
            mock_connect.return_value.close.assert_called_once()

    def test_transient_ssl_eof_on_connect_is_retried(self, impl):
        # The connector's own retry loop treats a bare SSL error during `open_session` (including
        # the OAuth token fetch) as non-retryable and raises immediately — connect() must recover
        # a transient peer-close instead of failing the sync on the first blip.
        mock_conn = MagicMock()
        with patch(_CONNECT_PATH, side_effect=[RequestError(_SSL_EOF_ERROR_MSG, {}, "x"), mock_conn]) as mock_connect:
            with patch(_SLEEP_PATH):
                with impl.connect(_make_config()) as conn:
                    assert conn is mock_conn
            assert mock_connect.call_count == 2

    def test_transient_ssl_eof_exhausts_retries_and_raises(self, impl):
        with patch(_CONNECT_PATH, side_effect=RequestError(_SSL_EOF_ERROR_MSG, {}, "x")) as mock_connect:
            with patch(_SLEEP_PATH):
                with pytest.raises(RequestError):
                    with impl.connect(_make_config()):
                        pass
            assert mock_connect.call_count == 5

    def test_non_transient_connect_error_is_not_retried(self, impl):
        # A permission/config error must surface on the first attempt — only the specific
        # transient SSL peer-close signature is worth retrying.
        with patch(_CONNECT_PATH, side_effect=RequestError("[PERMISSION_DENIED] nope", {}, "x")) as mock_connect:
            with pytest.raises(RequestError):
                with impl.connect(_make_config()):
                    pass
            assert mock_connect.call_count == 1


# ---------------------------------------------------------------------------
# Listing methods — they take a pre-opened connection
# ---------------------------------------------------------------------------


class TestGetColumns:
    def test_groups_columns_by_table(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", "BIGINT", "NO"),
            ("analytics", "users", "email", "STRING", "YES"),
            ("analytics", "orders", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(_conn_with_cursor(cursor), _make_config(), names=None)
        # Single-schema source keeps bare table names.
        assert set(result.keys()) == {"users", "orders"}
        assert ("id", "BIGINT", False) in result["users"]
        assert ("email", "STRING", True) in result["users"]

    def test_single_schema_filters_by_configured_schema(self, impl):
        cursor = _cursor()
        impl.get_columns(_conn_with_cursor(cursor), _make_config(schema="sales"), names=None)
        sql, params = cursor.execute.call_args.args
        assert "table_schema = :schema" in sql
        assert "`main`.`information_schema`.`columns`" in sql
        assert params == {"schema": "sales"}

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_schema_discovers_all_namespaces_qualified(self, impl, blank):
        cursor = _cursor()
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", "BIGINT", "NO"),
            ("sales", "users", "id", "BIGINT", "NO"),
            ("sales", "orders", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(_conn_with_cursor(cursor), _make_config(schema=blank), names=None)
        # Same table name in two schemas must stay distinct and qualified.
        assert set(result.keys()) == {"analytics.users", "sales.users", "sales.orders"}
        sql, params = cursor.execute.call_args.args
        assert "table_schema != :system_schema" in sql
        assert params == {"system_schema": "information_schema"}

    def test_filters_by_names(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", "BIGINT", "NO"),
            ("analytics", "orders", "id", "BIGINT", "NO"),
        ]
        result = impl.get_columns(_conn_with_cursor(cursor), _make_config(), names=["users"])
        assert list(result.keys()) == ["users"]

    def test_qualified_name_falls_back_to_bare_discovery_key(self, impl):
        # Mid-migration a row may be requested qualified while a configured-schema source still
        # discovers it bare — keep the requested (qualified) key, mapped to the bare columns.
        cursor = _cursor()
        cursor.fetchall.return_value = [("analytics", "users", "id", "BIGINT", "NO")]
        result = impl.get_columns(
            _conn_with_cursor(cursor), _make_config(schema="analytics"), names=["analytics.users"]
        )
        assert result == {"analytics.users": [("id", "BIGINT", False)]}


class TestGetPrimaryKeys:
    def test_orders_composite_key_by_ordinal_position(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = [
            ("analytics", "users", "tenant_id", 2),
            ("analytics", "users", "id", 1),
        ]
        out = impl.get_primary_keys(_conn_with_cursor(cursor), _make_config(), tables=["users"])
        assert out["users"] == ["id", "tenant_id"]
        # One batched information_schema query, not one per table.
        assert cursor.execute.call_count == 1

    def test_multi_schema_routes_keys_to_qualified_display_names(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = [
            ("analytics", "users", "id", 1),
            ("sales", "users", "uuid", 1),
        ]
        out = impl.get_primary_keys(
            _conn_with_cursor(cursor), _make_config(schema=""), tables=["analytics.users", "sales.users"]
        )
        assert out == {"analytics.users": ["id"], "sales.users": ["uuid"]}

    def test_swallows_failure_and_returns_none_placeholders(self, impl):
        # `hive_metastore` catalogs have no information_schema — discovery must keep working without PKs.
        cursor = _cursor()
        cursor.execute.side_effect = Exception("[TABLE_OR_VIEW_NOT_FOUND] information_schema")
        out = impl.get_primary_keys(_conn_with_cursor(cursor), _make_config(), tables=["users"])
        assert out == {"users": None}


class TestGetSourceMetadata:
    def test_single_schema_pins_configured_namespace(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema="analytics"), tables=["users"])
        assert meta.catalog_by_table == {"users": "main"}
        assert meta.schema_by_table == {"users": "analytics"}
        assert meta.table_name_by_table == {"users": "users"}

    def test_multi_schema_splits_qualified_display_names(self, impl):
        meta = impl.get_source_metadata(MagicMock(), _make_config(schema=""), tables=["analytics.users", "sales.users"])
        assert meta.schema_by_table == {"analytics.users": "analytics", "sales.users": "sales"}
        assert meta.table_name_by_table == {"analytics.users": "users", "sales.users": "users"}


class TestGetPrimaryKeysForTable:
    def test_returns_ordered_keys_scoped_to_table(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = [("id", 1), ("tenant_id", 2)]
        keys = impl.get_primary_keys_for_table(cursor, "main", "analytics", "users")
        assert keys == ["id", "tenant_id"]
        sql, params = cursor.execute.call_args.args
        assert params == {"schema": "analytics", "table_name": "users"}
        assert "`main`.`information_schema`.`table_constraints`" in sql

    def test_returns_none_when_lookup_fails(self, impl):
        # A permission/missing-information_schema failure must degrade to None so the pipeline falls
        # back to a persisted or `id`-column PK instead of crashing the sync.
        cursor = _cursor()
        cursor.execute.side_effect = Exception("PERMISSION_DENIED")
        assert impl.get_primary_keys_for_table(cursor, "main", "analytics", "users") is None

    def test_returns_none_when_no_pk_defined(self, impl):
        cursor = _cursor()
        cursor.fetchall.return_value = []
        assert impl.get_primary_keys_for_table(cursor, "main", "analytics", "users") is None


class TestFetchTableStats:
    def test_reads_size_from_describe_detail_and_counts_rows(self, impl):
        cursor = _cursor()
        # `DESCRIBE DETAIL` column order isn't contractual — sizeInBytes must be found by name.
        cursor.description = [("format",), ("name",), ("sizeInBytes",)]
        cursor.fetchone.side_effect = [("delta", "users", 10_485_760), (2_000,)]
        stats = impl.fetch_table_stats(cursor, "analytics", "users", MagicMock())
        assert stats == TableStats(table_size_bytes=10_485_760, row_count=2_000)
        assert cursor.execute.call_args_list[0].args[0] == "DESCRIBE DETAIL `analytics`.`users`"
        assert cursor.execute.call_args_list[1].args[0] == "SELECT COUNT(*) FROM `analytics`.`users`"

    def test_returns_none_when_size_column_missing(self, impl):
        # Views and federated tables don't report sizeInBytes — partition sizing must be skipped.
        cursor = _cursor()
        cursor.description = [("format",), ("name",)]
        cursor.fetchone.return_value = ("view", "users")
        assert impl.fetch_table_stats(cursor, "analytics", "users", MagicMock()) is None

    def test_returns_none_for_empty_table(self, impl):
        cursor = _cursor()
        cursor.description = [("sizeInBytes",)]
        cursor.fetchone.side_effect = [(1024,), (0,)]
        assert impl.fetch_table_stats(cursor, "analytics", "users", MagicMock()) is None


# ---------------------------------------------------------------------------
# build_pipeline end-to-end (mocked driver)
# ---------------------------------------------------------------------------


def _pipeline_mocks(pk_rows: list[tuple], row_count: int, arrow_batches: list[pa.Table]):
    """Two connections (metadata pass + streaming pass), each with one cursor."""
    metadata_cursor = _cursor()
    metadata_cursor.fetchall.return_value = pk_rows
    metadata_cursor.fetchone.return_value = (row_count,)

    streaming_cursor = _cursor()
    streaming_cursor.fetchmany_arrow.side_effect = [*arrow_batches, pa.table({"id": pa.array([], type=pa.int64())})]

    connections = []
    for cursor in (metadata_cursor, streaming_cursor):
        conn = MagicMock()
        conn.cursor.return_value = cursor
        connections.append(conn)

    return metadata_cursor, streaming_cursor, connections


class TestBuildPipeline:
    def test_builds_source_response_and_streams_until_empty_batch(self, impl):
        batch = pa.table({"id": [1, 2, 3]})
        metadata_cursor, streaming_cursor, connections = _pipeline_mocks(
            pk_rows=[("id", 1)], row_count=3, arrow_batches=[batch]
        )

        with patch(_CONNECT_PATH, side_effect=connections):
            response = impl.build_pipeline(_make_config(), _make_inputs(schema_name="users"))
            assert response.name == "users"
            assert response.primary_keys == ["id"]
            assert response.rows_to_sync == 3
            # Full refresh rewrites the whole table — the partition probes must be skipped.
            assert response.partition_count is None
            assert response.partition_size is None
            # The stream must terminate on the first empty arrow batch — not loop forever.
            assert list(response.items()) == [batch]

        sql, params = streaming_cursor.execute.call_args.args
        assert sql == "SELECT * FROM `analytics`.`users`"
        assert params == {}

    def test_incremental_query_filters_and_orders(self, impl):
        metadata_cursor, streaming_cursor, connections = _pipeline_mocks(
            pk_rows=[("id", 1)], row_count=1, arrow_batches=[pa.table({"id": [1]})]
        )
        # Incremental syncs also probe table stats: rows_to_sync COUNT, DESCRIBE DETAIL, stats COUNT.
        metadata_cursor.description = [("sizeInBytes",)]
        metadata_cursor.fetchone.side_effect = [(1_000,), (10_485_760,), (1_000,)]
        inputs = _make_inputs(
            schema_name="users",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value="2025-01-01T00:00:00",
        )

        with patch(_CONNECT_PATH, side_effect=connections):
            response = impl.build_pipeline(_make_config(), inputs)
            # Table stats feed the shared partition math so incremental merges get md5 partitioning.
            assert response.partition_count is not None
            assert response.partition_size is not None
            list(response.items())

        sql, params = streaming_cursor.execute.call_args.args
        assert "WHERE `updated_at` > :incremental_value" in sql
        assert "ORDER BY `updated_at` ASC" in sql
        assert params == {"incremental_value": "2025-01-01T00:00:00"}

    def test_enabled_columns_projection_retains_primary_key(self, impl):
        # Dropping the PK from the projection would break the Delta merge on every later sync.
        metadata_cursor, streaming_cursor, connections = _pipeline_mocks(
            pk_rows=[("id", 1)], row_count=1, arrow_batches=[pa.table({"id": [1]})]
        )
        inputs = _make_inputs(schema_name="users", enabled_columns=["email"])

        with patch(_CONNECT_PATH, side_effect=connections):
            response = impl.build_pipeline(_make_config(), inputs)
            list(response.items())

        sql, _ = streaming_cursor.execute.call_args.args
        assert sql.startswith("SELECT `email`, `id` FROM `analytics`.`users`")

    def test_multi_schema_row_routes_to_qualified_namespace(self, impl):
        # A blank-namespace source pins each row's schema via the dotted schema_name.
        metadata_cursor, streaming_cursor, connections = _pipeline_mocks(
            pk_rows=[("id", 1)], row_count=1, arrow_batches=[pa.table({"id": [1]})]
        )

        with patch(_CONNECT_PATH, side_effect=connections):
            response = impl.build_pipeline(_make_config(schema=""), _make_inputs(schema_name="sales.users"))
            # Delta subdir keeps the qualified, normalized name so cross-schema duplicates stay distinct.
            assert response.name == "sales_users"
            list(response.items())

        sql, _ = streaming_cursor.execute.call_args.args
        assert "FROM `sales`.`users`" in sql
        # PK probe targets the resolved schema too.
        pk_params = metadata_cursor.execute.call_args_list[0].args[1]
        assert pk_params == {"schema": "sales", "table_name": "users"}


# ---------------------------------------------------------------------------
# Source-level behavior
# ---------------------------------------------------------------------------


class TestDatabricksSource:
    @pytest.fixture
    def source(self) -> DatabricksSource:
        return DatabricksSource()

    def test_schema_field_is_optional_for_multi_schema_support(self, source):
        # `is_multi_schema_capable_sql_source` keys off the schema field being optional — making it
        # required would silently turn off multi-schema import for Databricks.
        schema_field = next(f for f in source.get_source_config.fields if f.name == "schema")
        assert schema_field.required is False

    def test_host_is_a_connection_host_field(self, source):
        # Retargeting the workspace hostname must force credential re-entry (exfiltration gate).
        assert source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Invalid access token.",
            "Error during request to server: b'Invalid access token. (403)'",
            "invalid_client: Client authentication failed",
            "[CATALOG_NOT_FOUND] The catalog 'main' cannot be found.",
            "[SCHEMA_NOT_FOUND] The schema 'analytics' cannot be found.",
            "PERMISSION_DENIED: User does not have USE SCHEMA on Schema 'analytics'.",
            "[TABLE_OR_VIEW_NOT_FOUND] The table or view `main`.`information_schema`.`columns` cannot be found.",
            # Workspace IP ACL rejection — matched on the stable phrase, ignoring the appended IP
            # address and workspace id.
            "Error during request to server: : Source IP address: 44.208.188.173 is blocked by Databricks IP ACL for workspace: 1557520918149316. ",
        ],
    )
    def test_permanent_failures_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable), f"Error should be non-retryable: {error_msg}"

    def test_validate_credentials_requires_access_token(self, source):
        config = DatabricksSourceConfig.from_dict(
            {"host": "h", "http_path": "p", "catalog": "main", "auth_type": {"selection": "access_token"}}
        )
        ok, message = source.validate_credentials(config, team_id=1)
        assert ok is False
        assert message is not None and "access token" in message

    def test_validate_credentials_requires_client_id_and_secret(self, source):
        config = DatabricksSourceConfig.from_dict(
            {
                "host": "h",
                "http_path": "p",
                "catalog": "main",
                "auth_type": {"selection": "service_principal", "client_id": "cid"},
            }
        )
        ok, message = source.validate_credentials(config, team_id=1)
        assert ok is False
        assert message is not None and "client" in message.lower()

    @pytest.mark.parametrize(
        "error_msg,expected_fragment",
        [
            ("Error during request to server: b'Invalid access token. (403)'", "access token"),
            ("invalid_client: Client authentication failed", "service principal"),
            ("[CATALOG_NOT_FOUND] The catalog 'main' cannot be found.", "catalog"),
            (
                "[TABLE_OR_VIEW_NOT_FOUND] The table or view `information_schema`.`columns` cannot be found.",
                "Unity Catalog",
            ),
            (
                "Error during request to server: : Source IP address: 44.208.188.173 is blocked by Databricks IP ACL for workspace: 1557520918149316. ",
                "IP access control list",
            ),
            ("[RESOURCE_DOES_NOT_EXIST] Warehouse abc123 does not exist.", "SQL warehouse"),
            ("something totally unexpected", "Could not connect to Databricks"),
        ],
    )
    def test_validate_credentials_maps_connection_errors(self, source, error_msg, expected_fragment):
        with patch.object(DatabricksSource, "get_schemas", side_effect=Exception(error_msg)):
            ok, message = source.validate_credentials(_make_config(), team_id=1)
        assert ok is False
        assert message is not None and expected_fragment in message

    def test_validate_credentials_success(self, source):
        with patch.object(DatabricksSource, "get_schemas", return_value=[MagicMock()]):
            assert source.validate_credentials(_make_config(), team_id=1) == (True, None)

    def test_validate_credentials_blocks_internal_host_before_connecting(self, source):
        # Guards the SSRF fix: a rejected host must short-circuit before any request reaches it.
        with (
            patch.object(DatabricksSource, "is_database_host_valid", return_value=(False, "Host is not allowed")),
            patch.object(DatabricksSource, "get_schemas") as mock_get_schemas,
        ):
            ok, message = source.validate_credentials(_make_config(), team_id=1)
        assert ok is False
        assert message == "Host is not allowed"
        mock_get_schemas.assert_not_called()
