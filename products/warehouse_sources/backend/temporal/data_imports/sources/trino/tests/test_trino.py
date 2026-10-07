import datetime as dt
from collections.abc import Iterable
from contextlib import nullcontext
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from trino.exceptions import HttpError, TrinoConnectionError, TrinoExternalError, TrinoUserError
from trino.types import NamedRowTuple

from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (
    _classify_refresh_schemas_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import (
    TrinoAuthTypeConfig,
    TrinoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.source import TrinoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import (
    TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR,
    TRINO_ACCESS_DENIED_ERROR,
    TRINO_AUTHENTICATION_ERROR,
    TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR,
    DiscoveredTrinoTable,
    TrinoColumn,
    TrinoImplementation,
    TrinoSchemaDiscoveryError,
    build_trino_select,
    connect_trino,
    discover_trino_schemas,
    filter_trino_incremental_fields,
    trino_error_to_message,
    trino_failures_as_sync_error,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _config(**overrides: object) -> TrinoSourceConfig:
    values: dict[str, object] = {
        "host": "trino.example.com",
        "port": 443,
        "catalog": "hive",
        "schema": None,
        "use_ssl": True,
        "verify_ssl": True,
        "auth_type": TrinoAuthTypeConfig(user="posthog", selection="password", password="secret"),
    }
    values.update(overrides)
    return TrinoSourceConfig(**values)  # type: ignore[arg-type]


def test_connect_trino_uses_tracked_session_and_closes_resources() -> None:
    connection = MagicMock()
    session = MagicMock()

    with (
        patch("trino.dbapi.connect", return_value=connection) as mock_connect,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ) as mock_session,
        connect_trino(_config()) as opened,
    ):
        assert opened is connection

    mock_session.assert_called_once_with(redact_values=("secret",), allow_redirects=False)
    assert session.verify is True
    assert mock_connect.call_args.kwargs["host"] == "trino.example.com"
    assert mock_connect.call_args.kwargs["catalog"] == "hive"
    assert mock_connect.call_args.kwargs["http_scheme"] == "https"
    assert mock_connect.call_args.kwargs["http_session"] is session
    assert mock_connect.call_args.kwargs["verify"] is True
    connection.close.assert_called_once_with()
    session.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("host", "port", "use_ssl", "verify_ssl", "expected_trust_env"),
    [
        ("trino.dw.us.postwh.com", 443, True, True, False),
        ("TRINO.DW.DEV.POSTWH.COM.", 443, True, True, False),
        ("trino.example.com", 443, True, True, True),
        ("other.dw.us.postwh.com", 443, True, True, True),
        ("tenant.dw.dev.postwh.com", 443, True, True, True),
        ("nested.tenant.dw.us.postwh.com", 443, True, True, True),
        ("dw.us.postwh.com", 443, True, True, True),
        ("tenant.dw.us.postwh.com.example.com", 443, True, True, True),
        ("trino.dw.us.postwh.com", 8443, True, True, True),
        ("trino.dw.us.postwh.com", 443, False, True, True),
        ("trino.dw.us.postwh.com", 443, True, False, True),
    ],
)
def test_connect_trino_bypasses_proxy_only_for_managed_tls_endpoints(
    host: str, port: int, use_ssl: bool, verify_ssl: bool, expected_trust_env: bool
) -> None:
    connection = MagicMock()
    session = MagicMock(trust_env=True)
    auth_type = TrinoAuthTypeConfig(user="posthog", selection="none")

    with (
        patch("trino.dbapi.connect", return_value=connection),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ),
        connect_trino(
            _config(
                host=host,
                port=port,
                use_ssl=use_ssl,
                verify_ssl=verify_ssl,
                auth_type=auth_type,
            )
        ),
    ):
        pass

    assert session.trust_env is expected_trust_env


def test_connect_trino_rejects_credentials_over_http() -> None:
    with pytest.raises(ValueError, match="require HTTPS"):
        with connect_trino(_config(use_ssl=False)):
            pass


@pytest.mark.parametrize(
    "auth_type",
    [
        TrinoAuthTypeConfig(user="posthog", selection="password", password="secret"),
        TrinoAuthTypeConfig(user="posthog", selection="jwt", token="token"),
    ],
    ids=["password", "jwt"],
)
def test_connect_trino_rejects_credentials_without_tls_verification(auth_type: TrinoAuthTypeConfig) -> None:
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session"
        ) as mock_session,
        pytest.raises(ValueError, match=TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR),
        connect_trino(_config(auth_type=auth_type, verify_ssl=False)),
    ):
        pass

    mock_session.assert_not_called()


def test_connect_trino_allows_unverified_connection_without_credentials() -> None:
    connection = MagicMock()
    session = MagicMock()
    auth_type = TrinoAuthTypeConfig(user="posthog", selection="none")

    with (
        patch("trino.dbapi.connect", return_value=connection) as mock_connect,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ),
        connect_trino(_config(auth_type=auth_type, verify_ssl=False)),
    ):
        pass

    assert session.verify is False
    assert mock_connect.call_args.kwargs["auth"] is None
    assert mock_connect.call_args.kwargs["verify"] is False


def test_trino_error_to_message_preserves_tls_verification_action() -> None:
    error = ValueError(TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR)

    assert trino_error_to_message(error) == TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR


@pytest.mark.parametrize(
    ("raw_error", "expected"),
    [
        ("TrinoExternalError: Failed to query OPA backend", TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR),
        ("Access Denied: Cannot select from table hive.analytics.events", TRINO_ACCESS_DENIED_ERROR),
        ("Authentication failed for user posthog", TRINO_AUTHENTICATION_ERROR),
        ("error 401", TRINO_AUTHENTICATION_ERROR),
        # A Trino query error's text carries a query ID (YYYYMMDD_HHMMSS_seq_random). The "401" in
        # its time part must not turn an access denial into an authentication error.
        (
            'TrinoUserError(type=USER_ERROR, name=PERMISSION_DENIED, message="Access Denied: '
            'Cannot select from table hive.analytics.events", query_id=20260902_123401_00000_abcde)',
            TRINO_ACCESS_DENIED_ERROR,
        ),
    ],
)
def test_trino_error_to_message_explains_access_failures(raw_error: str, expected: str) -> None:
    assert trino_error_to_message(RuntimeError(raw_error)) == expected


def _trino_external_error(message: str) -> TrinoExternalError:
    return TrinoExternalError(
        {
            "message": message,
            "errorName": "EXTERNAL",
            "errorCode": 65536,
            "errorType": "EXTERNAL",
            "failureInfo": {},
        },
        "20260902_120000_00000_abcde",
    )


def test_get_schemas_reports_what_trino_said_without_an_exception_report() -> None:
    source = TrinoSource()

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.source.connect_trino",
            side_effect=_trino_external_error("Failed to query OPA backend"),
        ),
        pytest.raises(TrinoSchemaDiscoveryError) as raised,
    ):
        source.get_schemas(_config(), team_id=1)

    message, is_expected_source_error = _classify_refresh_schemas_error(source, raised.value)
    assert message == TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR
    assert is_expected_source_error is True


def test_get_schemas_leaves_a_posthog_side_failure_for_error_tracking() -> None:
    source = TrinoSource()

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.source.connect_trino",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.source.discover_trino_schemas",
            side_effect=ValueError("not enough values to unpack (expected 5, got 4)"),
        ),
        pytest.raises(ValueError) as raised,
    ):
        source.get_schemas(_config(), team_id=1)

    _, is_expected_source_error = _classify_refresh_schemas_error(source, raised.value)
    assert is_expected_source_error is False


def test_unrecognized_trino_discovery_failure_is_not_reported_as_a_posthog_exception() -> None:
    source = TrinoSource()

    _, is_expected_source_error = _classify_refresh_schemas_error(
        source, TrinoSchemaDiscoveryError("Query exceeded per-node memory limit")
    )

    assert is_expected_source_error is True


def test_connect_trino_closes_tracked_session_when_connect_fails() -> None:
    session = MagicMock()

    with (
        patch("trino.dbapi.connect", side_effect=RuntimeError("connection failed")),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.make_tracked_session",
            return_value=session,
        ),
        pytest.raises(RuntimeError, match="connection failed"),
        connect_trino(_config()),
    ):
        pass

    session.close.assert_called_once_with()


def test_discover_trino_schemas_groups_columns_and_filters_names() -> None:
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("analytics", "events"), ("sales", "orders")],
        [
            ("analytics", "events", "id", "bigint", "NO"),
            ("analytics", "events", "properties", "map(varchar, varchar)", "YES"),
        ],
    ]

    discovered = discover_trino_schemas(cursor, _config(), names=["analytics.events"])

    assert discovered == [
        DiscoveredTrinoTable(
            catalog="hive",
            schema="analytics",
            name="events",
            columns=(
                TrinoColumn(name="id", data_type="bigint", nullable=False),
                TrinoColumn(name="properties", data_type="map(varchar, varchar)", nullable=True),
            ),
        )
    ]
    assert cursor.execute.call_count == 2
    assert 'FROM "hive".information_schema.tables' in cursor.execute.call_args_list[0].args[0]
    assert 'FROM "hive".information_schema.columns' in cursor.execute.call_args_list[1].args[0]
    assert cursor.execute.call_args_list[1].args[1] == ["analytics", "events"]


def test_discover_trino_schemas_fetches_columns_in_bounded_batches() -> None:
    cursor = MagicMock()
    analytics_tables = [("analytics", f"table_{index}") for index in range(101)]
    cursor.fetchall.side_effect = [
        [*analytics_tables, ("sales", "orders")],
        [("analytics", f"table_{index}", "id", "bigint", "NO") for index in range(100)],
        [("analytics", "table_100", "id", "bigint", "NO")],
        [("sales", "orders", "id", "bigint", "NO")],
    ]

    discovered = discover_trino_schemas(cursor, _config())

    assert len(discovered) == 102
    assert {(table.schema, table.name) for table in discovered} == {
        *analytics_tables,
        ("sales", "orders"),
    }
    column_calls = cursor.execute.call_args_list[1:]
    assert len(column_calls) == 3
    assert all("table_schema = ?" in call.args[0] for call in column_calls)
    assert all("table_name IN" in call.args[0] for call in column_calls)
    assert all(len(call.args[1]) <= 101 for call in column_calls)


_TRINO_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino"


def _inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    values: dict[str, Any] = {
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
    values.update(overrides)
    return SourceInputs(**values)


class _FakeTrinoCursor:
    def __init__(
        self,
        tables: dict[tuple[str, str], list[tuple[str, str, str]]],
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.tables = tables
        self.rows = list(rows or [])
        self.executed: list[tuple[str, list[Any]]] = []
        self.description: list[tuple[str]] | None = None
        self._result: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        self.executed.append((sql, list(params or [])))
        if "information_schema.columns" in sql:
            schema, table = params or []
            self._result = list(self.tables.get((schema, table), []))
        elif sql.startswith("SELECT COUNT(*)"):
            self._result = [(len(self.rows),)]
        else:
            columns = next(iter(self.tables.values()))
            self.description = [(name,) for name, _, _ in columns]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result[0] if self._result else None

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        page, self.rows = self.rows[:size], self.rows[size:]
        return page

    @property
    def data_queries(self) -> list[tuple[str, list[Any]]]:
        return [(sql, params) for sql, params in self.executed if sql.startswith("SELECT ") and 'FROM "hive".' in sql]


def _run_pipeline(
    config: TrinoSourceConfig, inputs: SourceInputs, cursor: _FakeTrinoCursor
) -> tuple[Any, list[pa.Table]]:
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        patch(f"{_TRINO_MODULE}.connect_trino", side_effect=lambda *args, **kwargs: nullcontext(connection)),
        patch.object(TrinoImplementation, "is_database_host_valid", return_value=(True, None)),
    ):
        response = TrinoImplementation().build_pipeline(config, inputs)
        tables = list(cast(Iterable[pa.Table], response.items()))
    return response, tables


@pytest.mark.parametrize(
    ("config_schema", "schema_name", "schema_metadata", "expected_table", "expected_response_name"),
    [
        (
            None,
            "analytics.events",
            {"source_schema": "analytics", "source_table_name": "events"},
            '"analytics"."events"',
            "analytics_events",
        ),
        (
            None,
            "sales.events",
            {"source_schema": "sales", "source_table_name": "events"},
            '"sales"."events"',
            "sales_events",
        ),
        # A nested Iceberg namespace holds a dot, so only the stored metadata can split the name.
        (
            None,
            "lake.raw.events",
            {"source_schema": "lake.raw", "source_table_name": "events"},
            '"lake.raw"."events"',
            "lake_raw_events",
        ),
        (None, "analytics.events", None, '"analytics"."events"', "analytics_events"),
        ("analytics", "events", None, '"analytics"."events"', "events"),
    ],
)
def test_build_pipeline_reads_each_table_from_its_own_schema(
    config_schema: str | None,
    schema_name: str,
    schema_metadata: dict[str, str] | None,
    expected_table: str,
    expected_response_name: str,
) -> None:
    location = (schema_metadata or {}).get("source_schema") or "analytics"
    cursor = _FakeTrinoCursor({(location, "events"): [("id", "bigint", "NO")]}, rows=[(1,)])

    response, _ = _run_pipeline(
        _config(schema=config_schema), _inputs(schema_name, schema_metadata=schema_metadata), cursor
    )

    assert cursor.data_queries[-1][0] == f'SELECT "id" FROM "hive".{expected_table}'
    assert response.name == expected_response_name
    assert response.primary_keys == ["id"]


@pytest.mark.parametrize(
    ("enabled_columns", "incremental", "expected_sql", "expected_params"),
    [
        (None, None, 'SELECT "id", "we""ird", "dotted.name", "updated_at" FROM "hive"."s"."t"', []),
        (
            ["dotted.name"],
            None,
            'SELECT "dotted.name", "id" FROM "hive"."s"."t"',
            [],
        ),
        (
            ['we"ird'],
            (
                "updated_at",
                IncrementalFieldType.Timestamp,
                dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=ZoneInfo("Europe/Berlin")),
            ),
            'SELECT "we""ird", "id", "updated_at" FROM "hive"."s"."t" WHERE "updated_at" > ? ORDER BY "updated_at" ASC',
            # The column has no time zone, so the UTC watermark is compared as a plain timestamp.
            [dt.datetime(2026, 1, 2, 2, 4, 5)],
        ),
        (
            None,
            ("id", IncrementalFieldType.Integer, 42),
            'SELECT "id", "we""ird", "dotted.name", "updated_at" FROM "hive"."s"."t" WHERE "id" > ? ORDER BY "id" ASC',
            [42],
        ),
    ],
    ids=["full_refresh", "projection_keeps_key", "incremental_watermark_to_utc", "integer"],
)
def test_build_pipeline_query(
    enabled_columns: list[str] | None,
    incremental: tuple[str, IncrementalFieldType, Any] | None,
    expected_sql: str,
    expected_params: list[Any],
) -> None:
    cursor = _FakeTrinoCursor(
        {
            ("s", "t"): [
                ("id", "bigint", "NO"),
                ('we"ird', "varchar", "YES"),
                ("dotted.name", "varchar", "YES"),
                ("updated_at", "timestamp(3)", "YES"),
            ]
        }
    )
    incremental_inputs: dict[str, Any] = {}
    if incremental is not None:
        field, field_type, last_value = incremental
        incremental_inputs = {
            "should_use_incremental_field": True,
            "incremental_field": field,
            "incremental_field_type": field_type,
            "db_incremental_field_last_value": last_value,
        }

    _run_pipeline(_config(schema="s"), _inputs("t", enabled_columns=enabled_columns, **incremental_inputs), cursor)

    assert cursor.data_queries[-1] == (expected_sql, expected_params)


def test_build_pipeline_ignores_the_incremental_field_on_a_full_refresh() -> None:
    cursor = _FakeTrinoCursor({("s", "t"): [("id", "bigint", "NO"), ("updated_at", "timestamp(3)", "YES")]})

    _run_pipeline(
        _config(schema="s"),
        _inputs(
            "t",
            should_use_incremental_field=False,
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value=dt.datetime(2026, 1, 1),
        ),
        cursor,
    )

    assert cursor.data_queries[-1] == ('SELECT "id", "updated_at" FROM "hive"."s"."t"', [])


def test_build_pipeline_quotes_the_catalog() -> None:
    query = build_trino_select(
        catalog='my"catalog',
        schema="s",
        table_name="t",
        columns=[],
        incremental_field=None,
        incremental_field_type=None,
        incremental_last_value=None,
        enabled_columns=None,
        primary_keys=None,
        row_filters=None,
    )

    assert query.sql == 'SELECT * FROM "my""catalog"."s"."t"'


@pytest.mark.parametrize(
    ("column_type", "last_value", "expected"),
    [
        ("timestamp(6) with time zone", dt.datetime(2026, 1, 1, 12), dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC)),
        ("timestamp(6) with time zone", None, dt.datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))),
        ("timestamp(3)", dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC), dt.datetime(2026, 1, 1, 12)),
        ("timestamp(3)", None, dt.datetime(1970, 1, 1)),
    ],
)
def test_incremental_watermark_matches_the_column_time_zone(
    column_type: str, last_value: dt.datetime | None, expected: dt.datetime
) -> None:
    cursor = _FakeTrinoCursor({("s", "t"): [("id", "bigint", "NO"), ("ts", column_type, "YES")]})

    _run_pipeline(
        _config(schema="s"),
        _inputs(
            "t",
            should_use_incremental_field=True,
            incremental_field="ts",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value=last_value,
        ),
        cursor,
    )

    (param,) = cursor.data_queries[-1][1]
    assert param == expected
    assert (param.tzinfo is None) == (expected.tzinfo is None)


def test_build_pipeline_converts_trino_values_to_arrow() -> None:
    columns = [
        ("id", "bigint", "NO"),
        ("amount", "decimal(12,2)", "YES"),
        ("created_at", "timestamp(3)", "YES"),
        ("seen_at", "timestamp(3) with time zone", "YES"),
        ("day", "date", "YES"),
        ("payload", "row(a bigint, b varchar)", "YES"),
        ("tags", "array(row(n bigint))", "YES"),
        ("attrs", "map(varchar, decimal(4,1))", "YES"),
        ("doc", "json", "YES"),
        ("uid", "uuid", "YES"),
        ("local_time", "time(3) with time zone", "YES"),
    ]
    row = (
        7,
        Decimal("12.50"),
        dt.datetime(2026, 3, 1, 8, 30),
        dt.datetime(2026, 3, 1, 8, 30, tzinfo=ZoneInfo("America/New_York")),
        dt.date(2026, 3, 1),
        NamedRowTuple([1, "x"], ["a", "b"], ["bigint", "varchar"]),
        [NamedRowTuple([2], ["n"], ["bigint"])],
        {"k": Decimal("1.5")},
        '{"already": "json"}',
        UUID("12345678-1234-5678-1234-567812345678"),
        dt.time(9, 15, tzinfo=dt.timezone(dt.timedelta(hours=2))),
    )
    cursor = _FakeTrinoCursor({("s", "t"): columns}, rows=[row])

    _, tables = _run_pipeline(_config(schema="s"), _inputs("t"), cursor)

    (table,) = tables
    assert table.schema.field("amount").type == pa.decimal128(12, 2)
    assert table.schema.field("created_at").type == pa.timestamp("us")
    assert table.schema.field("seen_at").type == pa.timestamp("us", tz="UTC")
    assert table.schema.field("day").type == pa.date32()
    assert table.to_pylist() == [
        {
            "id": 7,
            "amount": Decimal("12.50"),
            "created_at": dt.datetime(2026, 3, 1, 8, 30),
            "seen_at": dt.datetime(2026, 3, 1, 13, 30, tzinfo=dt.UTC),
            "day": dt.date(2026, 3, 1),
            "payload": '{"a": 1, "b": "x"}',
            "tags": '[{"n": 2}]',
            "attrs": '{"k": "1.5"}',
            "doc": '{"already": "json"}',
            "uid": "12345678-1234-5678-1234-567812345678",
            "local_time": "09:15:00+02:00",
        }
    ]


def test_build_pipeline_fails_permanently_when_the_table_is_gone() -> None:
    cursor = _FakeTrinoCursor({})

    with pytest.raises(ValueError) as raised:
        _run_pipeline(_config(schema="s"), _inputs("t"), cursor)

    assert error_message_matches(str(raised.value), TrinoSource().get_non_retryable_errors())


def test_build_pipeline_refuses_a_disallowed_host_before_connecting() -> None:
    with (
        patch(f"{_TRINO_MODULE}.connect_trino") as mock_connect,
        patch.object(TrinoImplementation, "is_database_host_valid", return_value=(False, "Host not allowed")),
        pytest.raises(ValueError, match="Host not allowed"),
    ):
        TrinoImplementation().build_pipeline(_config(schema="s"), _inputs("t"))

    mock_connect.assert_not_called()


@pytest.mark.parametrize(
    ("data_type", "expected"),
    [
        ("timestamp(3)", IncrementalFieldType.Timestamp),
        ("timestamp(6) with time zone", IncrementalFieldType.Timestamp),
        ("date", IncrementalFieldType.Date),
        ("bigint", IncrementalFieldType.Integer),
        ("tinyint", IncrementalFieldType.Integer),
        ("decimal(38,0)", IncrementalFieldType.Numeric),
        ("array(timestamp(3))", None),
        ("row(updated_at timestamp(3))", None),
        ("varchar(255)", None),
        ("double", None),
        ("time(3)", None),
    ],
)
def test_filter_trino_incremental_fields(data_type: str, expected: IncrementalFieldType | None) -> None:
    result = filter_trino_incremental_fields([("column", data_type, True)])

    assert result == ([("column", expected, True)] if expected is not None else [])


def test_get_schemas_advertises_incremental_fields_per_table() -> None:
    discovered = [
        DiscoveredTrinoTable(
            catalog="hive",
            schema="analytics",
            name="events",
            columns=(
                TrinoColumn(name="id", data_type="bigint", nullable=False),
                TrinoColumn(name="updated_at", data_type="timestamp(3)", nullable=True),
            ),
        ),
        DiscoveredTrinoTable(
            catalog="hive",
            schema="lake.raw",
            name="events",
            columns=(TrinoColumn(name="name", data_type="varchar", nullable=True),),
        ),
    ]
    source = TrinoSource()

    with (
        patch.object(TrinoSource, "is_database_host_valid", return_value=(True, None)),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.source.connect_trino",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trino.source.discover_trino_schemas",
            return_value=discovered,
        ),
    ):
        schemas = source.get_schemas(_config(), team_id=1)

    by_name = {schema.name: schema for schema in schemas}
    assert set(by_name) == {"analytics.events", "lake.raw.events"}
    assert [field["field"] for field in by_name["analytics.events"].incremental_fields] == ["id", "updated_at"]
    assert by_name["analytics.events"].supports_incremental is True
    assert by_name["analytics.events"].detected_primary_keys == ["id"]
    assert by_name["lake.raw.events"].supports_incremental is False
    assert (by_name["lake.raw.events"].source_schema, by_name["lake.raw.events"].source_table_name) == (
        "lake.raw",
        "events",
    )


def _trino_user_error(name: str, message: str) -> TrinoUserError:
    return TrinoUserError(
        {"message": message, "errorName": name, "errorCode": 1, "errorType": "USER_ERROR", "failureInfo": {}},
        "20260902_120000_00000_abcde",
    )


@pytest.mark.parametrize(
    ("error", "is_permanent"),
    [
        (_trino_user_error("PERMISSION_DENIED", "Access Denied: Cannot select from table hive.s.t"), True),
        (HttpError("error 401: b'Unauthorized'"), True),
        (_trino_user_error("TABLE_NOT_FOUND", "line 1:15: Table 'hive.s.t' does not exist"), True),
        (_trino_user_error("COLUMN_NOT_FOUND", "line 1:8: Column 'gone' cannot be resolved"), True),
        (_trino_external_error("Failed to query OPA backend"), False),
        (TrinoConnectionError("failed to execute: ('Connection aborted.', ConnectionResetError(104))"), False),
    ],
    ids=["access_denied", "unauthorized", "table_not_found", "column_not_found", "opa_unavailable", "connection_reset"],
)
def test_sync_failures_are_classified_for_retry(error: Exception, is_permanent: bool) -> None:
    with pytest.raises(Exception) as raised:
        with trino_failures_as_sync_error():
            raise error

    assert error_message_matches(str(raised.value), TrinoSource().get_non_retryable_errors()) is is_permanent
