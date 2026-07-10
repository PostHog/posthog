import socket
import threading
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock
from unittest.mock import MagicMock, patch

from django.db import (
    OperationalError as DjangoOperationalError,
    connection as django_connection,
)

import psycopg
import pyarrow as pa
import structlog
from parameterized import parameterized
from psycopg import sql

import products.warehouse_sources.backend.temporal.data_imports.sources.postgres.partitioned_tables as partitioned_tables_pkg
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_SCALE,
    MAX_NUMERIC_SCALE,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import (
    ForeignServerUnreachableError,
    PostHogDatabaseConnectionError,
    XminUnsupportedError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.partitioned_tables import (
    WINDOW_MAX_CONNECTION_DROP_RETRIES,
    WINDOW_MAX_QUERY_CANCELED_RETRIES,
    WINDOW_MAX_SERIALIZATION_RETRIES,
    ChildPartition,
    PartitionStrategy,
    build_partition_query,
    derive_upper_bound,
    get_partition_strategy,
    is_supported_incremental_type_for_window,
    iterate_date_windows,
    iterate_partitions,
    list_child_partitions,
    partition_bounds_for_range,
    should_preserve_asc_sort,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _MAX_SETUP_CONNECTION_DROPPED_RETRIES,
    _MAX_SETUP_RECOVERY_CONFLICT_RETRIES,
    _MIN_RECOVERY_CONFLICT_CHUNK_SIZE,
    _SSH_HANDSHAKE_EOF_ERROR,
    FORCE_UTF8_CLIENT_ENCODING,
    METADATA_STATEMENT_TIMEOUT_MS,
    SSL_REQUIRED_AFTER_DATE,
    XMIN_PROJECTED_COLUMN,
    JsonAsStringLoader,
    PostgresDiscoveredSchema,
    PostgresImplementation,
    PostgreSQLColumn,
    RangeAsStringLoader,
    SafeDateLoader,
    SafeTimeLoader,
    SafeTimestampLoader,
    SafeTimestamptzLoader,
    SafeTimetzLoader,
    SSLRequiredError,
    XminBounds,
    _build_count_query,
    _build_query,
    _capture_xmin_ceiling,
    _connect_to_postgres,
    _connect_with_dropped_retry,
    _connect_with_options_fallback,
    _get_estimated_row_count_for_partitioned_table,
    _get_partition_settings,
    _get_partition_settings_for_partitioned_table,
    _get_primary_keys,
    _get_rows_to_sync,
    _get_sslmode,
    _get_table,
    _get_table_chunk_size,
    _has_duplicate_primary_keys,
    _is_connection_dropped_error,
    _is_connection_limit_error,
    _is_dropped_or_connect_timeout,
    _is_invalid_ssl_negotiation_response,
    _is_options_startup_param_unsupported,
    _is_partitioned_table,
    _is_read_replica,
    _is_unsupported_function_error,
    _next_recovery_conflict_chunk_size,
    _normalize_function_names,
    _pk_uniqueness_probe_timeout_error,
    _raise_if_setup_connection_broken,
    _recovery_conflict_abort_error,
    _resolve_hostaddr_with_timeout,
    _rls_active_from_conn,
    _role_subject_to_rls,
    _safe_close_connection,
    _schemas_from_conn,
    _statement_timeout_as_non_retryable,
    _tunnel_with_handshake_translation,
    _xmin_capable_tables_from_conn,
    filter_postgres_incremental_fields,
    get_foreign_keys,
    get_leading_index_columns,
    get_postgres_row_count,
    get_schemas,
    postgres_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestSafeDateLoader:
    @pytest.fixture
    def loader(self):
        return SafeDateLoader(oid=1082)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15", date(2024, 1, 15)),
            (b"1999-12-31", date(1999, 12, 31)),
            (b"0001-01-01", date(1, 1, 1)),
            (b"9999-12-31", date(9999, 12, 31)),
            (b"48113-11-21", date.max),
            (b"10000-01-01", date.max),
            (b"99999-12-31", date.max),
            (b"infinity", date.max),
            (b"-infinity", date.min),
            (b"-0001-01-01", date.min),
            (b"-0044-03-15", date.min),
            (b"0000-01-01", date.min),
            (b"0044-03-15 BC", date.min),
            # duckdb/duckgres render `date` in text mode with a trailing time component; the
            # date portion must survive rather than falling through to a fabricated 9999-12-31.
            (b"2022-04-01 00:00:00", date(2022, 4, 1)),
            (b"2022-04-01T00:00:00", date(2022, 4, 1)),
            (b"2022-04-01 00:00:00+00", date(2022, 4, 1)),
            (b"  2024-01-15  ", date(2024, 1, 15)),
            (None, None),
        ],
    )
    def test_load_dates(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    @pytest.mark.parametrize("input_data", [b"04/01/2022", b"not-a-date", b"20220401"])
    def test_unparseable_dates_raise_instead_of_clamping(self, loader, input_data):
        # A silent clamp to date.max corrupts the whole column with a real-looking date;
        # an unparseable value must surface as a loud sync failure instead.
        with pytest.raises(ValueError):
            loader.load(input_data)


class TestSafeTimestampLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimestampLoader(oid=1114)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15 10:30:00", datetime(2024, 1, 15, 10, 30, 0)),
            (b"2024-01-15 10:30:00.123456", datetime(2024, 1, 15, 10, 30, 0, 123456)),
            (b"0001-01-01 00:00:00", datetime(1, 1, 1, 0, 0, 0)),
            (b"9999-12-31 23:59:59", datetime(9999, 12, 31, 23, 59, 59)),
            (b"200082-12-31 18:30:00", datetime.max),
            (b"20424-11-14 10:30:00", datetime.max),
            (b"10000-01-01 00:00:00", datetime.max),
            (b"infinity", datetime.max),
            (b"-infinity", datetime.min),
            (b"0044-03-15 00:00:00 BC", datetime.min),
            (None, None),
        ],
    )
    def test_load_timestamps(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_clamped_values_are_naive(self, loader):
        assert loader.load(b"200082-12-31 18:30:00").tzinfo is None


class TestSafeTimestamptzLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimestamptzLoader(oid=1184)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15 10:30:00+00", datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)),
            (b"200082-12-31 18:30:00+00", datetime.max.replace(tzinfo=UTC)),
            (b"infinity", datetime.max.replace(tzinfo=UTC)),
            (b"-infinity", datetime.min.replace(tzinfo=UTC)),
            (None, None),
        ],
    )
    def test_load_timestamptz(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_clamped_values_are_utc_aware(self, loader):
        # timestamptz columns map to a UTC-aware Arrow type, so clamps must stay aware
        # to avoid mixing naive and aware datetimes in the same column.
        assert loader.load(b"200082-12-31 18:30:00+00").tzinfo is UTC


class TestSafeTimeLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimeLoader(oid=1083)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            # Postgres allows 24:00:00 (end-of-day) but Python's time caps at 23 — clamp to max.
            (b"24:00:00", time.max),
            (b"24:00:00.000000", time.max),
            # Normal values are parsed unchanged.
            (b"00:00:00", time(0, 0, 0)),
            (b"13:45:30", time(13, 45, 30)),
            (b"13:45:30.123456", time(13, 45, 30, 123456)),
            (b"23:59:59.999999", time(23, 59, 59, 999999)),
        ],
    )
    def test_load_times(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    def test_non_hour_24_errors_still_propagate(self, loader):
        with pytest.raises(psycopg.DataError):
            loader.load(b"99:99:99")


class TestSafeTimetzLoader:
    @pytest.fixture
    def loader(self):
        return SafeTimetzLoader(oid=1266)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"24:00:00+00", time.max.replace(tzinfo=UTC)),
            (b"24:00:00.000000+00", time.max.replace(tzinfo=UTC)),
            (b"24:00:00+05:30", time.max.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            (b"24:00:00-08", time.max.replace(tzinfo=timezone(timedelta(hours=-8)))),
            (b"13:45:30+02", time(13, 45, 30, tzinfo=timezone(timedelta(hours=2)))),
        ],
    )
    def test_load_timetz(self, loader, input_data, expected):
        assert loader.load(input_data) == expected


class TestPostgresImplementationWiring:
    def test_source_exposes_postgres_implementation_singleton(self):
        source = PostgresSource()
        assert isinstance(source.get_implementation, PostgresImplementation)
        # Same instance across two PostgresSource constructions — module-level singleton.
        assert source.get_implementation is PostgresSource().get_implementation

    def test_get_incremental_filter_returns_filter_postgres_incremental_fields(self):
        impl = PostgresSource().get_implementation
        assert impl.get_incremental_filter() is filter_postgres_incremental_fields


class TestPostgresSourceMetadataConnectionErrors:
    def test_posthog_database_connection_failure_stays_retryable(self):
        # `source_for_pipeline` first reads sync metadata from PostHog's own database. A transient
        # connection failure there (e.g. a DNS blip resolving our host) surfaces the same
        # "Name or service not known" wording a customer host misconfig would, so it must be
        # re-raised as PostHogDatabaseConnectionError to avoid being misclassified as non-retryable.
        source = PostgresSource()
        config = MagicMock()
        inputs = MagicMock()

        with (
            patch.object(PostgresSource, "make_ssh_tunnel_func", return_value=None),
            patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema"
            ) as mock_schema_model,
        ):
            mock_schema_model.objects.select_related.return_value.get.side_effect = DjangoOperationalError(
                "[Errno -2] Name or service not known"
            )
            with pytest.raises(PostHogDatabaseConnectionError) as exc_info:
                source.source_for_pipeline(config, inputs)

        non_retryable = source.get_non_retryable_errors()
        error_msg = str(exc_info.value)
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"A PostHog-side DB connection failure must stay retryable: {error_msg}"


class TestPostgresSourceForeignServerConnectionError:
    def test_foreign_server_connection_failure_stays_retryable(self):
        # A setup query touched a postgres_fdw foreign table and the foreign server it points at
        # refused the connection (SQLSTATE 08001). libpq embeds "... Connection refused" verbatim,
        # which would collide with the connect-time "Connection refused" non-retryable rule meant for
        # the direct connection — so a transient foreign-server outage must be re-raised clear of that
        # substring to stay retryable instead of disabling a healthy sync.
        source = PostgresSource()
        schema_model = mock.MagicMock()
        schema_model.is_cdc = False
        schema_model.cdc_mode = None
        schema_model.schema_metadata = {"source_schema": "public", "source_table_name": "orders"}
        schema_model.initial_sync_complete = True

        inputs = mock.MagicMock(
            schema_id="00000000-0000-0000-0000-000000000000",
            schema_name="orders",
            team_id=1,
        )
        config = mock.MagicMock(user="u", password="p", database="db", schema="public")

        fdw_error = psycopg.errors.SqlclientUnableToEstablishSqlconnection(
            'could not connect to server "some_fdw_server"\n'
            'DETAIL:  connection to server at "10.0.0.5", port 5432 failed: Connection refused\n'
            "\tIs the server running on that host and accepting TCP/IP connections?"
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source",
                side_effect=fdw_error,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            with pytest.raises(ForeignServerUnreachableError) as exc_info:
                source.source_for_pipeline(config, inputs)

        error_msg = str(exc_info.value)
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"A foreign-server connection failure must stay retryable: {error_msg}"
        assert "Connection refused" not in error_msg


class TestPostgresSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: MaxClientsInSessionMode: max clients reached',
            # Newer Supabase/Supavisor session-mode pooler wording for the same client-slot
            # exhaustion as "MaxClientsInSessionMode: max clients reached". The pooler has
            # momentarily run out of client slots (pool_size reached); it recovers as connections
            # free up, so a fresh attempt succeeds — must stay retryable.
            'OperationalError: connection failed: connection to server at "44.216.29.125", port 5432 failed: FATAL:  (EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL: too many connections for role "user"',
            # Server-wide max_connections reached. Transient capacity on the customer's DB — a slot
            # frees as soon as another connection closes — so it's retried in-process on connect and
            # must stay out of NonRetryableErrors.
            'OperationalError: connection failed: connection to server at "142.93.153.201", port 25060 failed: FATAL:  sorry, too many clients already',
            # Mid-stream SSL/connection drops during schema discovery — the pooler culled an idle
            # connection or the socket died. A fresh attempt reconnects, so these must stay retryable.
            "consuming input failed: SSL connection has been closed unexpectedly",
            # The socket-level variant of the same TLS drop (network blip / idle cull mid-stream). It
            # triggers the offset-chunking recovery and must stay retryable — only the reconnect wall it
            # can hit on a hot-standby-disabled replica is non-retryable (see the permanent cases below).
            "consuming input failed: SSL SYSCALL error: EOF detected",
            "the connection is lost",
        ],
    )
    def test_transient_connection_errors_are_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            'psycopg2.OperationalError: could not connect to server: Connection refused\n\tIs the server running on host "10.0.0.1" and accepting TCP/IP connections on port 5432?',
            'psycopg2.OperationalError: could not connect to server: No route to host\n\tIs the server running on host "10.0.0.1"?',
            'could not translate host name "bad-hostname.example.com" to address: Name or service not known',
            'FATAL:  password authentication failed for user "myuser"',
            'FATAL: no such database "nonexistent_db"',
            "Name or service not known",
            "OperationalError: [Errno -5] No address associated with hostname",
            "BaseSSHTunnelForwarderError: Could not establish session to SSH gateway",
            # Newer Supabase/Supavisor pooler wording for a missing tenant/user. The older
            # "Tenant or user not found connection to server" / "FATAL: Tenant or user not found"
            # patterns don't substring-match this, so it needs its own key.
            'connection failed: connection to server at "52.45.94.125", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.hksbxxtlcfeyyalgveif not found',
            "ProtocolViolation: server login has been failing, cached error: connect timeout (server_login_retry)",
            "server login has been failing, cached error: connection refused (server_login_retry)",
            # AWS RDS Proxy rejects bad credentials with its own wording (validated against Secrets
            # Manager), not PostgreSQL's "password authentication failed for user". Newlines are
            # normalized to spaces upstream, so the real message arrives as the doubled single line.
            'connection failed: connection to server at "127.0.0.1", port 35425 failed: FATAL:  The password that was provided for the role postgres is wrong. connection to server at "127.0.0.1", port 35425 failed: FATAL:  This RDS Proxy requires TLS connections',
            # A read replica started with `hot_standby = off` refuses every connection (SQLSTATE 57P03).
            # Newlines are normalized to spaces upstream, so the FATAL/DETAIL pair arrives on one line.
            # Permanent until the replica's config changes or it's promoted — must not keep retrying.
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL:  the database system is not accepting connections DETAIL:  Hot standby mode is disabled.',
        ],
    )
    def test_permanent_connection_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)) when require_ssl=False
            # leaves the OperationalError unwrapped. The host/port are volatile; the alert text is stable.
            'connection failed: connection to server at "37.16.27.102", port 6432 failed: SSL error: tlsv1 alert no application protocol',
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: SSL error: tlsv1 alert no application protocol',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'OperationalError: connection failed: connection to server at "37.16.27.102", port 6432 failed: SSL error: tlsv1 alert no application protocol',
        ],
    )
    def test_tls_no_application_protocol_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"TLS ALPN rejection error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "SSHTunnel auth is not valid",
            # Temporal-wrapped form carrying the exception class name.
            "Exception: SSHTunnel auth is not valid",
        ],
    )
    def test_invalid_ssh_tunnel_auth_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        assert "SSHTunnel auth is not valid" in non_retryable
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Invalid SSH tunnel auth error should be non-retryable: {error_msg}"

    def test_invalid_ssh_tunnel_auth_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "SSHTunnel auth is not valid"
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Invalid SSH tunnel auth error should surface an actionable message"
        assert "SSH authentication details" in friendly[0]

    def test_tls_no_application_protocol_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = (
            'connection failed: connection to server at "37.16.27.102", port 6432 failed: '
            "SSL error: tlsv1 alert no application protocol"
        )
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "TLS ALPN rejection error should surface an actionable message"
        assert "host and port" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)). The host/IP, port,
            # and trailing response byte are volatile; the negotiation text is stable.
            'connection failed: connection to server at "66.33.22.254", port 41667 failed: received invalid response to SSL negotiation: I',
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: received invalid response to SSL negotiation: H',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'OperationalError: connection failed: connection to server at "66.33.22.254", port 41667 failed: received invalid response to SSL negotiation: I',
        ],
    )
    def test_invalid_ssl_negotiation_response_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Invalid SSL-negotiation response should be non-retryable: {error_msg}"

    def test_invalid_ssl_negotiation_response_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = (
            'connection failed: connection to server at "66.33.22.254", port 41667 failed: '
            "received invalid response to SSL negotiation: I"
        )
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Invalid SSL-negotiation response should surface an actionable message"
        assert "host and port" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Neon suspends compute when the plan's compute-time quota is exhausted; the handshake
            # fails with this provider message. The host/IP and port are volatile and excluded.
            'connection failed: connection to server at "44.198.216.75", port 5432 failed: ERROR:  Your account or project has exceeded the compute time quota. Upgrade your plan to increase limits.',
            "OperationalError: Your account or project has exceeded the compute time quota. Upgrade your plan to increase limits.",
        ],
    )
    def test_exceeded_compute_time_quota_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Exceeded compute-time quota error should be non-retryable: {error_msg}"

    def test_exceeded_compute_time_quota_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "Your account or project has exceeded the compute time quota. Upgrade your plan to increase limits."
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Exceeded compute-time quota error should surface an actionable message"
        assert "compute-time quota" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)). The leading
            # "pg_readonly:" prefix and trailing docs URL are volatile; "cluster is read-only" is stable.
            "pg_readonly: invalid statement because cluster is read-only. See planetscale.com/docs/postgres/troubleshooting/readonly",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "InternalError_: pg_readonly: invalid statement because cluster is read-only. See planetscale.com/docs/postgres/troubleshooting/readonly",
        ],
    )
    def test_read_only_cluster_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Read-only cluster error should be non-retryable: {error_msg}"

    def test_read_only_cluster_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "pg_readonly: invalid statement because cluster is read-only. See planetscale.com/docs/postgres/troubleshooting/readonly"
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Read-only cluster error should surface an actionable message"
        assert "read-only mode" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)). The request size
            # and memory-context name are volatile; the "out of memory" text is stable.
            'out of memory DETAIL:  Failed on request of size 12 in memory context "MessageContext".',
            'out of memory DETAIL:  Failed on request of size 32816 in memory context "get_actual_variable_range workspace".',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'OutOfMemory: out of memory DETAIL:  Failed on request of size 32816 in memory context "MessageContext".',
        ],
    )
    def test_server_out_of_memory_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Server out-of-memory error should be non-retryable: {error_msg}"

    def test_server_out_of_memory_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = 'out of memory DETAIL:  Failed on request of size 12 in memory context "MessageContext".'
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Server out-of-memory error should surface an actionable message"
        assert "ran out of memory" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            'connection failed: connection to server at "127.0.0.1", port 35425 failed: FATAL:  The password that was provided for the role postgres is wrong.',
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL:  The password that was provided for the role posthog_readonly is wrong.',
        ],
    )
    def test_rds_proxy_wrong_password_is_non_retryable(self, source, error_msg):
        # RDS Proxy's wrong-credentials wording isn't covered by the PostgreSQL "password
        # authentication failed for user" key, so confirm the dedicated role-password key is what
        # recognises it, independent of the volatile role name.
        non_retryable = source.get_non_retryable_errors()
        assert "The password that was provided for the role" in non_retryable
        assert "password authentication failed for user" not in error_msg
        assert any(pattern in error_msg for pattern in non_retryable.keys())

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Supabase's Supavisor transaction pooler (port 6543) rejects bad credentials with
            # "FATAL: SASL authentication failed" rather than PostgreSQL's "password authentication
            # failed for user". When `options` is rejected first, this is the message that propagates
            # via str(e) (the options error is only the chained context). Host/port are volatile.
            'connection failed: connection to server at "52.57.91.216", port 6543 failed: FATAL:  SASL authentication failed connection to server at "52.57.91.216", port 6543 failed: FATAL:  SASL authentication failed',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 6543 failed: FATAL:  SASL authentication failed',
        ],
    )
    def test_sasl_authentication_failed_is_non_retryable(self, source, error_msg):
        # The PostgreSQL "password authentication failed for user" key doesn't substring-match the
        # pooler's SASL wording, so confirm the dedicated key recognises it independent of host/port.
        non_retryable = source.get_non_retryable_errors()
        assert "SASL authentication failed" in non_retryable
        assert "password authentication failed for user" not in error_msg
        assert any(pattern in error_msg for pattern in non_retryable.keys())

    def test_sasl_authentication_failed_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = (
            'connection failed: connection to server at "52.57.91.216", port 6543 failed: '
            "FATAL:  SASL authentication failed"
        )
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "SASL authentication failure should surface an actionable message"
        assert "credentials" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Postgres configured with `pam` auth in pg_hba.conf rejects bad credentials with this
            # wording instead of "password authentication failed for user". Host/port are volatile.
            'connection failed: connection to server at "98.87.250.60", port 5432 failed: FATAL:  PAM authentication failed for user "postgres"',
            'OperationalError: connection failed: connection to server at "10.0.0.1", port 5432 failed: FATAL:  PAM authentication failed for user "myuser"',
        ],
    )
    def test_pam_authentication_failed_is_non_retryable(self, source, error_msg):
        # The PostgreSQL "password authentication failed for user" key doesn't substring-match the
        # PAM wording, so confirm the dedicated key recognises it independent of host/port.
        non_retryable = source.get_non_retryable_errors()
        assert "PAM authentication failed" in non_retryable
        assert "password authentication failed for user" not in error_msg
        assert any(pattern in error_msg for pattern in non_retryable.keys())

    def test_pam_authentication_failed_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = (
            'connection failed: connection to server at "98.87.250.60", port 5432 failed: '
            'FATAL:  PAM authentication failed for user "postgres"'
        )
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "PAM authentication failure should surface an actionable message"
        assert "credentials" in friendly[0]

    def test_supavisor_enotfound_tenant_user_uses_new_key(self, source):
        # The older tenant/user patterns don't cover the newer "(ENOTFOUND) tenant/user" wording,
        # so confirm it's specifically the new key that recognises this message.
        error_msg = (
            'connection failed: connection to server at "52.45.94.125", port 6543 failed: '
            "FATAL:  (ENOTFOUND) tenant/user postgres.hksbxxtlcfeyyalgveif not found"
        )
        non_retryable = source.get_non_retryable_errors()
        assert "(ENOTFOUND) tenant/user" in non_retryable
        assert "Tenant or user not found connection to server" not in error_msg
        assert "FATAL: Tenant or user not found" not in error_msg
        assert any(pattern in error_msg for pattern in non_retryable.keys())

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Supabase Supavisor pooler wording when the tenant/user is gone (project paused/deleted
            # or pooler username changed). The id between "tenant/user" and "not found" is volatile.
            'connection failed: connection to server at "13.238.183.126", port 5432 failed: FATAL:  (ENOTFOUND) tenant/user readonly_user.yvpaylojqoditoupicws not found',
            'connection failed: connection to server at "44.216.29.125", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.xysbwpayipjbkimdauqr not found',
            # The real production message repeats the line (newlines are normalized to spaces upstream).
            'connection failed: connection to server at "13.200.110.68", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.yszohtdqidnoqckysyff not found connection to server at "13.200.110.68", port 6543 failed: FATAL:  (ENOTFOUND) tenant/user postgres.yszohtdqidnoqckysyff not found',
        ],
    )
    def test_missing_pooler_tenant_or_user_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Missing pooler tenant/user error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Supabase Supavisor rejects a connection with no tenant identifier when the pooler
            # username omits the project ref. The host/IP and port are volatile; the message is stable.
            'connection failed: connection to server at "54.255.219.82", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required)',
            # The real production message repeats the line (newlines are normalized to spaces upstream).
            'connection failed: connection to server at "52.74.252.201", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required) connection to server at "52.74.252.201", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required)',
        ],
    )
    def test_missing_pooler_tenant_identifier_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Missing pooler tenant identifier error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Supabase Supavisor rejects a connection with no tenant identifier when the pooler
            # username omits the project ref. The host/IP and port are volatile; the message is stable.
            'connection failed: connection to server at "54.255.219.82", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required)',
            # The real production message repeats the line (newlines are normalized to spaces upstream).
            'connection failed: connection to server at "52.74.252.201", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required) connection to server at "52.74.252.201", port 5432 failed: FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required)',
        ],
    )
    def test_missing_pooler_tenant_identifier_returns_friendly_message(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Missing pooler tenant identifier error should surface an actionable message"
        assert "project ref" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
        ],
    )
    def test_unrepresentable_decimal_values_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unrepresentable decimal error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' has values that no longer fit",
        ],
    )
    def test_widened_integer_column_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Widened integer column error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            'invalid input syntax for type integer: "1.5"',
            'InvalidTextRepresentation: invalid input syntax for type integer: "1.5"',
        ],
    )
    def test_non_integer_incremental_cursor_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Non-integer incremental cursor error should be non-retryable: {error_msg}"

    def test_exhausted_recovery_conflict_retries_are_non_retryable(self, source):
        error_msg = str(_recovery_conflict_abort_error(10))
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Exhausted recovery-conflict abort should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw activity-level message (what `_handle_import_error` sees via str(e)) — no class name.
            # Raised by get_rows when a recovery conflict forces offset chunking and a chunk then hits
            # the 10-minute statement timeout.
            "Reading from your read replica timed out: Postgres canceled the initial read with a "
            "recovery conflict, and the chunked fallback read still couldn't finish within the 10 "
            "minute statement timeout. Increase max_standby_streaming_delay or enable "
            "hot_standby_feedback on the replica, or sync from the primary database instead.",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "QueryTimeoutException: Reading from your read replica timed out: Postgres canceled the "
            "initial read with a recovery conflict",
        ],
    )
    def test_read_replica_timeout_query_timeout_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Read-replica timeout error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)) — no class name.
            "permission denied for table brand",
            "permission denied for view posthog_areas",
            "permission denied for materialized view posthog_notifications",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "InsufficientPrivilege: permission denied for table brand",
        ],
    )
    def test_permission_denied_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permission-denied error should be non-retryable: {error_msg}"

    def test_permission_denied_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "permission denied for table brand"
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Permission-denied error should surface an actionable message"
        assert "SELECT" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)).
            "permission denied for function crypto_aead_det_decrypt",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "InsufficientPrivilege: permission denied for function crypto_aead_det_decrypt",
        ],
    )
    def test_permission_denied_for_function_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permission-denied-for-function error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "permission denied for function crypto_aead_det_decrypt",
            "InsufficientPrivilege: permission denied for function crypto_aead_det_decrypt",
        ],
    )
    def test_permission_denied_for_function_returns_execute_message(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Permission-denied-for-function error should surface an actionable message"
        # The function-permission message must win over the generic table-SELECT message and advise
        # EXECUTE rather than the misleading "GRANT SELECT ON <table>".
        assert "EXECUTE" in friendly[0]
        assert "GRANT SELECT" not in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)).
            "permission denied for schema extensions",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "InsufficientPrivilege: permission denied for schema extensions",
        ],
    )
    def test_permission_denied_for_schema_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permission-denied-for-schema error should be non-retryable: {error_msg}"

    def test_permission_denied_for_schema_returns_usage_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = "permission denied for schema extensions"
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Permission-denied-for-schema error should surface an actionable message"
        # The schema-USAGE message must win over the generic table-SELECT message and advise USAGE
        # rather than the misleading "GRANT SELECT ON <table>".
        assert "USAGE" in friendly[0]
        assert "GRANT SELECT" not in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)).
            'materialized view "mv_dayplan_blocks" has not been populated\nHINT:  Use the REFRESH MATERIALIZED VIEW command.',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'ObjectNotInPrerequisiteState: materialized view "mv_dayplan_blocks" has not been populated',
        ],
    )
    def test_unpopulated_materialized_view_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unpopulated materialized view error should be non-retryable: {error_msg}"

    def test_unpopulated_materialized_view_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = 'materialized view "mv_dayplan_blocks" has not been populated'
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Unpopulated materialized view error should surface an actionable message"
        assert "REFRESH MATERIALIZED VIEW" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            "cannot call jsonb_each on a non-object",
            "InvalidParameterValue: cannot call jsonb_each on a non-object",
            "cannot call jsonb_each_text on a non-object",
            "InvalidParameterValue: cannot call jsonb_each_text on a non-object",
        ],
    )
    def test_jsonb_each_on_non_object_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"jsonb_each on non-object error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw psycopg message (what the activity-level check sees via str(e)).
            'user mapping not found for user "svc_role", server "remote_server"',
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            'UndefinedObject: user mapping not found for user "svc_role", server "remote_server"',
        ],
    )
    def test_missing_fdw_user_mapping_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Missing FDW user mapping error should be non-retryable: {error_msg}"

    def test_missing_fdw_user_mapping_returns_friendly_message(self, source):
        non_retryable = source.get_non_retryable_errors()
        error_msg = 'user mapping not found for user "svc_role", server "remote_server"'
        friendly = [reason for pattern, reason in non_retryable.items() if pattern in error_msg and reason]
        assert friendly, "Missing FDW user mapping error should surface an actionable message"
        assert "CREATE USER MAPPING" in friendly[0]

    @pytest.mark.parametrize(
        "error_msg",
        [
            # A single recovery conflict is retried in-process; on its own it must stay retryable.
            "canceling statement due to conflict with recovery",
            "could not serialize access due to conflict with recovery",
            # The connection-terminating variant is retried by the setup phase the same way.
            "terminating connection due to conflict with recovery",
            # The connection-error abort is a separate, genuinely transient condition.
            "Hit 10 successive connection errors. Aborting.",
        ],
    )
    def test_recovery_conflict_related_transients_stay_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should remain retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw activity-level message (what `_handle_import_error` sees via str(e)) — no class name.
            # The standard incremental-read path (postgres.py) and the partitioned-table window path
            # word the guidance slightly differently but share the "appropriate index" fragment.
            "10 min timeout statement reached. Please ensure your incremental field (updated_at) has an appropriate index created",
            "window 2024-01-01..2024-02-01 hit statement_timeout after 5 retries. Please ensure updated_at has an appropriate index.",
            # Temporal-wrapped message (what the workflow-level check sees) — carries the class name.
            "QueryTimeoutException: 10 min timeout statement reached. Please ensure your incremental field (updated_at) has an appropriate index created",
        ],
    )
    def test_statement_timeout_query_timeout_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Statement-timeout error should be non-retryable: {error_msg}"

    def test_statement_timeout_raw_message_matches_index_fragment_not_class_name(self, source):
        # The raw activity-level message doesn't carry the class name, so the "QueryTimeoutException"
        # key can't catch it there — confirm the dedicated message fragment is what recognises it.
        error_msg = str(
            _statement_timeout_as_non_retryable(
                psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
                should_use_incremental_field=True,
                incremental_field="updated_at",
            )
        )
        non_retryable = source.get_non_retryable_errors()
        matching_keys = [pattern for pattern in non_retryable if pattern in error_msg]
        # The class-name key can't catch the raw message (str(e) carries no class name); the
        # dedicated message fragment is what recognises it at the activity layer.
        assert "QueryTimeoutException" not in matching_keys
        assert "has an appropriate index" in matching_keys

    def test_pk_uniqueness_probe_timeout_is_non_retryable_and_points_at_primary_key(self, source):
        # A statement_timeout in the fallback `id` uniqueness probe used to surface the generic
        # "index your incremental field" message, which won't fix this full-table GROUP BY. The
        # message must point at the assumed primary key while staying non-retryable at the raw
        # activity-level layer (where str(e) carries no class name).
        error_msg = str(_pk_uniqueness_probe_timeout_error())
        assert "primary key" in error_msg
        assert "incremental field" not in error_msg
        non_retryable = source.get_non_retryable_errors()
        matching_keys = [pattern for pattern in non_retryable if pattern in error_msg]
        assert "has an appropriate index" in matching_keys

    def test_ssh_handshake_eof_is_non_retryable(self, source):
        # `_tunnel_with_handshake_translation` turns paramiko's bare, empty-message handshake
        # EOFError into this stable message; without the entry it would match no rule and retry forever.
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in _SSH_HANDSHAKE_EOF_ERROR for pattern in non_retryable.keys())
        assert is_non_retryable, f"SSH handshake EOF should be non-retryable: {_SSH_HANDSHAKE_EOF_ERROR}"


def _raise_eof() -> None:
    # Indirection so the `yield` below stays reachable under mypy's warn_unreachable — at runtime
    # this raises before the generator yields, standing in for paramiko's handshake EOFError.
    raise EOFError()


@contextmanager
def _handshake_eof_tunnel() -> Iterator[tuple[str, int]]:
    _raise_eof()
    yield ("127.0.0.1", 5432)


@contextmanager
def _body_eof_tunnel() -> Iterator[tuple[str, int]]:
    yield ("127.0.0.1", 5432)


class TestTunnelWithHandshakeTranslation:
    def test_bare_handshake_eof_is_translated_with_cause(self):
        # The translated message (verified non-retryable in `test_ssh_handshake_eof_is_non_retryable`)
        # replaces the bare EOFError while preserving it as the cause.
        with pytest.raises(Exception, match=_SSH_HANDSHAKE_EOF_ERROR) as exc_info:
            with _tunnel_with_handshake_translation(_handshake_eof_tunnel):
                pass

        assert isinstance(exc_info.value.__cause__, EOFError)

    def test_body_eof_is_not_translated(self):
        # A failure raised by the body (not the handshake) must surface as the original EOFError,
        # never the translated handshake message — guards the `yield`-outside-`except` invariant.
        with pytest.raises(EOFError):
            with _tunnel_with_handshake_translation(_body_eof_tunnel):
                raise EOFError()


class TestPostgresSourceSetupRecoveryConflictRetry:
    @staticmethod
    @contextmanager
    def _tunnel():
        yield ("localhost", 5432)

    def _make_failing_connection(self, error: BaseException) -> mock.MagicMock:
        cursor = mock.MagicMock()
        cursor.execute.side_effect = error
        cursor_cm = mock.MagicMock()
        cursor_cm.__enter__.return_value = cursor
        cursor_cm.__exit__.return_value = False
        connection = mock.MagicMock()
        connection.closed = False
        connection.cursor.return_value = cursor_cm
        connection.__enter__.return_value = connection
        # Must return falsy so the raised error propagates out of the `with` block.
        connection.__exit__.return_value = False
        return connection

    def _call_postgres_source(self):
        return postgres_source(
            tunnel=self._tunnel,
            user="u",
            password="p",
            database="db",
            sslmode="prefer",
            schema="public",
            table_names=["t"],
            should_use_incremental_field=False,
            logger=structlog.get_logger(),
            db_incremental_field_last_value=None,
        )

    @pytest.mark.parametrize(
        "err",
        [
            # A hot-standby recovery conflict surfaces as either SerializationFailure (the
            # transaction was aborted) or QueryCanceled (the statement was canceled, e.g. a replica
            # reconnect) — the same transient condition. Both must be retried in-process during setup
            # and end in the non-retryable abort once sustained; before the QueryCanceled fix that
            # flavor escaped on the first probe and failed the whole activity.
            psycopg.errors.SerializationFailure("terminating connection due to conflict with recovery"),
            psycopg.errors.QueryCanceled(
                "canceling statement due to conflict with recovery\n"
                "DETAIL:  User query might have conflicted with replica reconnect."
            ),
        ],
    )
    def test_sustained_recovery_conflict_during_setup_aborts_non_retryably(self, err):
        connection = self._make_failing_connection(err)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(Exception) as exc_info:
                    self._call_postgres_source()

        message = str(exc_info.value)
        assert "conflict with recovery" in message and "max_standby_streaming_delay" in message
        non_retryable = PostgresSource().get_non_retryable_errors()
        assert any(pattern in message for pattern in non_retryable.keys())
        # Each retry reconnects, so connect is called once per attempt.
        assert connect_mock.call_count == _MAX_SETUP_RECOVERY_CONFLICT_RETRIES

    @pytest.mark.parametrize(
        "err",
        [
            # The in-process retry is scoped strictly to "conflict with recovery": a serialization
            # failure from a concurrent update, and a QueryCanceled from a statement_timeout, are
            # both unrelated to standby recovery and must propagate on the first probe.
            psycopg.errors.SerializationFailure("could not serialize access due to concurrent update"),
            psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
        ],
    )
    def test_non_recovery_conflict_during_setup_is_not_retried(self, err):
        connection = self._make_failing_connection(err)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with pytest.raises(type(err)):
                self._call_postgres_source()

        assert connect_mock.call_count == 1

    def test_connection_dropped_while_opening_setup_connection_is_retried(self):
        # A transient drop while opening the setup connection ("server closed the connection
        # unexpectedly") is the same class of error the read path already recovers from. The setup
        # connect must retry in-process with bounded backoff instead of failing on the first drop.
        err = psycopg.OperationalError(
            'connection failed: connection to server at "3.151.121.165", port 5432 failed: '
            "server closed the connection unexpectedly"
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=err,
        ) as connect_mock:
            with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.OperationalError):
                    self._call_postgres_source()

        # `_connect_with_dropped_retry` defaults to 5 attempts; before the fix the drop escaped on
        # the first connect (call_count == 1).
        assert connect_mock.call_count == 5

    def test_permanent_error_while_opening_setup_connection_is_not_retried(self):
        # A permanent connect failure (bad password) must not be retried by the dropped-connection
        # handler — it should propagate on the first attempt.
        err = psycopg.OperationalError(
            'connection to server at "10.0.0.1" failed: FATAL: password authentication failed for user "u"'
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=err,
        ) as connect_mock:
            with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.OperationalError):
                    self._call_postgres_source()

        assert connect_mock.call_count == 1

    def test_sustained_connection_drop_during_setup_probes_is_retried_then_reraised(self):
        # A transient drop hit *during* the metadata probes — here Supavisor's pooler "DbHandler
        # exited" (XX000 InternalError_) raised by `_get_table` — must reconnect and retry the
        # probes in-process, not escape on the first failure. Once the drop is sustained the
        # original error re-raises (Temporal then retries the whole activity).
        err = psycopg.errors.InternalError_("(EDBHANDLEREXITED) DbHandler exited. Check logs for more information")
        connection = self._make_failing_connection(err)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.errors.InternalError_):
                    self._call_postgres_source()

        # Each retry reconnects, so connect is called once per attempt before giving up.
        assert connect_mock.call_count == _MAX_SETUP_CONNECTION_DROPPED_RETRIES

    def test_non_dropped_internal_error_during_setup_probes_is_not_retried(self):
        # A genuine XX000 internal error that isn't the pooler drop is not a connection drop, so it
        # must propagate on the first probe instead of being retried by the dropped-connection handler.
        err = psycopg.errors.InternalError_("XX000: internal error: something went wrong")
        connection = self._make_failing_connection(err)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            return_value=connection,
        ) as connect_mock:
            with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
                with pytest.raises(psycopg.errors.InternalError_):
                    self._call_postgres_source()

        assert connect_mock.call_count == 1


class TestIsConnectionDroppedError:
    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.ProtocolViolation("server conn crashed?"),
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.OperationalError("connection to server was lost"),
            psycopg.OperationalError("connection to server was closed unexpectedly"),
            psycopg.OperationalError("consuming input failed: EOF detected"),
            # libpq's bare SSL drop, exactly as it reaches the discovery/setup connect — no
            # "consuming input failed" prefix. A transient TLS close (pooler/firewall idle cull,
            # failover) the in-process reconnect must catch, not the permanent no-SSL-support case.
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "SSL connection has been closed unexpectedly"
            ),
            # libpq's lower-level form of the same TLS drop — a socket-level EOF/reset during the
            # SSL handshake or read. Transient (pooler/firewall idle cull, failover, network blip),
            # not the permanent no-SSL-support case, so the in-process reconnect must catch it.
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "SSL SYSCALL error: EOF detected"
            ),
            psycopg.OperationalError("terminating connection due to administrator command"),
            # psycopg's message when libpq finds the socket already gone (raised from
            # PGconn.socket inside the commit at the end of get_connection). A transient
            # dead-socket drop the in-process recovery must catch — without this the
            # reconnect retry gives up and the offset-chunking fallback never triggers.
            psycopg.OperationalError("the connection is lost"),
            psycopg.errors.ProtocolViolation("SERVER CONN CRASHED?"),
            # SQLSTATE 25P03: the source's idle_in_transaction_session_timeout culled our
            # backend mid-stream. psycopg maps this to InternalError, not OperationalError,
            # so it's detected by type alone — even with no message to match on.
            psycopg.errors.IdleInTransactionSessionTimeout("terminating connection due to idle-in-transaction timeout"),
            psycopg.errors.IdleInTransactionSessionTimeout(),
            # Supavisor (Supabase's connection pooler) tears down a session whose backend connection
            # died and surfaces it as a generic XX000 InternalError_ — a transient drop, not a libpq
            # signature, so it's matched on the pooler's own "(EDBHANDLEREXITED)" code. The trailing
            # message wording varies for the same condition, so every observed variant must match.
            psycopg.errors.InternalError_("(EDBHANDLEREXITED) DbHandler exited. Check logs for more information"),
            psycopg.errors.InternalError_("(EDBHANDLEREXITED) DBHANDLER EXITED. Check logs for more information"),
            psycopg.errors.InternalError_(
                "(EDBHANDLEREXITED) connection to database closed. Check logs for more information"
            ),
            # Supavisor also surfaces a transient pool-checkout failure as an XX000 InternalError_
            # carrying the "(ECHECKOUTRETRIES)" code — it couldn't hand us a backend connection after
            # retrying internally. Same transient pooler class as EDBHANDLEREXITED; recovers on
            # reconnect once a session returns a connection to the pool.
            psycopg.errors.InternalError_("(ECHECKOUTRETRIES) failed to check out a connection after multiple retries"),
            # Transaction-mode sibling of ECHECKOUTRETRIES: Supavisor couldn't check out a backend
            # from the pool before its checkout timeout elapsed. Same transient pooler-saturation
            # class, also an XX000 InternalError_, matched on the "(ECHECKOUTTIMEOUT)" code.
            psycopg.errors.InternalError_(
                "(ECHECKOUTTIMEOUT) unable to check out connection from the pool after 60000ms in Transaction mode"
            ),
            # Supavisor loses the backend socket mid-session (idle cull, restart, failover) and, once
            # the client is past auth, surfaces it as an XX000 InternalError_ "Internal error
            # (authenticated): :closed" — ":closed" being the Erlang gen_tcp peer-closed reason. No
            # error code, so it's matched on the full phrase including the ":closed" reason; same
            # transient class as the pooler drops above and recovers on reconnect.
            psycopg.errors.InternalError_("Internal error (authenticated): :closed"),
            # Supavisor reports a transient timeout reaching the upstream backend as a
            # ConnectionFailure (08006, an OperationalError) carrying the Erlang-tuple reason
            # "{:error, :etimedout}" — a transient drop the in-process recovery must catch.
            psycopg.errors.ConnectionFailure("Failed to connect to database: {:error, :etimedout}"),
            # The connection-refused sibling: Supavisor's TCP connect to its upstream backend is
            # refused while the backend is briefly down, carrying "{:error, :econnrefused}". Same
            # transient class as :etimedout — the in-process recovery reconnect must catch it rather
            # than letting it escape and fail the whole sync.
            psycopg.errors.ConnectionFailure(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "FATAL:  Failed to connect to database: {:error, :econnrefused}"
            ),
            # Neon's proxy reports a compute that didn't wake from scale-to-zero before the auth
            # deadline as a ConnectionFailure — a transient drop the in-process recovery must catch.
            psycopg.errors.ConnectionFailure(
                "Failed to connect to database: authentication did not complete within 15000ms"
            ),
        ],
    )
    def test_connection_dropped_errors_are_detected(self, error):
        assert _is_connection_dropped_error(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.SerializationFailure("could not serialize access due to conflict with recovery"),
            psycopg.errors.QueryCanceled("statement timeout"),
            psycopg.OperationalError("password authentication failed for user"),
            # Initial-connect failures embed "connection to server …" but are
            # permanent — they must not be misclassified as a recoverable drop.
            psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            ),
            psycopg.errors.UniqueViolation("duplicate key value violates unique constraint"),
            ValueError("server conn crashed?"),
            Exception("server conn crashed?"),
            # A genuine XX000 internal error that isn't the Supavisor pooler drop must stay
            # non-recoverable — the InternalError_ match is scoped to the known pooler codes
            # ("(EDBHANDLEREXITED)" / "(ECHECKOUTRETRIES)"), not every XX000.
            psycopg.errors.InternalError_("XX000: internal error: something went wrong"),
            # The Supavisor authenticated-state match is scoped to the ":closed" socket-drop reason.
            # Any other "Internal error (authenticated): ..." reason could be a permanent pooler or
            # protocol failure that must surface immediately, so it must NOT be treated as a drop.
            psycopg.errors.InternalError_("Internal error (authenticated): :protocol_error"),
            # libpq's bare English "Connection refused" is a permanent wrong-host/port
            # misconfiguration (non-retryable in source.py) and must NOT be confused with Supavisor's
            # transient Erlang-tuple "{:error, :econnrefused}" — broadening the match to a plain
            # "refused" substring would wrongly retry it.
            psycopg.OperationalError('connection to server at "10.0.0.1", port 5432 failed: Connection refused'),
        ],
    )
    def test_unrelated_errors_are_not_detected(self, error):
        assert _is_connection_dropped_error(error) is False

    def test_connect_timeout_is_not_a_mid_stream_drop(self):
        # A connect-time timeout is not a mid-stream drop, so the discovery/validation path
        # (which uses `_is_connection_dropped_error`) keeps failing fast on it.
        assert _is_connection_dropped_error(psycopg.errors.ConnectionTimeout("connection timeout expired")) is False


class TestDroppedOrConnectTimeout:
    @pytest.mark.parametrize(
        "error",
        [
            # Every mid-stream drop the base predicate already recognises stays recognised.
            psycopg.OperationalError("consuming input failed: SSL connection has been closed unexpectedly"),
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.errors.ProtocolViolation("server conn crashed?"),
            # The new case: the read-path reconnect that bootstraps offset-chunking recovery times
            # out establishing the socket. Transient — the source was reachable moments earlier.
            psycopg.errors.ConnectionTimeout("connection timeout expired"),
        ],
    )
    def test_transient_connect_path_errors_are_retryable(self, error):
        assert _is_dropped_or_connect_timeout(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            ),
            # A statement timeout is not a connect timeout — it must not be absorbed here.
            psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
        ],
    )
    def test_permanent_and_non_connect_errors_are_not_retryable(self, error):
        assert _is_dropped_or_connect_timeout(error) is False


class TestIsConnectionLimitError:
    @pytest.mark.parametrize(
        "error",
        [
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "FATAL:  sorry, too many clients already"
            ),
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute"
            ),
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                'FATAL:  too many connections for role "reader"'
            ),
            # Supabase's Supavisor session-mode pooler refuses a new connection once every client
            # slot is in use. A plain OperationalError (not the XX000 pooler-drop class), so it must
            # be recognised here for the in-process connect retry to recover from it.
            psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "FATAL:  (EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15"
            ),
            # A pooler (PgBouncer-style) that caches an upstream login failure reveals the limit on
            # the first query as a ProtocolViolation, not an OperationalError — it must still be
            # recognised so the discovery retry recovers instead of surfacing it as captured noise.
            psycopg.errors.ProtocolViolation(
                "server login has been failing, cached error: remaining connection slots are "
                "reserved for roles with the SUPERUSER attribute (server_login_retry)"
            ),
        ],
    )
    def test_connection_limit_errors_are_detected(self, error):
        assert _is_connection_limit_error(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            # A connection that was established then dropped is a different class — not a limit.
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            ),
            psycopg.errors.QueryCanceled("statement timeout"),
            ValueError("sorry, too many clients already"),
        ],
    )
    def test_unrelated_errors_are_not_detected(self, error):
        assert _is_connection_limit_error(error) is False


class TestRaiseIfSetupConnectionBroken:
    """A connection dropped mid-discovery must surface as a retryable error, not the masked
    `ProgrammingError: Explicit commit() forbidden within a Transaction context` that psycopg's
    implicit `with connection:` exit-commit raises when a savepoint teardown leaks the
    transaction-nesting counter on a no-longer-OK connection."""

    def test_broken_connection_raises_retryable_dropped_error(self):
        connection = mock.MagicMock()
        connection.broken = True

        with pytest.raises(psycopg.OperationalError) as exc_info:
            _raise_if_setup_connection_broken(cast(Any, connection))

        # Classified as a transient drop, so the activity keeps retrying...
        assert _is_connection_dropped_error(exc_info.value) is True
        # ...and the message is not matched by any NonRetryableErrors substring.
        message = str(exc_info.value)
        assert not any(key in message for key in PostgresSource().get_non_retryable_errors())

    def test_healthy_connection_is_a_noop(self):
        connection = mock.MagicMock()
        connection.broken = False

        # A healthy connection must not raise.
        _raise_if_setup_connection_broken(cast(Any, connection))


class TestConnectWithDroppedRetry:
    @pytest.fixture
    def logger(self):
        return structlog.get_logger()

    def test_retries_dropped_connection_then_succeeds(self, logger):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The exact error surfaced in production: a mid-stream SSL EOF on
                # the reconnect that bootstraps offset-chunking recovery.
                psycopg.OperationalError("consuming input failed: SSL SYSCALL error: EOF detected"),
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            result = _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert result is good_conn
        assert connect.call_count == 3

    def test_retries_connect_timeout_then_succeeds(self, logger):
        # The exact production sequence: a mid-stream SSL drop routes into offset-chunking recovery,
        # and the reconnect that bootstraps it times out establishing the socket before succeeding.
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                psycopg.errors.ConnectionTimeout("connection timeout expired"),
                good_conn,
            ]
        )

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            result = _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert result is good_conn
        assert connect.call_count == 2

    def test_retries_connection_limit_error_then_succeeds(self, logger):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The source is momentarily at its connection limit; slots free up by a
                # later attempt, so the reconnect succeeds rather than failing the whole sync.
                # Two consecutive refusals lock in that the loop keeps retrying past one attempt.
                psycopg.OperationalError(
                    'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                    "FATAL:  sorry, too many clients already"
                ),
                psycopg.OperationalError(
                    'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                    "FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute"
                ),
                good_conn,
            ]
        )

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            result = _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert result is good_conn
        assert connect.call_count == 3

    def test_permanent_error_is_not_retried(self, logger):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_dropped_retry(connect, logger, max_attempts=5)

        assert connect.call_count == 1

    def test_gives_up_after_max_attempts(self, logger):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError("consuming input failed: SSL SYSCALL error: EOF detected")
        )

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_dropped_retry(connect, logger, max_attempts=3)

        assert connect.call_count == 3


class TestNextRecoveryConflictChunkSize:
    @pytest.mark.parametrize(
        "chunk_size,successive_errors,expected",
        [
            # Grace period — don't shrink on a one-off blip.
            (20_000, 1, 20_000),
            (20_000, 4, 20_000),
            # Sustained conflict → reduce.
            (20_000, 5, int(20_000 / 1.5)),
            # Never drops below the floor.
            (120, 5, _MIN_RECOVERY_CONFLICT_CHUNK_SIZE),
            (_MIN_RECOVERY_CONFLICT_CHUNK_SIZE, 5, _MIN_RECOVERY_CONFLICT_CHUNK_SIZE),
        ],
    )
    def test_chunk_size_reduction(self, chunk_size, successive_errors, expected):
        assert _next_recovery_conflict_chunk_size(chunk_size, successive_errors) == expected

    def test_converges_to_floor(self):
        chunk_size = 20_000
        for _ in range(50):
            chunk_size = _next_recovery_conflict_chunk_size(chunk_size, 5)
        assert chunk_size == _MIN_RECOVERY_CONFLICT_CHUNK_SIZE


class TestRecoveryConflictAbortError:
    def test_message_is_actionable(self):
        message = str(_recovery_conflict_abort_error(10))
        assert "conflict with recovery" in message
        assert "max_standby_streaming_delay" in message
        assert "hot_standby_feedback" in message

    def test_message_is_non_retryable(self):
        message = str(_recovery_conflict_abort_error(10))
        non_retryable = PostgresSource().get_non_retryable_errors()
        assert any(pattern in message for pattern in non_retryable.keys())


# Redshift (and other Postgres-wire engines) report `client_encoding` as the legacy alias
# `UNICODE`, which psycopg3 can't decode — it raises `NotSupportedError: codec not available in
# Python: 'UNICODE'`. We pin the client encoding to UTF8 on connect to avoid the crash.
class TestConnectForcesUtf8ClientEncoding:
    def test_connect_pins_client_encoding_to_utf8(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect"
        ) as connect_mock:
            _connect_to_postgres(
                host="redshift-cluster.example.com",
                port=5439,
                database="dev",
                user="user",
                password="password",
            )

        assert connect_mock.call_args.kwargs["options"] == FORCE_UTF8_CLIENT_ENCODING

    def test_caller_supplied_options_are_appended_after_utf8(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect"
        ) as connect_mock:
            _connect_to_postgres(
                host="db.example.com",
                port=5432,
                database="postgres",
                user="user",
                password="password",
                options="-c statement_timeout=5000",
            )

        assert connect_mock.call_args.kwargs["options"] == f"{FORCE_UTF8_CLIENT_ENCODING} -c statement_timeout=5000"


# psycopg3 resolves hostnames Python-side (`socket.getaddrinfo`) before libpq's `connect_timeout`
# applies, so a stalled resolver hangs the threaded sync activity until Temporal's
# `start_to_close_timeout` cancels it, surfacing a misleading `CancelledError`. We bound the lookup
# and hand psycopg the address via `hostaddr`.
class TestResolveHostaddrWithTimeout:
    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",  # already an IP (also the SSH-tunnel local endpoint) — nothing to resolve
            "::1",
            "[::1]",  # bracketed IPv6 literal — exercises the host.strip("[]") path in _is_ip_literal
            "/var/run/postgresql",  # Unix-socket path
            "",
        ],
    )
    def test_hosts_that_need_no_lookup_short_circuit(self, host):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.socket.getaddrinfo"
        ) as getaddrinfo_mock:
            assert _resolve_hostaddr_with_timeout(host, 5432, 15) is None
        getaddrinfo_mock.assert_not_called()

    def test_resolved_hostname_returns_first_address(self):
        addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 5432)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.6", 5432)),
        ]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.socket.getaddrinfo",
            return_value=addrinfo,
        ):
            assert _resolve_hostaddr_with_timeout("db.example.com", 5432, 15) == "10.0.0.5"

    def test_genuine_resolution_failure_falls_through(self):
        # A host that doesn't resolve must return None (not raise) so psycopg connects as before and
        # its own "Name or service not known" error still reaches the non-retryable classifier.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.socket.getaddrinfo",
            side_effect=socket.gaierror(-2, "Name or service not known"),
        ):
            assert _resolve_hostaddr_with_timeout("does-not-exist.example.com", 5432, 15) is None

    def test_stalled_resolver_raises_fast_retryable_error(self):
        release = threading.Event()
        try:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.socket.getaddrinfo",
                side_effect=lambda *a, **k: release.wait(),
            ):
                with pytest.raises(psycopg.OperationalError) as exc_info:
                    _resolve_hostaddr_with_timeout("db.example.com", 5432, 0.1)
        finally:
            release.set()  # let the orphaned lookup thread exit

        message = str(exc_info.value)
        assert "Timed out resolving database host name" in message
        # Must stay retryable: it must not carry any of the non-retryable resolution fragments.
        assert "could not translate host name" not in message
        assert "Name or service not known" not in message


# Transaction-mode poolers (Supabase Supavisor on :6543, PgBouncer transaction mode, AWS RDS Proxy)
# reject the libpq `options` startup parameter we send to pin client_encoding=UTF8. When they do, we
# drop `options` and retry rather than failing the connection.
class TestConnectOptionsStartupParamFallback:
    @pytest.mark.parametrize(
        "message,expected",
        [
            (
                'connection to server at "1.2.3.4", port 6543 failed: FATAL:  unsupported startup parameter: options',
                True,
            ),
            (
                "connection failed: FATAL:  Feature not supported: RDS Proxy currently "
                "doesn’t support command-line options.",
                True,
            ),
            ("password authentication failed for user", False),
            ("server closed the connection unexpectedly", False),
        ],
    )
    def test_detects_options_unsupported_message(self, message, expected):
        assert _is_options_startup_param_unsupported(psycopg.OperationalError(message)) is expected

    def test_non_operational_error_is_not_matched(self):
        assert _is_options_startup_param_unsupported(ValueError("unsupported startup parameter: options")) is False

    def test_retries_without_options_when_pooler_rejects_it(self):
        good_conn = mock.MagicMock()
        connect_mock = mock.MagicMock(
            side_effect=[
                psycopg.OperationalError("FATAL:  unsupported startup parameter: options"),
                good_conn,
            ]
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            result = _connect_with_options_fallback(host="db", options=FORCE_UTF8_CLIENT_ENCODING)

        assert result is good_conn
        assert connect_mock.call_count == 2
        # First attempt carries options, retry drops it entirely.
        assert connect_mock.call_args_list[0].kwargs["options"] == FORCE_UTF8_CLIENT_ENCODING
        assert "options" not in connect_mock.call_args_list[1].kwargs

    def test_does_not_retry_when_no_options_were_sent(self):
        connect_mock = mock.MagicMock(
            side_effect=psycopg.OperationalError("FATAL:  unsupported startup parameter: options")
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_options_fallback(host="db")

        assert connect_mock.call_count == 1

    def test_unrelated_operational_error_is_not_retried(self):
        connect_mock = mock.MagicMock(side_effect=psycopg.OperationalError("password authentication failed for user"))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(psycopg.OperationalError):
                _connect_with_options_fallback(host="db", options=FORCE_UTF8_CLIENT_ENCODING)

        assert connect_mock.call_count == 1

    def test_retry_failure_is_not_chained_to_options_error(self):
        # When the options-less retry fails for a real reason (wrong password), that error must not
        # carry the recovered "options unsupported" error as its context — the chained context
        # otherwise surfaces in error tracking and masks the genuine, already-classified cause.
        connect_mock = mock.MagicMock(
            side_effect=[
                psycopg.OperationalError(
                    "FATAL:  Feature not supported: RDS Proxy currently doesn’t support command-line options."
                ),
                psycopg.OperationalError("FATAL:  The password that was provided for the role postgres is wrong."),
            ]
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(psycopg.OperationalError) as exc_info:
                _connect_with_options_fallback(host="db", options=FORCE_UTF8_CLIENT_ENCODING)

        assert connect_mock.call_count == 2
        assert "The password that was provided for the role" in str(exc_info.value)
        assert exc_info.value.__context__ is None


class TestInvalidSSLNegotiationResponse:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("received invalid response to SSL negotiation: I", True),
            (
                'connection to server at "1.2.3.4", port 41667 failed: received invalid response to SSL negotiation: I',
                True,
            ),
            ("server does not support SSL, but SSL was required", False),
            ("SSL error: tlsv1 alert no application protocol", False),
            ("password authentication failed for user", False),
        ],
    )
    def test_detects_invalid_ssl_negotiation_message(self, message, expected):
        assert _is_invalid_ssl_negotiation_response(psycopg.OperationalError(message)) is expected

    def test_invalid_negotiation_is_not_wrapped_as_ssl_required(self):
        # require_ssl=True, but the message is a wrong-port/non-Postgres signal — it must surface
        # raw (so get_non_retryable_errors can give an accurate message), not as the misleading
        # SSLRequiredError "enable SSL on your server".
        connect_mock = mock.MagicMock(
            side_effect=psycopg.OperationalError("received invalid response to SSL negotiation: I")
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(psycopg.OperationalError) as exc_info:
                _connect_to_postgres(
                    host="db", port=41667, database="railway", user="postgres", password="x", require_ssl=True
                )
        assert not isinstance(exc_info.value, SSLRequiredError)
        assert "received invalid response to SSL negotiation" in str(exc_info.value)

    def test_genuine_unsupported_ssl_still_raises_ssl_required(self):
        connect_mock = mock.MagicMock(
            side_effect=psycopg.OperationalError("server does not support SSL, but SSL was required")
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(SSLRequiredError):
                _connect_to_postgres(
                    host="db", port=5432, database="db", user="postgres", password="x", require_ssl=True
                )

    @pytest.mark.parametrize(
        "message",
        [
            "SSL connection has been closed unexpectedly",
            "SSL SYSCALL error: EOF detected",
        ],
    )
    def test_transient_ssl_drop_is_not_wrapped_as_ssl_required(self, message):
        # require_ssl=True, but the message is a transient TLS drop (pooler/firewall idle cull,
        # failover, network blip) — it must surface raw so the connect-retry / Temporal can treat
        # it as retryable, not as the non-retryable SSLRequiredError, which would permanently stop
        # the sync with a misleading "enable SSL on your server" message.
        connect_mock = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                f'connection failed: connection to server at "10.0.0.1", port 5432 failed: {message}'
            )
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            connect_mock,
        ):
            with pytest.raises(psycopg.OperationalError) as exc_info:
                _connect_to_postgres(
                    host="db", port=5432, database="db", user="postgres", password="x", require_ssl=True
                )
        assert not isinstance(exc_info.value, SSLRequiredError)


class TestStatementTimeoutAsNonRetryable:
    @pytest.mark.parametrize(
        "should_use_incremental_field,incremental_field,expected_substr",
        [
            # Incremental syncs map the timeout to a non-retryable QueryTimeoutException.
            (True, "updated_at", "updated_at"),
            # Full-table syncs must re-raise the raw QueryCanceled so a fresh re-sync can
            # reorder rows; we only short-circuit incremental reads.
            (False, None, None),
        ],
    )
    def test_statement_timeout_mapping(self, should_use_incremental_field, incremental_field, expected_substr):
        result = _statement_timeout_as_non_retryable(
            psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
        )
        if expected_substr is None:
            assert result is None
        else:
            assert isinstance(result, QueryTimeoutException)
            assert expected_substr in str(result)

    @pytest.mark.parametrize(
        "error",
        [
            psycopg.errors.ProtocolViolation("server conn crashed?"),
            psycopg.OperationalError("server closed the connection unexpectedly"),
            psycopg.errors.SerializationFailure("due to conflict with recovery"),
            Exception("canceling statement due to statement timeout"),
        ],
    )
    def test_non_statement_timeout_errors_are_not_mapped(self, error):
        assert (
            _statement_timeout_as_non_retryable(
                error,
                should_use_incremental_field=True,
                incremental_field="updated_at",
            )
            is None
        )


class TestServerCursorStatementTimeout:
    """The main server-cursor streaming path in `get_rows` must not leak a raw,
    retryable QueryCanceled when a FETCH hits the statement_timeout — it must map
    to a non-retryable QueryTimeoutException for incremental syncs (mirroring the
    offset-chunking and windowed paths), and re-raise the raw error for full-table
    syncs so a fresh re-sync can reorder rows safely.
    """

    class _Cursor:
        def __init__(self, raise_on_fetch: bool):
            self._raise_on_fetch = raise_on_fetch
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            return None

        def fetchmany(self, _n: int):
            if self._raise_on_fetch:
                raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self):
            self.autocommit = False
            self.closed = False
            # Real psycopg connections expose `broken`; the setup path probes it via
            # `_raise_if_setup_connection_broken`, so the fake must carry it too.
            self.broken = False
            self.adapters = mock.Mock()

        def cursor(self, *args, **kwargs):
            # A named cursor (`name=...`) is the streaming server cursor that must
            # raise the timeout; the unnamed setup cursor stays benign.
            return TestServerCursorStatementTimeout._Cursor(raise_on_fetch="name" in kwargs)

        def commit(self):
            return None

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _run(self, *, should_use_incremental_field: bool):
        from contextlib import contextmanager

        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", return_value=self._Connection()),
            patch(f"{module}.psycopg.Cursor", return_value=self._Cursor(raise_on_fetch=False)),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=False),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=100),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=should_use_incremental_field,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=datetime(2026, 6, 15, tzinfo=UTC)
                if should_use_incremental_field
                else None,
                team_id=1,
                incremental_field="updated_at" if should_use_incremental_field else None,
                incremental_field_type=IncrementalFieldType.Timestamp if should_use_incremental_field else None,
            )
            list(cast(Iterable[Any], response.items()))

    @pytest.mark.parametrize(
        "should_use_incremental_field,expected_exception,expected_substr",
        [
            # Incremental syncs map the FETCH timeout to a non-retryable QueryTimeoutException.
            (True, QueryTimeoutException, "updated_at"),
            # Full-table syncs have no stable ORDER BY, so we re-raise the raw QueryCanceled
            # to let a fresh re-sync reorder rows rather than giving up.
            (False, psycopg.errors.QueryCanceled, None),
        ],
    )
    def test_statement_timeout_handling(self, should_use_incremental_field, expected_exception, expected_substr):
        with pytest.raises(expected_exception) as exc_info:
            self._run(should_use_incremental_field=should_use_incremental_field)
        if expected_substr is not None:
            assert expected_substr in str(exc_info.value)


class TestServerCursorCloseStatementTimeout:
    """Closing the `get_rows` generator (the sync finished, or the activity was cancelled) tears
    down the open server cursor; that teardown round-trip can itself hit the statement_timeout and
    raise QueryCanceled. It must be swallowed so close() completes cleanly — re-raising it (or
    mapping it to a non-retryable QueryTimeoutException) masks the real outcome and floods error
    tracking with phantom statement timeouts.
    """

    class _Cursor:
        def __init__(self, *, named: bool):
            self._named = named
            self._yielded = False
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            return None

        def fetchmany(self, _n: int):
            # Yield one chunk once so the generator suspends at the yield inside the
            # `with cursor` block, then report end-of-rows on the next call.
            if self._yielded:
                return []
            self._yielded = True
            return [(1,)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            # Only the named server cursor's close round-trip trips the timeout, and
            # only while the generator is being closed (GeneratorExit unwinding).
            if self._named and any(isinstance(a, GeneratorExit) for a in args):
                raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
            return False

    class _Connection:
        def __init__(self):
            self.autocommit = False
            self.closed = False
            self.broken = False
            self.adapters = mock.Mock()

        def cursor(self, *args, **kwargs):
            return TestServerCursorCloseStatementTimeout._Cursor(named="name" in kwargs)

        def commit(self):
            return None

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _open(self, *, should_use_incremental_field: bool) -> tuple[Generator[Any], Any]:
        from contextlib import contextmanager

        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        connection = self._Connection()
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", return_value=connection),
            patch(f"{module}.psycopg.Cursor", return_value=self._Cursor(named=False)),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=False),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=100),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=should_use_incremental_field,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=datetime(2026, 6, 15, tzinfo=UTC)
                if should_use_incremental_field
                else None,
                team_id=1,
                incremental_field="updated_at" if should_use_incremental_field else None,
                incremental_field_type=IncrementalFieldType.Timestamp if should_use_incremental_field else None,
            )
            gen = cast(Generator[Any], response.items())
            next(gen)  # one chunk; generator now suspended at the yield inside `with cursor`
            return gen, connection

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    def test_close_swallows_statement_timeout(self, should_use_incremental_field):
        gen, connection = self._open(should_use_incremental_field=should_use_incremental_field)
        # close() must not raise — neither the raw QueryCanceled nor a converted
        # QueryTimeoutException should escape teardown.
        gen.close()
        assert connection.closed


class TestOffsetChunkingConnectRecoveryConflict:
    """A recovery conflict raised by the connect itself in the offset-chunking fallback — a hot
    standby cancelling the new connection's startup with "conflict with recovery" — must be retried
    in-process, not escape `get_rows`. It surfaces as a SerializationFailure when the standby cancels
    a chunk read, but as a plain OperationalError ("connection failed: ... conflict with recovery")
    when it cancels the connection's own startup — the latter bypassed the loop's SerializationFailure
    handler and failed the whole sync.
    """

    _RECOVERY_CONFLICT = "canceling statement due to conflict with recovery"
    # psycopg wraps a startup-time cancel as a plain OperationalError with no SQLSTATE-mapped subclass.
    _CONNECT_RECOVERY_CONFLICT = (
        'connection failed: connection to server at "localhost", port 5432 failed: '
        "FATAL:  canceling statement due to conflict with recovery"
    )

    class _NamedCursor:
        def __init__(self):
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            # The initial server-cursor read on a read replica hits the recovery conflict, which
            # routes get_rows into the offset-chunking fallback.
            raise psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery")

        def fetchmany(self, _n):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _OffsetCursor:
        # Unnamed client cursor used by the offset-chunking path; yields no rows so the loop ends.
        def __init__(self):
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            return None

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self):
            self.autocommit = False
            self.closed = False
            self.broken = False
            self.adapters = mock.Mock()

        def cursor(self, *args, **kwargs):
            if "name" in kwargs:
                return TestOffsetChunkingConnectRecoveryConflict._NamedCursor()
            # Unnamed setup cursor (metadata probes are patched out) stays benign.
            return mock.MagicMock()

        def commit(self):
            return None

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    @pytest.mark.parametrize(
        "connect_error",
        [
            psycopg.errors.SerializationFailure(_RECOVERY_CONFLICT),
            psycopg.OperationalError(_CONNECT_RECOVERY_CONFLICT),
        ],
    )
    def test_recovery_conflict_on_offset_chunking_connect_is_retried_in_process(self, connect_error):
        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        connection = self._Connection()
        connect_calls = {"n": 0}

        def connect_side_effect(*args, **kwargs):
            connect_calls["n"] += 1
            # Calls 1 (setup) and 2 (initial server-cursor read) succeed; the offset-chunking
            # bootstrap connect hits the recovery conflict twice before succeeding.
            if connect_calls["n"] in (3, 4):
                raise connect_error
            return connection

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", side_effect=connect_side_effect) as connect_mock,
            patch(f"{module}.psycopg.Cursor", side_effect=lambda _conn: self._OffsetCursor()),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=True),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=1000),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
            patch(f"{module}.time.sleep"),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=False,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=None,
                team_id=1,
            )
            # Before the fix the connect-time conflict escaped offset_chunking and raised here.
            list(cast(Iterable[Any], response.items()))

        # 1 setup + 1 initial read + 3 offset-chunking connects (2 conflicts + 1 success).
        assert connect_mock.call_count == 5


class TestOffsetChunkingConnectTimeout:
    """The reconnect that bootstraps offset-chunking recovery can time out establishing the socket
    (`ConnectionTimeout: connection timeout expired`). That's transient — the source was reachable
    moments earlier — so it must be retried in-process, not escape `get_rows` and get misclassified
    as the non-retryable "connection timeout expired" by `get_non_retryable_errors`.
    """

    def test_connect_timeout_on_offset_chunking_connect_is_retried_in_process(self):
        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        # Reuse the connect-conflict scaffolding: the named server cursor raises a recovery conflict
        # to route get_rows into offset-chunking; the unnamed cursor then yields no rows.
        connection = TestOffsetChunkingConnectRecoveryConflict._Connection()
        connect_calls = {"n": 0}

        def connect_side_effect(*args, **kwargs):
            connect_calls["n"] += 1
            # Calls 1 (setup) and 2 (initial server-cursor read) succeed; the offset-chunking
            # bootstrap connect times out twice before succeeding.
            if connect_calls["n"] in (3, 4):
                raise psycopg.errors.ConnectionTimeout("connection timeout expired")
            return connection

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", side_effect=connect_side_effect) as connect_mock,
            patch(
                f"{module}.psycopg.Cursor",
                side_effect=lambda _conn: TestOffsetChunkingConnectRecoveryConflict._OffsetCursor(),
            ),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=True),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=1000),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
            patch(f"{module}.time.sleep"),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=False,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=None,
                team_id=1,
            )
            # Before the fix the connect-time timeout escaped offset_chunking and raised here.
            list(cast(Iterable[Any], response.items()))

        # 1 setup + 1 initial read + 3 offset-chunking connects (2 timeouts + 1 success).
        assert connect_mock.call_count == 5


class TestOffsetChunkingRecoveryConflictTimeout:
    """When a read replica cancels the initial read with a recovery conflict, `get_rows` falls
    back to offset chunking. If a chunk then exhausts the 10-min statement_timeout, a full-table
    sync used to re-raise the raw, retryable QueryCanceled — so Temporal re-read from the start
    into the same conflicting, overloaded replica every attempt. The fallback must instead surface
    a non-retryable QueryTimeoutException with actionable replica guidance.
    """

    class _NamedCursor:
        def __init__(self):
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            raise psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery")

        def fetchmany(self, _n):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _OffsetCursor:
        def __init__(self):
            col = mock.Mock()
            col.name = "id"
            self.description = [col]

        def execute(self, *args, **kwargs):
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self):
            self.autocommit = False
            self.closed = False
            self.broken = False
            self.adapters = mock.Mock()

        def cursor(self, *args, **kwargs):
            if "name" in kwargs:
                return TestOffsetChunkingRecoveryConflictTimeout._NamedCursor()
            return mock.MagicMock()

        def commit(self):
            return None

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_statement_timeout_in_recovery_conflict_fallback_is_non_retryable(self):
        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", return_value=self._Connection()),
            patch(f"{module}.psycopg.Cursor", side_effect=lambda _conn: self._OffsetCursor()),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=True),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=1000),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
            patch(f"{module}.time.sleep"),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=False,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=None,
                team_id=1,
            )
            with pytest.raises(QueryTimeoutException) as exc_info:
                list(cast(Iterable[Any], response.items()))

        message = str(exc_info.value)
        assert "max_standby_streaming_delay" in message
        # Unlike a raw QueryCanceled, QueryTimeoutException is classified non-retryable. It's matched
        # by class name in the Temporal-wrapped error string (see external_data_job.py), so the
        # non-retryable signal here is the type name, not the message text.
        non_retryable = PostgresSource().get_non_retryable_errors()
        assert type(exc_info.value).__name__ in non_retryable


class TestSafeCloseConnection:
    def test_none_is_a_noop(self):
        # The offset-chunking path can reach a teardown handler with no connection (a connect that
        # raised before assigning), so closing None must not raise.
        _safe_close_connection(None)

    def test_already_closed_is_a_noop(self):
        connection = mock.Mock()
        connection.closed = True
        _safe_close_connection(connection)
        connection.close.assert_not_called()

    def test_open_connection_is_closed(self):
        connection = mock.Mock()
        connection.closed = False
        _safe_close_connection(connection)
        connection.close.assert_called_once()


class TestPostgresSourceForPipelineSchemaResolution:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    def _make_inputs(self, schema_name: str):
        return mock.MagicMock(
            schema_id="00000000-0000-0000-0000-000000000000",
            schema_name=schema_name,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            team_id=1,
            logger=mock.MagicMock(),
        )

    def _make_config(self, schema: str | None = None):
        return mock.MagicMock(
            user="u",
            password="p",
            database="db",
            schema=schema,
        )

    def _make_schema_model(
        self,
        name: str,
        schema_metadata: dict | None = None,
        source_model=None,
        sync_type_config: dict | None = None,
        s3_folder_name: str | None = None,
    ):
        schema = mock.MagicMock()
        schema.name = name
        schema.id = "00000000-0000-0000-0000-000000000000"
        schema.is_cdc = False
        schema.cdc_mode = None
        schema.initial_sync_complete = True
        schema.enabled_columns = None
        schema.chunk_size_override = None
        schema.schema_metadata = schema_metadata
        schema.sync_type_config = sync_type_config or {}
        schema.s3_folder_name = s3_folder_name
        # MagicMock auto-attrs are truthy; pin the property to what the real model would resolve
        # (resolution itself is covered by warehouse_sources test_models).
        schema.resolved_s3_folder_name = s3_folder_name
        schema.source = source_model or mock.MagicMock()
        return schema

    def test_dotted_schema_name_without_metadata_routes_to_correct_source_schema(self, source):
        # Repro: row created before this PR has name="poblic.example_table" and no schema_metadata.
        # source_for_pipeline must not fall through to config.schema or "public" — that produces
        # `SELECT FROM "public"."poblic.example_table"`, an undefined relation.
        schema_model = self._make_schema_model("poblic.example_table", schema_metadata=None)
        inputs = self._make_inputs("poblic.example_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source"
            ) as postgres_source_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)

            assert postgres_source_mock.called, "postgres_source was not invoked"
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "poblic", f"expected schema='poblic', got {kwargs['schema']!r}"
            assert kwargs["table_names"] == ["example_table"], (
                f"expected table_names=['example_table'], got {kwargs['table_names']!r}"
            )

    def test_schema_metadata_wins_over_dotted_name_inference(self, source):
        # Metadata is the source of truth — explicit pin always beats name-splitting.
        schema_model = self._make_schema_model(
            "weird.name",
            schema_metadata={"source_schema": "real_schema", "source_table_name": "real_table"},
        )
        inputs = self._make_inputs("weird.name")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source"
            ) as postgres_source_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "real_schema"
            assert kwargs["table_names"] == ["real_table"]

    def test_s3_folder_name_drives_response_name_so_delta_writes_to_legacy_path(self, source):
        # After `consolidate_postgres_legacy_rows` renames `example_table` → `public.example_table`,
        # the row carries `s3_folder_name="example_table"`. `validate_schema_and_update_table` uses
        # that key for `url_pattern`, so `SourceResponse.name` MUST also derive from the storage key
        # — otherwise Delta files land at `.../public__example_table/` while `DataWarehouseTable.url_pattern`
        # points at `.../example_table/` and HogQL reads from an empty location.
        from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

        schema_model = self._make_schema_model(
            "public.example_table",
            schema_metadata={"source_schema": "public", "source_table_name": "example_table"},
            s3_folder_name="example_table",
        )
        inputs = self._make_inputs("public.example_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source"
            ) as postgres_source_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            response = mock.MagicMock()
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = response

            source.source_for_pipeline(config, inputs)

            assert response.name == NamingConvention.normalize_identifier("example_table"), (
                f"response.name must derive from s3_folder_name to keep Delta writes anchored to the "
                f"legacy folder; got {response.name!r}"
            )

    def test_response_name_uses_schema_name_when_no_storage_key(self, source):
        # New (non-migrated) rows have no s3_folder_name — response.name falls back to the row's
        # current name so the Delta path matches `url_pattern` (also derived from the row's name).
        from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

        schema_model = self._make_schema_model(
            "poblic.new_table",
            schema_metadata={"source_schema": "poblic", "source_table_name": "new_table"},
            sync_type_config={},
        )
        inputs = self._make_inputs("poblic.new_table")
        config = self._make_config(schema=None)

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source"
            ) as postgres_source_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            response = mock.MagicMock()
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = response

            source.source_for_pipeline(config, inputs)

            assert response.name == NamingConvention.normalize_identifier("poblic.new_table")

    def test_unqualified_name_falls_back_to_config_schema(self, source):
        # Legacy row "example_table" with no metadata + config.schema="public" → ("public", "example_table").
        schema_model = self._make_schema_model("example_table", schema_metadata=None)
        inputs = self._make_inputs("example_table")
        config = self._make_config(schema="public")

        with (
            mock.patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects"
            ) as objects_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.postgres_source"
            ) as postgres_source_mock,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.source_requires_ssl",
                return_value=False,
            ),
            mock.patch.object(source, "make_ssh_tunnel_func", return_value=lambda: None),
        ):
            objects_mock.select_related.return_value.get.return_value = schema_model
            postgres_source_mock.return_value = mock.MagicMock()

            source.source_for_pipeline(config, inputs)
            kwargs = postgres_source_mock.call_args.kwargs
            assert kwargs["schema"] == "public"
            assert kwargs["table_names"] == ["example_table"]

    def test_validate_credentials_for_access_method_allows_blank_schema_for_warehouse_imports(self, source):
        # Multi-schema parity: warehouse mode now accepts blank `schema` (browse-all) just like
        # direct mode. Each `ExternalDataSchema` row pins its own `(schema, table)` in metadata.
        config = source.parse_config(
            {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "",
            }
        )

        with mock.patch.object(source, "validate_credentials", return_value=(True, None)) as validate_credentials:
            valid, error = source.validate_credentials_for_access_method(config, team_id=1, access_method="warehouse")

        assert valid is True
        assert error is None
        validate_credentials.assert_called_once_with(config, 1, schema_name=None)

    def test_validate_credentials_for_access_method_allows_blank_schema_for_direct_queries(self, source):
        config = source.parse_config(
            {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "",
            }
        )

        with mock.patch.object(source, "validate_credentials", return_value=(True, None)) as validate_credentials:
            valid, error = source.validate_credentials_for_access_method(config, team_id=1, access_method="direct")

        assert valid is True
        assert error is None
        validate_credentials.assert_called_once_with(config, 1, schema_name=None)


class TestValidateCredentialsErrorMapping:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    @pytest.fixture
    def config(self, source):
        return source.parse_config(
            {
                "host": "db.example.com",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            }
        )

    @pytest.mark.parametrize(
        "error_msg, expected",
        [
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "error received from server in SCRAM exchange: Wrong password",
                "Invalid user or password",
            ),
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "FATAL:  the database system is starting up",
                "Your database is starting up or recovering. Wait a moment and try again.",
            ),
            (
                'connection failed: connection to server at "1.2.3.4", port 5432 failed: '
                "server does not support SSL, but SSL was required",
                "SSL/TLS connection is required but your database does not support it. "
                "Please enable SSL/TLS on your PostgreSQL server.",
            ),
            (
                "consuming input failed: SSL connection has been closed unexpectedly",
                "The SSL/TLS connection to your database was closed unexpectedly. "
                "Check your database's SSL configuration and that the port is correct.",
            ),
            (
                'connection failed: connection to server at "127.0.0.1", port 43185 failed: '
                "server closed the connection unexpectedly\n\tThis probably means the server terminated abnormally\n"
                "\tbefore or while processing the request.",
                "Your database closed the connection unexpectedly while connecting. This usually means the host "
                "or port is wrong, the server requires SSL/TLS, or a connection pooler, firewall, or SSH tunnel "
                "dropped the connection. Check your host, port, and SSL settings.",
            ),
            # Supabase/Supavisor session-mode pooler with no free client slots. The pool_size number
            # is volatile, so the match is on the stable "max clients reached in session mode" phrase.
            (
                'connection failed: connection to server at "52.45.94.125", port 5432 failed: '
                "FATAL:  (EMAXCONNSESSION) max clients reached in session mode - max clients are "
                "limited to pool_size: 15",
                "Your database's connection pooler has no free client connections (\"max clients "
                "reached in session mode\"). Raise the pooler's client limit (for example increase "
                "pool_size, or switch it to transaction mode) or reduce the number of concurrent "
                "connections to your database, then try again.",
            ),
            # Supabase/Supavisor pooler reports a missing tenant/user with a volatile username/host.
            (
                'connection failed: connection to server at "44.216.29.125", port 5432 failed: '
                "FATAL:  (ENOTFOUND) tenant/user postgres.icjrfprdtrgjpxfpbrvx not found",
                "Your database connection pooler couldn't find the tenant or user. This usually means the "
                "database project is paused or deleted, or the pooler username/host is wrong. Check that "
                "your database is active and the connection details are correct.",
            ),
            # Supabase's transaction pooler (port 6543) rejects bad credentials during the
            # SASL/SCRAM exchange rather than with libpq's "password authentication failed".
            (
                'connection failed: connection to server at "10.0.0.1", port 6543 failed: '
                "FATAL:  SASL authentication failed",
                'Your database rejected the credentials during authentication ("SASL '
                'authentication failed"). This usually means the username or password is wrong. '
                "Some connection poolers (for example Supabase's transaction pooler) also require a "
                "pooler-specific username such as postgres.<project-ref>. Check your credentials "
                "and try again.",
            ),
            # Supabase/Supavisor's shared pooler rejects a connection whose username carries no
            # project ref with "(ENOIDENTIFIER) no tenant identifier provided".
            (
                'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
                "FATAL:  (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname required)",
                "Your connection pooler couldn't identify your project (\"no tenant identifier "
                'provided"). On the shared pooler host the username must include your project ref '
                '(for example "postgres.<project-ref>"). Update the username to the pooler username '
                "shown in your Supabase dashboard and try again.",
            ),
            # Invalid SSL-negotiation response — the host/port isn't a Postgres server speaking SSL.
            (
                'connection failed: connection to server at "66.33.22.254", port 41667 failed: '
                "received invalid response to SSL negotiation: I",
                "PostHog reached the host and port you configured, but the server didn't respond like a "
                "PostgreSQL server speaking SSL. Check that the host and port point at your PostgreSQL server "
                "(not an HTTP, proxy, or edge endpoint) and that the database is running.",
            ),
            # DNS-resolution failure surfaced as the raw socket wording (no libpq "could not
            # translate host name" prefix) — e.g. through an SSH tunnel or psycopg's Python-side
            # resolution. Must map to the actionable host message instead of being captured.
            (
                "[Errno -2] Name or service not known",
                "Could not resolve the database host. Check that the host is spelled correctly and reachable from the public internet.",
            ),
            (
                "[Errno -5] No address associated with hostname",
                "Could not resolve the database host. Check that the host is spelled correctly and reachable from the public internet.",
            ),
            # Unmapped errors fall back to the generic message.
            (
                "some brand new failure",
                "Could not connect to Postgres. Please check all connection details are valid.",
            ),
        ],
    )
    def test_operational_errors_map_to_friendly_messages(self, source, config, error_msg, expected):
        with (
            mock.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None)),
            mock.patch.object(source, "is_database_host_valid", return_value=(True, None)),
            mock.patch.object(source, "get_schemas", side_effect=psycopg.OperationalError(error_msg)),
        ):
            valid, error = source.validate_credentials(config, team_id=1)

        assert valid is False
        assert error == expected

    @pytest.mark.parametrize(
        "host",
        [
            "https://db.example.com/",
            "postgres://user:secret@db.example.com:5432/mydb",
        ],
    )
    def test_url_in_host_field_rejected_without_echoing_input(self, source, host):
        config = source.parse_config(
            {
                "host": host,
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            }
        )
        with (
            mock.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None)),
            mock.patch.object(source, "is_database_host_valid", side_effect=AssertionError("should not resolve")),
            mock.patch.object(source, "get_schemas", side_effect=AssertionError("should not connect")),
        ):
            valid, error = source.validate_credentials(config, team_id=1)

        assert valid is False
        # The raw host may embed credentials, so it must never be reflected back.
        assert host not in (error or "")
        assert "hostname" in (error or "")


class TestPostgresSchemaDiscovery:
    def _mock_connection(self, *fetchall_results: list[tuple[object, ...]]):
        cursor = mock.MagicMock()
        cursor.fetchall.side_effect = list(fetchall_results)
        cursor.fetchone.return_value = ("PostgreSQL 15.0",)

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None

        connection = mock.MagicMock()
        connection.cursor.return_value = cursor_context
        return connection

    @pytest.mark.parametrize("n_drops", [1, 2, 3])
    def test_get_schemas_retries_repeated_pooler_drops_during_discovery_query(self, n_drops: int):
        # `n_drops` successive Supavisor pooler drops on the first discovery query
        # ("(EDBHANDLEREXITED) DbHandler exited", XX000 InternalError_), then a healthy connection.
        # Each drop must reconnect and rerun the whole connect-and-discover cycle on a fresh
        # connection, recovering once the pooler stops dropping the upstream backend — so connect is
        # called once per dropped attempt plus once for the successful one.
        dropping_connections = [
            self._drop_on_execute_connection(
                psycopg.errors.InternalError_("(EDBHANDLEREXITED) DbHandler exited. Check logs for more information")
            )
            for _ in range(n_drops)
        ]
        good_connection = self._mock_connection(
            [("public", "users")],
            [("public", "users", "id", "integer", "NO", 1)],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[*dropping_connections, good_connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                schemas = get_schemas(
                    host="localhost",
                    port=5432,
                    database="postgres",
                    user="postgres",
                    password="postgres",
                    schema="",
                )

        assert connect_mock.call_count == n_drops + 1
        assert set(schemas.keys()) == {"public.users"}
        for dropped in dropping_connections:
            dropped.close.assert_called_once()
        good_connection.close.assert_called_once()

    def test_get_schemas_reraises_after_exhausting_retries_on_sustained_discovery_drop(self):
        # When every attempt hits the pooler drop on the discovery query, discovery exhausts its
        # bounded in-process retries and re-raises the original error for Temporal to retry the whole
        # activity — it does not loop forever. With _MAX_SETUP_CONNECTION_DROPPED_RETRIES attempts,
        # connect is called once per attempt and each connection is closed before the next reconnect.
        dropping_connections = [
            self._drop_on_execute_connection(
                psycopg.errors.InternalError_("(EDBHANDLEREXITED) DbHandler exited. Check logs for more information")
            )
            for _ in range(_MAX_SETUP_CONNECTION_DROPPED_RETRIES)
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=dropping_connections,
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                with pytest.raises(psycopg.errors.InternalError_):
                    get_schemas(
                        host="localhost",
                        port=5432,
                        database="postgres",
                        user="postgres",
                        password="postgres",
                        schema="",
                    )

        assert connect_mock.call_count == _MAX_SETUP_CONNECTION_DROPPED_RETRIES
        for dropped in dropping_connections:
            dropped.close.assert_called_once()

    @pytest.mark.parametrize(
        "drop_message",
        [
            "server closed the connection unexpectedly",
            # The SSL-flavoured sibling, exactly as it reached discovery in production. Before the
            # fix it wasn't in `_CONNECTION_DROPPED_ERROR_SUBSTRINGS`, so the retry didn't catch it
            # and the first blip surfaced as captured error-tracking noise.
            "SSL connection has been closed unexpectedly",
        ],
    )
    def test_get_schemas_retries_transient_connection_drop_on_connect(self, drop_message):
        # A transient drop on the discovery connect is the same class of error the import read path
        # already recovers from. Discovery must retry the connect in-process and recover instead of
        # failing the whole run — and surfacing as captured error-tracking noise — on the first blip.
        drop = psycopg.OperationalError(
            f'connection failed: connection to server at "66.33.22.246", port 11212 failed: {drop_message}'
        )
        connection = self._mock_connection(
            [("public", "users")],
            [("public", "users", "id", "integer", "NO", 1)],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[drop, connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                schemas = get_schemas(
                    host="localhost",
                    port=5432,
                    database="postgres",
                    user="postgres",
                    password="postgres",
                    schema="",
                )

        # First connect dropped, second succeeded — before the fix the drop escaped on the first
        # connect (call_count == 1) and failed the discovery activity.
        assert connect_mock.call_count == 2
        assert set(schemas.keys()) == {"public.users"}
        connection.close.assert_called_once()

    def _drop_on_execute_connection(self, error):
        cursor = mock.MagicMock()
        cursor.execute.side_effect = error

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None

        connection = mock.MagicMock()
        connection.cursor.return_value = cursor_context
        return connection

    def test_get_schemas_retries_pooler_drop_during_discovery_query(self):
        # The connect can succeed and the pooler then drop the upstream backend on the first
        # discovery query — Supavisor surfaces this as "(EDBHANDLEREXITED) connection to database
        # closed" (XX000 InternalError_). The retry must span the discovery queries, not just the
        # connect, so a fresh connection reruns discovery instead of escaping as captured error noise.
        drop = psycopg.errors.InternalError_(
            "(EDBHANDLEREXITED) connection to database closed. Check logs for more information"
        )
        dropped_connection = self._drop_on_execute_connection(drop)
        good_connection = self._mock_connection(
            [("public", "users")],
            [("public", "users", "id", "integer", "NO", 1)],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[dropped_connection, good_connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                schemas = get_schemas(
                    host="localhost",
                    port=5432,
                    database="postgres",
                    user="postgres",
                    password="postgres",
                    schema="",
                )

        # Drop on the first query reconnected and reran discovery — before the fix the retry only
        # wrapped the connect, so the query-time drop escaped on the first attempt (call_count == 1).
        assert connect_mock.call_count == 2
        assert set(schemas.keys()) == {"public.users"}
        dropped_connection.close.assert_called_once()
        good_connection.close.assert_called_once()

    def test_get_schemas_retries_pooler_connection_limit_on_discovery_query(self):
        # A pooler can accept the connect and then reveal, on the first discovery query, that the
        # customer database is out of connection slots — caching the upstream login failure as a
        # ProtocolViolation ("server login has been failing, cached error: remaining connection slots
        # are reserved ..."). It's a transient capacity condition (a slot frees as connections close),
        # so discovery must retry on a fresh connection. Before the fix the SET-timeout `except` rolled
        # the refused connection back — raising a misleading "the connection is lost" — and the
        # discovery retry didn't cover connection-limit refusals, so it surfaced as captured noise.
        refusal = psycopg.errors.ProtocolViolation(
            "server login has been failing, cached error: remaining connection slots are reserved "
            "for roles with the SUPERUSER attribute (server_login_retry)"
        )
        refused_connection = self._drop_on_execute_connection(refusal)
        good_connection = self._mock_connection(
            [("public", "users")],
            [("public", "users", "id", "integer", "NO", 1)],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[refused_connection, good_connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                schemas = get_schemas(
                    host="localhost",
                    port=5432,
                    database="postgres",
                    user="postgres",
                    password="postgres",
                    schema="",
                )

        assert connect_mock.call_count == 2
        assert set(schemas.keys()) == {"public.users"}
        refused_connection.close.assert_called_once()
        good_connection.close.assert_called_once()
        # The refused connection was never rolled back — that's what masked the real cause before.
        refused_connection.rollback.assert_not_called()

    def test_get_schemas_retries_connection_limit_refused_on_connect(self):
        # The customer database can refuse the discovery connect outright once it's out of slots
        # ("remaining connection slots are reserved for roles with the SUPERUSER attribute"). It's the
        # same transient capacity class as a dropped connection, so discovery must retry on a fresh
        # connect rather than fail the activity on the first blip — before the fix the discovery retry
        # only covered drops, so a connection-limit refusal escaped on the first attempt.
        refusal = psycopg.OperationalError(
            'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
            "FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute"
        )
        good_connection = self._mock_connection(
            [("public", "users")],
            [("public", "users", "id", "integer", "NO", 1)],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[refusal, good_connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                schemas = get_schemas(
                    host="localhost",
                    port=5432,
                    database="postgres",
                    user="postgres",
                    password="postgres",
                    schema="",
                )

        assert connect_mock.call_count == 2
        assert set(schemas.keys()) == {"public.users"}
        good_connection.close.assert_called_once()

    def test_get_schemas_does_not_retry_non_drop_error_during_discovery_query(self):
        # A genuine XX000 internal error that isn't the pooler drop must propagate on the first
        # discovery attempt — the discovery retry is scoped strictly to transient drops.
        err = psycopg.errors.InternalError_("XX000: internal error: something went wrong")
        dropped_connection = self._drop_on_execute_connection(err)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=[dropped_connection],
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                with pytest.raises(psycopg.errors.InternalError_):
                    get_schemas(
                        host="localhost",
                        port=5432,
                        database="postgres",
                        user="postgres",
                        password="postgres",
                        schema="",
                    )

        assert connect_mock.call_count == 1
        dropped_connection.close.assert_called_once()

    def test_get_schemas_does_not_retry_permanent_connect_error(self):
        # A permanent connect failure (bad password) must propagate on the first attempt — the
        # dropped-connection retry is scoped strictly to transient drops.
        err = psycopg.OperationalError(
            'connection to server at "10.0.0.1" failed: FATAL: password authentication failed for user "postgres"'
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
            side_effect=err,
        ) as connect_mock:
            with mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"
            ):
                with pytest.raises(psycopg.OperationalError):
                    get_schemas(
                        host="localhost",
                        port=5432,
                        database="postgres",
                        user="postgres",
                        password="postgres",
                        schema="",
                    )

        assert connect_mock.call_count == 1

    def test_get_schemas_qualifies_table_names_when_schema_is_blank(self):
        connection = self._mock_connection(
            [("public", "users"), ("analytics", "events")],
            [
                ("analytics", "events", "id", "integer", "NO", 1),
                ("public", "users", "id", "integer", "NO", 1),
            ],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            schemas = get_schemas(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        executed_queries = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "SELECT version()" not in str(call.args[0]) and "statement_timeout" not in str(call.args[0])
        ]
        first_query = executed_queries[0]
        second_query = executed_queries[1]

        assert "NOT IN" in first_query
        assert "ALL(" not in first_query
        assert " IN (" in second_query
        assert "ANY(" not in second_query
        assert set(schemas.keys()) == {"public.users", "analytics.events"}
        assert schemas["public.users"].source_schema == "public"
        assert schemas["public.users"].source_table_name == "users"
        assert schemas["analytics.events"].source_schema == "analytics"
        assert schemas["analytics.events"].source_table_name == "events"

    @pytest.mark.parametrize(
        "selected_schema,requested_name,fetchall_results,expected_keys",
        [
            # Qualified lookup against a schema that's keyed unqualified (config.schema set).
            # This is the multi-schema migration scenario: row name was rewritten to
            # `public.tracking_link` while the source still has `schema="public"` configured.
            (
                "public",
                "public.tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"public.tracking_link"},
            ),
            # Unqualified lookup against an unqualified keyspace — the legacy path.
            (
                "public",
                "tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"tracking_link"},
            ),
            # Qualified lookup against a qualified keyspace (no config.schema, multi-schema mode).
            (
                "",
                "public.tracking_link",
                (
                    [("public", "tracking_link")],
                    [("public", "tracking_link", "id", "integer", "NO", 1)],
                ),
                {"public.tracking_link"},
            ),
        ],
    )
    def test_get_schemas_accepts_qualified_and_unqualified_names(
        self, selected_schema, requested_name, fetchall_results, expected_keys
    ):
        connection = self._mock_connection(*fetchall_results)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            schemas = get_schemas(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema=selected_schema,
                names=[requested_name],
            )

        assert set(schemas.keys()) == expected_keys

    def test_get_foreign_keys_qualifies_target_table_names_when_schema_is_blank(self):
        connection = self._mock_connection(
            [("public", "users"), ("analytics", "events")],
            [("analytics", "events", "user_id", "public", "users", "id")],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            foreign_keys = get_foreign_keys(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        executed_queries = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "SELECT version()" not in str(call.args[0]) and "statement_timeout" not in str(call.args[0])
        ]
        first_query = executed_queries[0]
        second_query = executed_queries[1]

        assert "NOT IN" in first_query
        assert "ALL(" not in first_query
        assert " IN (" in second_query
        assert "ANY(" not in second_query
        assert foreign_keys == {"analytics.events": [("user_id", "public.users", "id")]}

    def test_get_schemas_for_duckdb_uses_current_catalog_only(self):
        connection = self._mock_connection(
            [("ducklake", "system", "query_log")],
            [
                ("system", "query_log", "query_id", "varchar", "NO", 1),
            ],
        )
        connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
            ("DuckDB 1.4 (Duckgres)",),
            ("ducklake",),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres",
            return_value=connection,
        ):
            schemas = get_schemas(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="",
            )

        cursor = connection.cursor.return_value.__enter__.return_value
        information_schema_call = next(
            call for call in cursor.execute.call_args_list if "FROM information_schema.tables" in str(call.args[0])
        )
        information_schema_query = str(information_schema_call.args[0])
        information_schema_params = information_schema_call.args[1]

        assert "table_catalog = %(current_database)s" in information_schema_query
        assert information_schema_params["current_database"] == "ducklake"
        assert schemas["system.query_log"].source_catalog == "ducklake"
        assert "public.ducklake_view" not in schemas

    def test_get_postgres_row_count_skips_blank_schema_browse(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._connect_to_postgres"
        ) as patch_connect_to_postgres:
            row_counts = get_postgres_row_count(
                host="localhost",
                port=5432,
                database="postgres",
                user="postgres",
                password="postgres",
                schema="   ",
            )

        assert row_counts == {}
        patch_connect_to_postgres.assert_not_called()


class TestPostgresSourceGetSchemasDegradesGracefully:
    @pytest.fixture
    def source(self):
        return PostgresSource()

    def _config(self):
        return mock.MagicMock(user="u", password="p", database="db", schema="", ssh_tunnel=None)

    @pytest.mark.parametrize(
        "exc",
        [
            psycopg.errors.OutOfMemory(
                'out of memory\nDETAIL:  Failed on request of size 2048 in memory context "ExecutorState".'
            ),
            psycopg.OperationalError("connection refused"),
            Exception("unexpected error"),
        ],
    )
    def test_foreign_key_discovery_failure_does_not_break_schema_listing(self, source, exc):
        # A failing foreign-key lookup (e.g. the source DB OOMs on the information_schema join)
        # must degrade to empty foreign keys, not take down the whole schema listing.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                side_effect=exc,
            ),
            # PK/index discovery opens its own connection; let it fail so the test needs no real DB.
            # That path is already guarded and defaults gracefully.
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.pg_connection",
                side_effect=psycopg.OperationalError("no db in test"),
            ),
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        assert schemas[0].foreign_keys == []

    def test_metadata_connection_failure_degrades_quietly_without_capturing(self, source):
        # The PK/index/RLS metadata connection is opened separately from schema discovery and is
        # prone to transient drops (commonly an SSH-tunnel hiccup raising "server closed the
        # connection unexpectedly"). Schema discovery already succeeded, so this must degrade quietly:
        # surface the schema listing and DON'T flood error tracking with a captured exception.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        connection_dropped = psycopg.OperationalError(
            'connection failed: connection to server at "127.0.0.1", port 37761 failed: '
            "server closed the connection unexpectedly\n\tThis probably means the server terminated "
            "abnormally\n\tbefore or while processing the request."
        )

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                return_value={},
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.pg_connection",
                side_effect=connection_dropped,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.capture_exception"
            ) as mock_capture,
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        # Best-effort metadata is dropped, but the listing survives and nothing is captured.
        assert schemas[0].supports_cdc is False
        mock_capture.assert_not_called()

    def test_primary_key_discovery_failure_degrades_without_capturing_exception(self, source):
        # Some Postgres-wire-compatible engines reject our pg_catalog PK query (e.g. a
        # DuckDB/DuckLake backend can't bind `ANY(indkey)` and raises the binder error
        # below). PK discovery is best-effort and already falls back to no-CDC, so the
        # failure must be logged, not flooded into error tracking as a captured exception.
        discovered = {
            "public.users": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="users",
                columns=[("id", "integer", False)],
            )
        }

        tunnel_cm = mock.MagicMock()
        tunnel_cm.__enter__.return_value = ("localhost", 5432)
        tunnel_cm.__exit__.return_value = None

        conn_cm = mock.MagicMock()
        conn_cm.__enter__.return_value = mock.MagicMock()
        conn_cm.__exit__.return_value = None

        unnest_error = psycopg.errors.InternalError_(
            "flight execute: rpc error: code = InvalidArgument desc = failed to prepare query: "
            "Binder Error: UNNEST not supported here"
        )

        with (
            mock.patch.object(source, "with_ssh_tunnel", return_value=tunnel_cm),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
                return_value=discovered,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
                return_value={},
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.pg_connection",
                return_value=conn_cm,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_primary_key_columns",
                side_effect=unnest_error,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_leading_index_columns",
                return_value={"users": set()},
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source._rls_active_from_conn",
                return_value={},
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.capture_exception"
            ) as mock_capture,
        ):
            schemas = source.get_schemas(self._config(), team_id=1)

        assert len(schemas) == 1
        assert schemas[0].name == "public.users"
        # PK discovery failed, so CDC must not be advertised — but the listing still succeeds.
        assert schemas[0].supports_cdc is False
        # The handled, best-effort failure must not be captured as an exception.
        mock_capture.assert_not_called()


class TestGetSslmode:
    @pytest.mark.parametrize(
        "require_ssl,expected",
        [
            (True, "prefer"),
            (False, "prefer"),
        ],
    )
    def test_returns_prefer_in_test_mode(self, require_ssl, expected):
        """In TEST mode (our default for pytest), always returns 'prefer'."""
        assert _get_sslmode(require_ssl) == expected

    def test_returns_require_when_ssl_required_outside_test(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.settings"
        ) as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(True) == "require"

    def test_returns_prefer_when_ssl_not_required_outside_test(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.settings"
        ) as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(False) == "prefer"

    def test_returns_prefer_in_debug_mode(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.settings"
        ) as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = True
            mock_settings.E2E_TESTING = False
            assert _get_sslmode(True) == "prefer"

    def test_returns_prefer_in_e2e_mode(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.settings"
        ) as mock_settings:
            mock_settings.TEST = False
            mock_settings.DEBUG = False
            mock_settings.E2E_TESTING = True
            assert _get_sslmode(True) == "prefer"


class TestNormalizeFunctionNames:
    def test_valid_identifiers(self):
        result = _normalize_function_names(["foo", "bar_baz", "_private", "CamelCase"])
        assert result == ["_private", "bar_baz", "camelcase", "foo"]

    def test_filters_invalid_identifiers(self):
        result = _normalize_function_names(["valid", "123invalid", "has-dash", "also valid", "ok_name"])
        assert result == ["ok_name", "valid"]

    def test_filters_non_string_values(self):
        result = _normalize_function_names(["valid", 123, None, True, "another"])
        assert result == ["another", "valid"]

    def test_deduplicates_case_insensitive(self):
        result = _normalize_function_names(["Foo", "foo", "FOO"])
        assert result == ["foo"]

    def test_empty_list(self):
        assert _normalize_function_names([]) == []

    def test_all_invalid(self):
        assert _normalize_function_names([123, None, "1bad", "has space"]) == []

    def test_rejects_empty_string(self):
        assert _normalize_function_names([""]) == []


class TestFilterPostgresIncrementalFields:
    @pytest.mark.parametrize(
        "type_name,expected_type",
        [
            ("timestamp", IncrementalFieldType.Timestamp),
            ("timestamp without time zone", IncrementalFieldType.Timestamp),
            ("timestamp with time zone", IncrementalFieldType.Timestamp),
            ("timestamptz", IncrementalFieldType.Timestamp),
            ("TIMESTAMP", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("DATE", IncrementalFieldType.Date),
            ("integer", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
            ("INTEGER", IncrementalFieldType.Integer),
        ],
    )
    def test_supported_types(self, type_name, expected_type):
        result = filter_postgres_incremental_fields([("col", type_name, False)])
        assert result == [("col", expected_type, False)]

    @pytest.mark.parametrize(
        "type_name",
        ["text", "varchar", "boolean", "real", "numeric", "serial", "bigserial", "uuid", "json", "bytea"],
    )
    def test_unsupported_types_excluded(self, type_name):
        result = filter_postgres_incremental_fields([("col", type_name, False)])
        assert result == []

    def test_preserves_nullable_flag(self):
        result = filter_postgres_incremental_fields([("col", "integer", True)])
        assert result == [("col", IncrementalFieldType.Integer, True)]

    def test_multiple_columns(self):
        columns = [
            ("id", "integer", False),
            ("name", "text", False),
            ("created_at", "timestamp", True),
            ("is_active", "boolean", False),
            ("updated_at", "date", False),
        ]
        result = filter_postgres_incremental_fields(columns)
        assert result == [
            ("id", IncrementalFieldType.Integer, False),
            ("created_at", IncrementalFieldType.Timestamp, True),
            ("updated_at", IncrementalFieldType.Date, False),
        ]

    def test_empty_list(self):
        assert filter_postgres_incremental_fields([]) == []


class TestBuildQuery:
    def _render(self, composed: sql.Composed) -> str:
        """Render a psycopg sql.Composed to string without a connection."""
        return composed.as_string()

    def test_full_refresh(self):
        query = _build_query("public", "users", False, "table", None, None, None)
        rendered = self._render(query)
        assert '"public"."users"' in rendered
        assert "SELECT *" in rendered
        assert "WHERE" not in rendered

    def test_incremental(self):
        query = _build_query(
            "public", "events", True, "table", "created_at", IncrementalFieldType.Timestamp, "2024-01-01"
        )
        rendered = self._render(query)
        assert '"created_at"' in rendered
        assert "'2024-01-01'" in rendered
        assert "ORDER BY" in rendered

    def test_incremental_raises_without_field(self):
        with pytest.raises(ValueError, match="incremental_field and incremental_field_type can't be None"):
            _build_query("public", "events", True, "table", None, None, None)

    def test_incremental_raises_without_field_type(self):
        with pytest.raises(ValueError):
            _build_query("public", "events", True, "table", "id", None, None)

    def test_sampling_table(self):
        query = _build_query("public", "users", False, "table", None, None, None, add_sampling=True)
        rendered = self._render(query)
        assert "TABLESAMPLE SYSTEM (1)" in rendered
        assert "LIMIT 1000" in rendered

    def test_sampling_view(self):
        query = _build_query("public", "users", False, "view", None, None, None, add_sampling=True)
        rendered = self._render(query)
        assert "random() < 0.01" in rendered
        assert "LIMIT 1000" in rendered

    def test_incremental_with_sampling_table(self):
        query = _build_query(
            "myschema", "events", True, "table", "id", IncrementalFieldType.Integer, 100, add_sampling=True
        )
        rendered = self._render(query)
        assert "TABLESAMPLE SYSTEM (1)" in rendered
        assert '"id"' in rendered
        assert "LIMIT 1000" in rendered

    def test_incremental_with_sampling_view(self):
        query = _build_query(
            "myschema", "events", True, "view", "id", IncrementalFieldType.Integer, 100, add_sampling=True
        )
        rendered = self._render(query)
        assert "random() < 0.01" in rendered
        assert '"id"' in rendered
        assert "LIMIT 1000" in rendered

    @pytest.mark.parametrize(
        "case_name,enabled_columns,primary_keys,should_use_incremental,incremental_field,incremental_type,last_value,must_contain,must_not_contain,ordered",
        [
            (
                "explicit_list_includes_pk",
                ["email", "name"],
                ["id"],
                False,
                None,
                None,
                None,
                ['"email"', '"name"', '"id"'],
                ["SELECT *"],
                None,
            ),
            (
                "preserves_user_order_pk_appended",
                ["zeta", "alpha"],
                ["id"],
                False,
                None,
                None,
                None,
                [],
                None,
                ['"zeta"', '"alpha"', '"id"'],
            ),
            (
                "includes_incremental_field",
                ["payload"],
                ["id"],
                True,
                "updated_at",
                IncrementalFieldType.Timestamp,
                "2024-01-01",
                ['"payload"', '"updated_at"', '"id"'],
                None,
                None,
            ),
            (
                "none_is_select_star",
                None,
                ["id"],
                False,
                None,
                None,
                None,
                ["SELECT *"],
                None,
                None,
            ),
            (
                "empty_keeps_only_pks_and_incremental",
                [],
                ["id"],
                False,
                None,
                None,
                None,
                ['"id"'],
                ["SELECT *"],
                None,
            ),
            # Guard against an invalid `SELECT  FROM` when no columns can be retained.
            (
                "empty_with_no_pks_or_incremental_falls_back_to_star",
                [],
                None,
                False,
                None,
                None,
                None,
                ["SELECT *"],
                None,
                None,
            ),
        ],
    )
    def test_enabled_columns_projection(
        self,
        case_name,
        enabled_columns,
        primary_keys,
        should_use_incremental,
        incremental_field,
        incremental_type,
        last_value,
        must_contain,
        must_not_contain,
        ordered,
    ):
        query = _build_query(
            "public",
            "events" if should_use_incremental else "users",
            should_use_incremental,
            "table",
            incremental_field,
            incremental_type,
            last_value,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        rendered = self._render(query)
        for substring in must_contain or []:
            assert substring in rendered, f"[{case_name}] expected {substring!r} in {rendered!r}"
        for substring in must_not_contain or []:
            assert substring not in rendered, f"[{case_name}] expected {substring!r} NOT in {rendered!r}"
        if ordered:
            positions = [rendered.index(s) for s in ordered]
            assert positions == sorted(positions), f"[{case_name}] expected {ordered} in order in {rendered!r}"

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            # Date cursors must be inclusive — saving cursor='2026-05-13' and re-querying with
            # `>` skips every row that lands on 2026-05-13 after the cursor advanced.
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Timestamp, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = _build_query("public", "events", True, "table", "cursor", field_type, last_value)
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered
        # The other operator never appears for the cursor column.
        wrong = ">" if expected_operator == ">=" else ">="
        assert f'"cursor" {wrong} ' not in rendered

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_count_query_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = _build_count_query("public", "events", True, "cursor", field_type, last_value)
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered

    def test_windowed_mode_keeps_exclusive_lower_bound_for_date(self):
        # iterate_date_windows feeds previous_hi as next_lo; `>=` would re-fetch every
        # boundary date inside one run, so the upper_bound_inclusive path must stay `>`.
        query = _build_query(
            "public",
            "events",
            True,
            "table",
            "cursor",
            IncrementalFieldType.Date,
            date(2026, 5, 13),
            upper_bound_inclusive=date(2026, 5, 14),
        )
        rendered = self._render(query)
        assert '"cursor" > ' in rendered
        assert '"cursor" >= ' not in rendered

    def test_row_filter_full_refresh(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert 'WHERE "age" > 21' in rendered

    def test_row_filter_composes_with_incremental(self):
        query = _build_query(
            "public",
            "events",
            True,
            "table",
            "created_at",
            IncrementalFieldType.Timestamp,
            "2024-01-01",
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert '"created_at"' in rendered
        assert 'AND "age" > 21' in rendered
        assert rendered.rstrip().endswith('ORDER BY "created_at" ASC')

    def test_row_filter_in_list_renders_parenthesized(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30, 40], category=ColumnTypeCategory.INTEGER)
            ],
        )
        rendered = self._render(query)
        assert 'WHERE "age" IN (21, 30, 40)' in rendered

    def test_row_filter_composes_with_windowed_upper_bound(self):
        query = _build_query(
            "public",
            "events",
            True,
            "table",
            "cursor",
            IncrementalFieldType.Date,
            date(2026, 5, 13),
            upper_bound_inclusive=date(2026, 5, 14),
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        # Row filter is ANDed after the window's upper bound, before ORDER BY.
        assert '"cursor" <= ' in rendered
        assert 'AND "age" > 21' in rendered
        assert rendered.index('"cursor" <= ') < rendered.index('"age" > 21')

    def test_row_filter_not_applied_to_sampling(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            add_sampling=True,
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert '"age"' not in rendered

    def test_row_filter_string_value_is_escaped_literal(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            row_filters=[
                ValidatedRowFilter(
                    column="name", operator="=", value="x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
                )
            ],
        )
        rendered = self._render(query)
        assert "'x''; DROP TABLE y; --'" in rendered


class TestBuildXminQuery:
    def _render(self, composed: sql.Composed) -> str:
        return composed.as_string()

    def _bounds(self, *, lower=0, upper=5000, num_wraparound=0, wraparound_or_range=False) -> XminBounds:
        return XminBounds(
            lower=lower,
            upper=upper,
            ceiling_xid8=(num_wraparound << 32) | upper,
            num_wraparound=num_wraparound,
            wraparound_or_range=wraparound_or_range,
        )

    def test_first_run_reads_below_ceiling(self):
        query = _build_query("public", "users", False, "table", None, None, None, xmin_bounds=self._bounds(lower=0))
        rendered = self._render(query)
        assert f'xmin::text::bigint AS "{XMIN_PROJECTED_COLUMN}"' in rendered
        assert "xmin::text::bigint >= 0 AND xmin::text::bigint < 5000" in rendered
        assert "OR xmin::text::bigint" not in rendered
        assert rendered.rstrip().endswith("ORDER BY xmin::text::bigint ASC")

    def test_steady_state_single_range(self):
        query = _build_query(
            "public", "users", False, "table", None, None, None, xmin_bounds=self._bounds(lower=100, upper=5000)
        )
        rendered = self._render(query)
        assert "xmin::text::bigint >= 100 AND xmin::text::bigint < 5000" in rendered

    def test_wraparound_or_range(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            xmin_bounds=self._bounds(lower=4000000000, upper=500, num_wraparound=1, wraparound_or_range=True),
        )
        rendered = self._render(query)
        assert "xmin::text::bigint >= 4000000000 OR xmin::text::bigint < 500" in rendered

    def test_projects_ph_xmin_alias(self):
        query = _build_query("public", "users", False, "table", None, None, None, xmin_bounds=self._bounds())
        rendered = self._render(query)
        # `*` is kept so the user's columns come back alongside the synthetic cursor.
        assert f'SELECT xmin::text::bigint AS "{XMIN_PROJECTED_COLUMN}", *' in rendered

    def test_row_filter_anded_into_predicate(self):
        query = _build_query(
            "public",
            "users",
            False,
            "table",
            None,
            None,
            None,
            xmin_bounds=self._bounds(lower=100, upper=5000),
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert 'AND "age" > 21' in rendered
        assert rendered.index("xmin::text::bigint < 5000") < rendered.index('"age" > 21')

    def test_sampling_appends_limit(self):
        query = _build_query(
            "public", "users", False, "table", None, None, None, add_sampling=True, xmin_bounds=self._bounds()
        )
        rendered = self._render(query)
        assert rendered.rstrip().endswith("LIMIT 1000")

    def test_count_query_uses_bounded_predicate(self):
        query = _build_count_query("public", "users", False, None, None, None, xmin_bounds=self._bounds(lower=100))
        rendered = self._render(query)
        assert "SELECT COUNT(*)" in rendered
        assert "xmin::text::bigint >= 100 AND xmin::text::bigint < 5000" in rendered


class TestCaptureXminCeiling:
    def _cursor(self, *, server_version: int, ceiling_xid8: int, ceiling_xid: int) -> MagicMock:
        cursor = MagicMock()
        cursor.connection.info.server_version = server_version
        cursor.fetchone.return_value = (ceiling_xid8, ceiling_xid)
        return cursor

    def test_requires_pg13(self):
        cursor = self._cursor(server_version=120000, ceiling_xid8=5000, ceiling_xid=5000)
        with pytest.raises(XminUnsupportedError, match="PostgreSQL 13"):
            _capture_xmin_ceiling(cursor, None, None, MagicMock())

    def test_first_run_seeds_zero_lower_bound(self):
        cursor = self._cursor(server_version=150000, ceiling_xid8=5000, ceiling_xid=5000)
        bounds = _capture_xmin_ceiling(cursor, None, None, MagicMock())
        assert bounds.lower == 0
        assert bounds.upper == 5000
        assert bounds.wraparound_or_range is False

    def test_steady_state_uses_stored_lower_bound(self):
        cursor = self._cursor(server_version=150000, ceiling_xid8=5000, ceiling_xid=5000)
        bounds = _capture_xmin_ceiling(cursor, 100, 0, MagicMock())
        assert bounds.lower == 100
        assert bounds.wraparound_or_range is False

    def test_single_wrap_sets_or_range(self):
        # Epoch advanced by exactly 1 since last sync.
        cursor = self._cursor(server_version=150000, ceiling_xid8=(1 << 32) | 500, ceiling_xid=500)
        bounds = _capture_xmin_ceiling(cursor, 4000000000, 0, MagicMock())
        assert bounds.num_wraparound == 1
        assert bounds.wraparound_or_range is True
        assert bounds.lower == 4000000000

    def test_multi_wrap_forces_full_reread(self):
        cursor = self._cursor(server_version=150000, ceiling_xid8=(3 << 32) | 500, ceiling_xid=500)
        bounds = _capture_xmin_ceiling(cursor, 4000000000, 0, MagicMock())
        assert bounds.lower == 0
        assert bounds.wraparound_or_range is False


class TestXminCapableTablesFromConn:
    def test_pg12_is_never_xmin_capable(self):
        # The PG13 guard short-circuits before any catalog query runs.
        connection = MagicMock()
        connection.info.server_version = 120000
        assert _xmin_capable_tables_from_conn(connection, "public", None) == set()
        connection.cursor.assert_not_called()


class TestBuildPartitionQuery:
    def _render(self, composed: sql.Composed) -> str:
        return composed.as_string()

    def test_full_refresh_targets_child_relation(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        rendered = self._render(query)
        assert '"public"."events_2026_01"' in rendered
        assert "WHERE" not in rendered

    def test_incremental_applies_cursor_filter(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value="2026-01-15",
        )
        rendered = self._render(query)
        assert '"public"."events_2026_01"' in rendered
        assert '"created_at" > ' in rendered
        assert "'2026-01-15'" in rendered
        assert "ORDER BY" in rendered

    def test_incremental_raises_without_field(self):
        with pytest.raises(ValueError, match="incremental_field and incremental_field_type can't be None"):
            build_partition_query(
                "public",
                "events_2026_01",
                should_use_incremental_field=True,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    @pytest.mark.parametrize(
        "field_type,last_value,expected_operator",
        [
            (IncrementalFieldType.Date, date(2026, 5, 13), ">="),
            (IncrementalFieldType.DateTime, datetime(2026, 5, 13, 1, 36, tzinfo=UTC), ">"),
            (IncrementalFieldType.Integer, 100, ">"),
        ],
    )
    def test_operator_matches_field_type(self, field_type, last_value, expected_operator):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=True,
            incremental_field="cursor",
            incremental_field_type=field_type,
            db_incremental_field_last_value=last_value,
        )
        rendered = self._render(query)
        assert f'"cursor" {expected_operator} ' in rendered

    def test_row_filter_full_refresh(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert 'WHERE "age" > 21' in rendered

    def test_row_filter_composes_with_incremental(self):
        query = build_partition_query(
            "public",
            "events_2026_01",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value="2026-01-15",
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        rendered = self._render(query)
        assert '"created_at" > ' in rendered
        assert 'AND "age" > 21' in rendered
        assert rendered.rstrip().endswith('ORDER BY "created_at" ASC')


class TestBuildCountQuery:
    def _render(self, composed: sql.Composed) -> str:
        return composed.as_string()

    def test_full_refresh_count_query(self):
        query = _build_count_query("public", "users", False, None, None, None)
        rendered = self._render(query)
        assert "SELECT COUNT(*)" in rendered
        assert '"public"."users"' in rendered
        assert "WHERE" not in rendered
        assert "ORDER BY" not in rendered
        assert "FROM (" not in rendered

    def test_incremental_count_query(self):
        query = _build_count_query("public", "events", True, "created_at", IncrementalFieldType.Timestamp, "2024-01-01")
        rendered = self._render(query)
        assert "SELECT COUNT(*)" in rendered
        assert '"public"."events"' in rendered
        assert '"created_at"' in rendered
        assert "'2024-01-01'" in rendered
        assert "ORDER BY" not in rendered
        assert "FROM (" not in rendered


class TestIsPartitionedTable:
    @pytest.mark.parametrize(
        "setup_ddl, table_name, expected",
        [
            (
                [
                    "CREATE TABLE test_is_part (id INTEGER, created_at DATE NOT NULL, PRIMARY KEY (id, created_at)) PARTITION BY RANGE (created_at)",
                    "CREATE TABLE test_is_part_2026 PARTITION OF test_is_part FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
                ],
                "test_is_part",
                True,
            ),
            (
                ["CREATE TABLE test_is_regular (id SERIAL PRIMARY KEY, data TEXT)"],
                "test_is_regular",
                False,
            ),
            ([], "does_not_exist_xyz", False),
        ],
    )
    @pytest.mark.django_db
    def test_is_partitioned_table(self, setup_ddl, table_name, expected):
        with django_connection.cursor() as dj_cursor:
            for stmt in setup_ddl:
                dj_cursor.execute(stmt)
            assert _is_partitioned_table(cast(Any, dj_cursor), "public", table_name) is expected


@pytest.fixture
def autocommit_pg_connection():
    # Raw autocommit connection to the test DB — mirrors how discovery connects in production
    # (no shared transaction). The default django_db cursor runs inside a transaction and can't
    # exercise the isolation path.
    sd = django_connection.settings_dict
    conn = psycopg.connect(
        host=sd["HOST"] or None,
        port=sd["PORT"] or None,
        dbname=sd["NAME"],
        user=sd["USER"] or None,
        password=sd["PASSWORD"] or None,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


class TestGetTableChunkSize:
    @pytest.mark.django_db
    def test_failing_probe_isolated_by_autocommit(self, autocommit_pg_connection):
        # A failing probe falls back to DEFAULT_CHUNK_SIZE and, under autocommit, doesn't poison
        # the connection for later probes.
        logger = structlog.get_logger()
        with autocommit_pg_connection.cursor() as cursor:
            inner_query = sql.SQL("SELECT * FROM does_not_exist_chunk_probe").format()

            chunk_size = _get_table_chunk_size(cast(Any, cursor), inner_query, logger)
            assert chunk_size == DEFAULT_CHUNK_SIZE

            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

    @pytest.mark.django_db
    def test_statement_timeout_falls_back_without_poisoning_transaction(self):
        # The estimation query wraps the sample in octet_length(t::text), which can exceed the
        # source's statement_timeout on tables whose rows trigger slow validator functions. A
        # cancelled probe must degrade to DEFAULT_CHUNK_SIZE, not crash the whole import — the
        # streaming read loop has its own dedicated QueryCanceled handling.
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            # Tight timeout + a deliberately slow probe reproduces a real QueryCanceled.
            dj_cursor.execute("SET LOCAL statement_timeout = '100ms'")
            inner_query = sql.SQL("SELECT pg_sleep(3) AS c").format()

            chunk_size = _get_table_chunk_size(cast(Any, dj_cursor), inner_query, logger)
            assert chunk_size == DEFAULT_CHUNK_SIZE

            # Savepoint rollback leaves the connection usable for the rest of setup.
            dj_cursor.execute("SELECT 1")
            assert dj_cursor.fetchone()[0] == 1


class TestGetRowsToSync:
    # Mirrors a misconfigured incremental field: COUNT(*) over a column that doesn't exist.
    _FAILING_COUNT_QUERY = sql.SQL("SELECT COUNT(*) FROM {table} WHERE {col} > 0").format(
        table=sql.Identifier("information_schema", "tables"),
        col=sql.Identifier("does_not_exist_count_col"),
    )

    @pytest.mark.django_db
    def test_failing_count_query_falls_back_to_zero_without_capturing(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
            ) as mock_capture:
                rows = _get_rows_to_sync(cast(Any, dj_cursor), self._FAILING_COUNT_QUERY, logger)

        # Best-effort estimate falls back to 0 and never reports the handled failure.
        assert rows == 0
        mock_capture.assert_not_called()

    @pytest.mark.django_db
    def test_failing_count_isolated_by_autocommit(self, autocommit_pg_connection):
        # Regression for the reported incident: a read-replica recovery conflict cancels the
        # rows-to-sync COUNT(*). Under autocommit the failure stays contained — returns 0 and
        # leaves the connection usable — instead of poisoning a shared transaction.
        logger = structlog.get_logger()
        with autocommit_pg_connection.cursor() as cursor:
            assert _get_rows_to_sync(cast(Any, cursor), self._FAILING_COUNT_QUERY, logger) == 0

            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

    def test_temp_file_limit_error_still_raises(self):
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("temporary file size exceeds temp_file_limit (1048576kB)")
        count_query = _build_count_query("public", "users", False, None, None, None)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            with pytest.raises(TemporaryFileSizeExceedsLimitException):
                _get_rows_to_sync(cast(Any, cursor), count_query, logger)

        # The temp-file signal is actionable, so it propagates rather than being swallowed.
        mock_capture.assert_not_called()

    @pytest.mark.parametrize(
        "should_use_incremental_field,expect_raise",
        [
            # Full-table sync: the COUNT is a full scan while extraction streams sequentially via a
            # server cursor, so a statement_timeout here says nothing about whether extraction will
            # succeed. It must degrade to an unknown total (0), not fail setup with a raw, retryable
            # QueryCanceled that floods error tracking and Temporal re-attempts forever.
            (False, False),
            # Incremental sync: the COUNT shares its WHERE with the chunked read, so the timeout is
            # predictive — re-raise so the caller surfaces the "add an index" guidance.
            (True, True),
        ],
    )
    def test_statement_timeout_degrades_for_full_table_but_re_raises_for_incremental(
        self, should_use_incremental_field, expect_raise
    ):
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        count_query = _build_count_query("public", "users", False, None, None, None)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            if expect_raise:
                with pytest.raises(psycopg.errors.QueryCanceled):
                    _get_rows_to_sync(
                        cast(Any, cursor),
                        count_query,
                        logger,
                        should_use_incremental_field=should_use_incremental_field,
                    )
            else:
                assert (
                    _get_rows_to_sync(
                        cast(Any, cursor),
                        count_query,
                        logger,
                        should_use_incremental_field=should_use_incremental_field,
                    )
                    == 0
                )

        mock_capture.assert_not_called()


class TestPartitionedTableChunkSizing:
    """Incremental reads use per-child partition queries; no parent FETCH chunk cap."""

    def test_no_partitioned_fetch_cap_exported(self) -> None:
        assert not hasattr(partitioned_tables_pkg, "PARTITIONED_TABLE_MAX_CHUNK_SIZE")
        assert "PARTITIONED_TABLE_MAX_CHUNK_SIZE" not in partitioned_tables_pkg.__all__


class TestGetEstimatedRowCountForPartitionedTable:
    @pytest.mark.django_db
    def test_returns_estimate_for_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned_q1
                PARTITION OF test_est_count_partitioned
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partitioned_q2
                PARTITION OF test_est_count_partitioned
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_partitioned (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            dj_cursor.execute("ANALYZE test_est_count_partitioned")

            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_partitioned", logger
            )
            assert result is not None
            # reltuples is approximate; 200 rows should be close
            assert 150 <= result <= 250

    @pytest.mark.django_db
    def test_returns_none_for_non_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_est_count_regular (id SERIAL PRIMARY KEY, data TEXT)")
            dj_cursor.execute("INSERT INTO test_est_count_regular (data) SELECT 'x' FROM generate_series(1, 50)")
            dj_cursor.execute("ANALYZE test_est_count_regular")

            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_regular", logger
            )
            # No child partitions → partition_count == 0 → function returns None
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_when_partitions_partially_analyzed(self):
        """Mixed analyzed + unanalyzed partitions must not sum reltuples naively.

        reltuples = -1 on never-analyzed partitions would under-count if summed.
        We require all partitions analyzed before trusting reltuples.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial_q1
                PARTITION OF test_est_count_partial
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_partial_q2
                PARTITION OF test_est_count_partial
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_partial (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            # Analyze only the first partition — second remains reltuples=-1.
            dj_cursor.execute("ANALYZE test_est_count_partial_q1")

            # reltuples unreliable; n_live_tup is 0 inside test transaction →
            # function returns None, forcing exact COUNT(*) fallback.
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_partial", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_without_analyze(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_no_analyze (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_no_analyze_p1
                PARTITION OF test_est_count_no_analyze
                FOR VALUES FROM ('2026-01-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_est_count_no_analyze (created_at)
                SELECT '2026-03-01'::date FROM generate_series(1, 300)
            """)
            # Without ANALYZE, reltuples is -1 (PG14+). The stats collector
            # n_live_tup fallback also can't see rows inside a test transaction.
            # In production, committed inserts would be visible via n_live_tup.
            # Here the function returns None, causing a fallback to exact COUNT(*).
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_no_analyze", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_returns_none_for_empty_partitioned_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_est_count_empty (
                    id INTEGER,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_est_count_empty_p1
                PARTITION OF test_est_count_empty
                FOR VALUES FROM ('2026-01-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("ANALYZE test_est_count_empty")

            # Both reltuples and n_live_tup are 0 — falls back to exact COUNT(*)
            result = _get_estimated_row_count_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_est_count_empty", logger
            )
            assert result is None


class TestGetPartitionSettings:
    @pytest.mark.django_db
    def test_partitioned_table_uses_catalog_fast_path(self):
        """On a partitioned parent, settings come from pg_inherits/reltuples,
        not a COUNT(*) + pg_table_size on the parent.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    payload TEXT,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned_q1
                PARTITION OF test_ps_partitioned
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partitioned_q2
                PARTITION OF test_ps_partitioned
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_ps_partitioned (created_at, payload)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months',
                       repeat('x', 256)
                FROM generate_series(1, 500) g
            """)
            dj_cursor.execute("ANALYZE test_ps_partitioned")

            result = _get_partition_settings(cast(Any, dj_cursor), "public", "test_ps_partitioned", logger)
            assert result is not None
            assert result.partition_count >= 1
            assert result.partition_size > 0

    @pytest.mark.django_db
    def test_partitioned_table_returns_none_when_any_partition_unanalyzed(self):
        """Mixed analyzed + unanalyzed partitions must not produce a setting —
        the catalog numbers are stale, so fall through to exact scan.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial_q1
                PARTITION OF test_ps_partial
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_ps_partial_q2
                PARTITION OF test_ps_partial
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                INSERT INTO test_ps_partial (created_at)
                SELECT '2026-01-15'::date + (g % 2) * interval '3 months'
                FROM generate_series(1, 200) g
            """)
            dj_cursor.execute("ANALYZE test_ps_partial_q1")

            result = _get_partition_settings_for_partitioned_table(
                cast(Any, dj_cursor), "public", "test_ps_partial", logger
            )
            assert result is None

    @pytest.mark.django_db
    def test_non_partitioned_table_still_uses_legacy_query(self):
        """Regular tables must skip the catalog fast path and go through the
        original COUNT(*) + pg_table_size query.
        """
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_ps_regular (id SERIAL PRIMARY KEY, data TEXT)")
            dj_cursor.execute("INSERT INTO test_ps_regular (data) SELECT repeat('x', 128) FROM generate_series(1, 200)")
            dj_cursor.execute("ANALYZE test_ps_regular")

            result = _get_partition_settings(cast(Any, dj_cursor), "public", "test_ps_regular", logger)
            assert result is not None
            assert result.partition_size > 0

    def test_missing_table_falls_back_to_none_without_capturing(self):
        # The selected table was dropped/renamed before this best-effort probe, so psycopg raises
        # UndefinedTable (42P01). The real extraction query surfaces "does not exist" through the
        # non-retryable path, so this helper must degrade quietly (None) instead of flooding error
        # tracking with a handled duplicate.
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedTable('relation "public.store_source" does not exist')

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            result = _get_partition_settings(cast(Any, cursor), "public", "store_source", logger, is_partitioned=False)

        assert result is None
        mock_capture.assert_not_called()

    def test_reuses_passed_is_partitioned_flag(self):
        # When the caller already knows the table is partitioned, skip re-detecting it.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        sentinel = object()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._is_partitioned_table"
            ) as mock_detect,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._get_partition_settings_for_partitioned_table",
                return_value=sentinel,
            ) as mock_partitioned,
        ):
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=True)

        mock_detect.assert_not_called()
        mock_partitioned.assert_called_once()
        assert result is sentinel

    def test_recovery_conflict_returns_none_without_capturing(self):
        # Regression: a read-replica recovery conflict cancels the best-effort sizing query.
        # It's transient and the row-streaming reader retries it in-process, so degrade to None
        # without flooding error tracking with a handled condition.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = psycopg.errors.SerializationFailure(
            "canceling statement due to conflict with recovery"
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=False)

        assert result is None
        capture_mock.assert_not_called()

    @pytest.mark.django_db
    def test_failing_sizing_query_falls_back_to_none_without_capturing(self):
        logger = structlog.get_logger()

        # The sizing query runs against a table that doesn't exist — stands in for an
        # upstream/source-side failure (e.g. a misbehaving extension index on the source DB)
        # that is already tolerated by falling back to default partition settings.
        with django_connection.cursor() as dj_cursor:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
            ) as mock_capture:
                result = _get_partition_settings(cast(Any, dj_cursor), "public", "does_not_exist_ps_table", logger)

        # Best-effort sizing falls back to None and never reports the handled failure.
        assert result is None
        mock_capture.assert_not_called()

    @pytest.mark.parametrize(
        "exc",
        [
            # Direct read-replica recovery conflict on the sizing query.
            psycopg.errors.SerializationFailure("canceling statement due to conflict with recovery"),
            # Downstream symptom: an earlier best-effort query in this transaction hit the transient
            # condition above and left it in INERROR, so the sizing query fails with this instead.
            psycopg.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            ),
        ],
    )
    def test_handled_transient_errors_return_none_without_capturing(self, exc):
        # Both are handled, transient conditions that resurface (and are classified) via the real
        # extraction query, so partition sizing must degrade to None without flooding error tracking.
        logger = structlog.get_logger()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = exc

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _get_partition_settings(cast(Any, cursor), "public", "t", logger, is_partitioned=False)

        assert result is None
        capture_mock.assert_not_called()

    def test_temp_file_limit_error_still_raises(self):
        logger = structlog.get_logger()

        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("temporary file size exceeds temp_file_limit (1048576kB)")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            with pytest.raises(TemporaryFileSizeExceedsLimitException):
                _get_partition_settings(cast(Any, cursor), "public", "users", logger)

        # The temp-file signal is actionable, so it propagates rather than being swallowed.
        mock_capture.assert_not_called()


class TestPostgreSQLColumnToArrowField:
    @pytest.mark.parametrize(
        "data_type,expected_arrow_type",
        [
            ("bigint", pa.int64()),
            ("integer", pa.int32()),
            ("smallint", pa.int16()),
            ("real", pa.float32()),
            ("double precision", pa.float64()),
            ("text", pa.string()),
            ("varchar", pa.string()),
            ("character varying", pa.string()),
            ("date", pa.date32()),
            ("time", pa.time64("us")),
            ("time without time zone", pa.time64("us")),
            ("timestamp", pa.timestamp("us")),
            ("timestamp without time zone", pa.timestamp("us")),
            ("timestamptz", pa.timestamp("us", tz="UTC")),
            ("timestamp with time zone", pa.timestamp("us", tz="UTC")),
            ("interval", pa.duration("us")),
            ("boolean", pa.bool_()),
            ("bytea", pa.binary()),
            ("uuid", pa.string()),
            ("json", pa.string()),
            ("jsonb", pa.string()),
        ],
    )
    def test_type_mappings(self, data_type, expected_arrow_type):
        col = PostgreSQLColumn("test_col", data_type, nullable=True)
        field = col.to_arrow_field()
        assert field.type == expected_arrow_type
        assert field.name == "test_col"
        assert field.nullable is True

    def test_numeric_with_precision_and_scale(self):
        col = PostgreSQLColumn("price", "numeric", nullable=False, numeric_precision=10, numeric_scale=2)
        field = col.to_arrow_field()
        assert isinstance(field.type, pa.Decimal128Type)
        assert field.nullable is False

    def test_decimal_alias(self):
        col = PostgreSQLColumn("amount", "decimal", nullable=True, numeric_precision=18, numeric_scale=4)
        field = col.to_arrow_field()
        assert isinstance(field.type, pa.Decimal128Type)

    def test_numeric_raises_without_precision(self):
        col = PostgreSQLColumn("val", "numeric", nullable=True, numeric_precision=None, numeric_scale=None)
        with pytest.raises(TypeError, match="expected `numeric_precision` and `numeric_scale` to be `int`"):
            col.to_arrow_field()

    def test_numeric_raises_with_zero_precision(self):
        col = PostgreSQLColumn("val", "numeric", nullable=True, numeric_precision=0, numeric_scale=2)
        with pytest.raises(TypeError):
            col.to_arrow_field()

    def test_array_types_map_to_string(self):
        col = PostgreSQLColumn("tags", "text[]", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_integer_array(self):
        col = PostgreSQLColumn("ids", "integer[]", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_unknown_type_maps_to_string(self):
        col = PostgreSQLColumn("mystery", "citext", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()

    def test_nullable_false(self):
        col = PostgreSQLColumn("id", "integer", nullable=False)
        field = col.to_arrow_field()
        assert field.nullable is False


class TestJsonAsStringLoader:
    @pytest.fixture
    def loader(self):
        return JsonAsStringLoader(oid=114)

    def test_loads_json_bytes(self, loader):
        assert loader.load(b'{"key": "value"}') == '{"key": "value"}'

    def test_loads_empty_object(self, loader):
        assert loader.load(b"{}") == "{}"

    def test_loads_array(self, loader):
        assert loader.load(b"[1, 2, 3]") == "[1, 2, 3]"

    def test_none_returns_none(self, loader):
        assert loader.load(None) is None

    def test_loads_unicode(self, loader):
        result = loader.load("héllo".encode())
        assert result == "héllo"


class TestRangeAsStringLoader:
    @pytest.fixture
    def loader(self):
        return RangeAsStringLoader(oid=3904)

    def test_loads_range_bytes(self, loader):
        assert loader.load(b"[4,6)") == "[4,6)"

    def test_loads_empty_range(self, loader):
        assert loader.load(b"empty") == "empty"

    def test_none_returns_none(self, loader):
        assert loader.load(None) is None

    def test_loads_unbounded_range(self, loader):
        assert loader.load(b"[,10)") == "[,10)"


class TestSSLRequiredAfterDate:
    def test_date_value(self):
        assert SSL_REQUIRED_AFTER_DATE == datetime(2026, 2, 18, tzinfo=UTC)

    def test_timezone_aware(self):
        assert SSL_REQUIRED_AFTER_DATE.tzinfo is not None


class TestGetPrimaryKeys:
    @pytest.mark.django_db
    def test_returns_primary_keys_for_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_pk_table (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_pk_table", logger)
            assert result is not None
            assert "id" in result

    @pytest.mark.django_db
    def test_returns_none_for_table_without_primary_key(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_no_pk_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_no_pk_table", logger)
            assert result is None

    @pytest.mark.django_db
    def test_returns_composite_primary_keys(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_composite_pk_table (
                    org_id INTEGER,
                    user_id INTEGER,
                    name TEXT,
                    PRIMARY KEY (org_id, user_id)
                )
            """)
            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_composite_pk_table", logger)
            assert result is not None
            assert len(result) == 2
            assert "org_id" in result
            assert "user_id" in result

    @pytest.mark.django_db
    def test_returns_primary_keys_for_partitioned_parent_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_pk (
                    id INTEGER,
                    created_at DATE,
                    name TEXT,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_pk_2026
                PARTITION OF test_partitioned_parent_pk
                FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_parent_pk", logger)
            assert result is not None
            assert result == ["id", "created_at"]

    @pytest.mark.django_db
    def test_returns_primary_keys_for_partitioned_parent_when_only_children_have_pk(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk (
                    order_id INTEGER NOT NULL,
                    created_at DATE NOT NULL,
                    updated_at DATE NOT NULL
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk_2026_q1
                PARTITION OF test_partitioned_parent_no_pk
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_parent_no_pk_2026_q2
                PARTITION OF test_partitioned_parent_no_pk
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)

            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_parent_no_pk_2026_q1
                ADD CONSTRAINT test_partitioned_parent_no_pk_2026_q1_pkey PRIMARY KEY (order_id)
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_parent_no_pk_2026_q2
                ADD CONSTRAINT test_partitioned_parent_no_pk_2026_q2_pkey PRIMARY KEY (order_id)
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_parent_no_pk", logger)
            assert result is not None
            assert result == ["order_id"]

    @pytest.mark.django_db
    def test_returns_none_for_partitioned_parent_with_inconsistent_child_pks(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk (
                    col_a INTEGER NOT NULL,
                    col_b INTEGER NOT NULL,
                    created_at DATE NOT NULL
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk_q1
                PARTITION OF test_partitioned_inconsistent_pk
                FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')
            """)
            dj_cursor.execute("""
                CREATE TABLE test_partitioned_inconsistent_pk_q2
                PARTITION OF test_partitioned_inconsistent_pk
                FOR VALUES FROM ('2026-04-01') TO ('2026-07-01')
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_inconsistent_pk_q1
                ADD CONSTRAINT test_partitioned_inconsistent_pk_q1_pkey PRIMARY KEY (col_a)
            """)
            dj_cursor.execute("""
                ALTER TABLE ONLY test_partitioned_inconsistent_pk_q2
                ADD CONSTRAINT test_partitioned_inconsistent_pk_q2_pkey PRIMARY KEY (col_b)
            """)

            result = _get_primary_keys(cast(Any, dj_cursor), "public", "test_partitioned_inconsistent_pk", logger)
            assert result is None

    def test_reraises_connection_drop_during_child_partition_fallback(self):
        logger = structlog.get_logger()
        cursor = MagicMock()
        # Primary PK query returns no rows, so the child-partition fallback runs.
        cursor.fetchall.return_value = []
        # The fallback query then hits a transient connection drop. It must propagate to the setup
        # retry loop (stays retryable), not be swallowed as "no primary key" + captured as noise.
        cursor.execute.side_effect = [None, psycopg.OperationalError("the connection is lost")]
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}._explain_query"),
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            with pytest.raises(psycopg.OperationalError, match="the connection is lost"):
                _get_primary_keys(cast(Any, cursor), "public", "events", logger)
        mock_capture.assert_not_called()

    def test_captures_and_degrades_on_non_connection_error_in_child_partition_fallback(self):
        logger = structlog.get_logger()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        # A genuine query-incompatibility error in the best-effort fallback still degrades to
        # "no primary key" and is captured — only transient drops are re-raised.
        cursor.execute.side_effect = [None, psycopg.errors.UndefinedColumn("boom")]
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}._explain_query"),
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            result = _get_primary_keys(cast(Any, cursor), "public", "events", logger)
        assert result is None
        mock_capture.assert_called_once()


class TestGetLeadingIndexColumns:
    """Unit tests for the leading-index-column helper used to flag unindexed
    incremental fields in the source-setup wizard. The helper queries
    ``pg_index``/``pg_attribute``; we mock the cursor to verify that:
    - rows are bucketed by table
    - tables in the input list with no rows return empty sets (so the UI
      warning fires for tables without any indexes)
    - empty input is short-circuited
    """

    def _mock_connection(self, fetched_rows: list[tuple[str, str]]):
        cursor = mock.MagicMock()
        cursor.__iter__.return_value = iter(fetched_rows)

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None

        connection = mock.MagicMock()
        connection.cursor.return_value = cursor_context
        return connection, cursor

    def test_groups_columns_by_table(self):
        connection, _ = self._mock_connection(
            [
                ("orders", "created_at"),
                ("orders", "id"),
                ("users", "id"),
            ]
        )
        result = get_leading_index_columns(connection, "public", ["orders", "users", "logs"])
        assert result == {
            "orders": {"created_at", "id"},
            "users": {"id"},
        }
        assert "logs" not in result  # caller distinguishes "no index" via missing key

    def test_returns_empty_dict_for_empty_input(self):
        # No connection cursor should be opened when there are no tables.
        connection = mock.MagicMock()
        result = get_leading_index_columns(connection, "public", [])
        assert result == {}
        connection.cursor.assert_not_called()

    def test_returns_none_when_query_raises(self):
        # Permission errors on system catalogs (rare, but possible with
        # restricted roles) must not leak out — the caller defaults to
        # `is_indexed=True` and skips the warning when discovery fails.
        connection = mock.MagicMock()
        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("permission denied for table pg_index")

        cursor_context = mock.MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = None
        connection.cursor.return_value = cursor_context

        result = get_leading_index_columns(connection, "public", ["orders"])
        assert result is None


class TestHasDuplicatePrimaryKeys:
    @pytest.mark.django_db
    def test_returns_false_when_no_primary_keys(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            assert _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "any_table", None, logger) is False
            assert _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "any_table", [], logger) is False

    @pytest.mark.django_db
    def test_returns_false_when_no_duplicates(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_no_dup_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            dj_cursor.execute("INSERT INTO test_no_dup_table VALUES (1, 'a'), (2, 'b'), (3, 'c')")
            result = _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "test_no_dup_table", ["id"], logger)
            assert result is False

    @pytest.mark.django_db
    def test_returns_true_when_duplicates_exist(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_dup_table (
                    id INTEGER,
                    name TEXT
                )
            """)
            dj_cursor.execute("INSERT INTO test_dup_table VALUES (1, 'a'), (1, 'b'), (2, 'c')")
            result = _has_duplicate_primary_keys(cast(Any, dj_cursor), "public", "test_dup_table", ["id"], logger)
            assert result is True

    @parameterized.expand(
        [
            # postgres_fdw surfaces a saturated foreign server while executing the probe query: the
            # remote connection couldn't be established, so the probe never ran. Transient, stays
            # retryable — re-raised as its OperationalError base.
            (
                "connection_error",
                psycopg.errors.SqlclientUnableToEstablishSqlconnection(
                    'could not connect to server "posthog_fdw_payment"\n'
                    'DETAIL:  connection to server at "10.0.0.1", port 5432 failed: '
                    'FATAL:  too many connections for role "posthog_fdw_reader"'
                ),
                psycopg.OperationalError,
            ),
            # The sync role lacks SELECT on the table (SQLSTATE 42501). Already non-retryable via
            # get_non_retryable_errors, so the probe must propagate it rather than capture it.
            (
                "permission_denied",
                psycopg.errors.InsufficientPrivilege("permission denied for table orders"),
                psycopg.errors.InsufficientPrivilege,
            ),
        ]
    )
    def test_reraises_without_capturing(self, _name, side_effect, expected_exception):
        # A probe failure that means the query never ran, or that is already non-retryable, must
        # propagate — not be swallowed as "no duplicate keys" and captured as error-tracking noise.
        logger = structlog.get_logger()
        cursor = MagicMock()
        cursor.execute.side_effect = side_effect
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            with pytest.raises(expected_exception):
                _has_duplicate_primary_keys(cast(Any, cursor), "public", "orders", ["id"], logger)
        mock_capture.assert_not_called()

    def test_captures_and_returns_false_on_non_connection_error(self):
        logger = structlog.get_logger()
        cursor = MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedColumn('column "id" does not exist')
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as mock_capture:
            result = _has_duplicate_primary_keys(cast(Any, cursor), "public", "orders", ["id"], logger)
        assert result is False
        mock_capture.assert_called_once()


class TestIsReadReplica:
    @pytest.mark.django_db
    def test_primary_is_not_read_replica(self):
        with django_connection.cursor() as dj_cursor:
            result = _is_read_replica(cast(Any, dj_cursor))
            assert result is False


class _RecordingCursor:
    """Wraps a real cursor, recording executed SQL as text while delegating everything else."""

    def __init__(self, inner: Any, sink: list[str] | None = None):
        self._inner = inner
        self.executed: list[str] = sink if sink is not None else []

    def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            self.executed.append(query.as_string())
        except Exception:
            self.executed.append(str(query))
        return self._inner.execute(query, *args, **kwargs)

    def __enter__(self) -> "_RecordingCursor":
        self._inner.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._inner.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RecordingConnection:
    """Wraps a real connection so `_schemas_from_conn` runs against a recording cursor."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.executed: list[str] = []

    def cursor(self, *args: Any, **kwargs: Any) -> _RecordingCursor:
        return _RecordingCursor(self._inner.cursor(*args, **kwargs), self.executed)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TestGetTable:
    def teardown_method(self):
        # `_get_table` and `_schemas_from_conn` raise a session-level `statement_timeout` on the
        # connection (production opens and closes its own, so the GUC is discarded with it). Here
        # they run against the shared `django_connection`, which Postgres does not reset on
        # transaction rollback — reset it after every test so a raised timeout can't leak onto
        # later tests reusing the connection.
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("RESET statement_timeout")

    @pytest.mark.django_db
    def test_schema_discovery_raises_statement_timeout_before_any_probe(self):
        """`_get_table` raises a generous session-level `statement_timeout` before issuing any
        discovery query, so a short role/server default can't cancel discovery with QueryCanceled.
        The protection must precede every probe — the `pg_matviews`/`pg_views` lookups and the
        transaction `BEGIN` that scopes the metadata query both ran under the inherited short
        default before, which canceled the statement against pooled Postgres. Pin that the timeout
        is the first statement issued, ahead of the metadata SELECT it ultimately protects."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_timeout_scope (id INTEGER PRIMARY KEY, amount NUMERIC(10, 2))"
            )
            spy = _RecordingCursor(dj_cursor)
            table = _get_table(cast(Any, spy), "public", "test_get_table_timeout_scope", logger)

            # Real execution still succeeds and returns the expected columns.
            assert {c.name for c in table.columns} >= {"id", "amount"}

            set_timeout_idx = next(
                i
                for i, q in enumerate(spy.executed)
                if "statement_timeout" in q and str(METADATA_STATEMENT_TIMEOUT_MS) in q
            )
            # The protective timeout must come before the first discovery probe (the
            # `pg_matviews` lookup) and the metadata SELECT — not midway through, where a
            # short default would already have canceled an earlier statement.
            first_probe_idx = next(i for i, q in enumerate(spy.executed) if "pg_matviews" in q)
            info_schema_idx = next(
                i for i, q in enumerate(spy.executed) if "information_schema.columns" in q and "EXPLAIN" not in q
            )
            assert set_timeout_idx < first_probe_idx < info_schema_idx

    @pytest.mark.django_db
    def test_schemas_from_conn_runs_under_scoped_statement_timeout(self):
        """`_schemas_from_conn` (the discovery path `sync_new_schemas_activity` and credential
        validation use) raises statement_timeout before scanning the catalog, so a short
        role/server default can't cancel the `information_schema.columns` query with QueryCanceled
        on large schemas. Pin that the timeout is bumped before the column query runs."""
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_schemas_from_conn_timeout (id INTEGER PRIMARY KEY, name TEXT)")

        conn = _RecordingConnection(django_connection)
        discovered = _schemas_from_conn(cast(Any, conn), "public", ["test_schemas_from_conn_timeout"])

        assert "test_schemas_from_conn_timeout" in discovered
        assert {col[0] for col in discovered["test_schemas_from_conn_timeout"].columns} >= {"id", "name"}

        set_timeout_idx = next(
            i
            for i, q in enumerate(conn.executed)
            if "statement_timeout" in q and str(METADATA_STATEMENT_TIMEOUT_MS) in q
        )
        column_query_idx = next(i for i, q in enumerate(conn.executed) if "information_schema.columns" in q)
        assert set_timeout_idx < column_query_idx

    @pytest.mark.django_db
    def test_regular_table(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_get_table_regular (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    score DOUBLE PRECISION
                )
            """)
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_regular", logger)
            assert table.type == "table"
            col_names = [c.name for c in table.columns]
            assert "id" in col_names
            assert "name" in col_names
            assert "score" in col_names

    @pytest.mark.django_db
    def test_view(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_view_base (id INTEGER, name TEXT)")
            dj_cursor.execute("CREATE VIEW test_get_table_view AS SELECT * FROM test_get_table_view_base")
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_view", logger)
            assert table.type == "view"

    @pytest.mark.django_db
    def test_materialized_view(self):
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_matview_base (id INTEGER, val NUMERIC(10,2))")
            dj_cursor.execute(
                "CREATE MATERIALIZED VIEW test_get_table_matview AS SELECT * FROM test_get_table_matview_base"
            )
            table = _get_table(cast(Any, dj_cursor), "public", "test_get_table_matview", logger)
            assert table.type == "materialized_view"

    @pytest.mark.django_db
    def test_unconstrained_numeric_probe_gated_off_uses_default_scale(self):
        """When the caller doesn't request probing (the default), an unconstrained `numeric`
        column falls back to `DEFAULT_NUMERIC_SCALE` regardless of the actual data. This is the
        path used by incremental syncs where the delta column type is already set and probing
        would be a wasted full-table aggregation."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_probe_gated_off (id INTEGER PRIMARY KEY, val NUMERIC)")
            dj_cursor.execute("INSERT INTO test_get_table_probe_gated_off VALUES (1, 0.84497449830783164117::numeric)")
            # Explicitly omit `probe_unconstrained_numeric_scale` to exercise the default.
            table = _get_table(dj_cursor, "public", "test_get_table_probe_gated_off", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_scale == DEFAULT_NUMERIC_SCALE

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "inserts,expected_precision,expected_scale,expected_arrow_type",
        [
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 0.84497449830783164117::numeric)",
                    "INSERT INTO test_probe_scale VALUES (2, 0::numeric)",
                ],
                38,
                20,
                pa.decimal128(38, 20),
                id="fractional_fits_in_decimal128",
            ),
            pytest.param(
                [],
                38,
                DEFAULT_NUMERIC_SCALE,
                pa.decimal128(38, DEFAULT_NUMERIC_SCALE),
                id="empty_table_falls_back_to_default",
            ),
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 0.1234567890123456789012345678901234567890::numeric)",
                ],
                38,
                MAX_NUMERIC_SCALE,
                pa.decimal128(38, MAX_NUMERIC_SCALE),
                id="scale_past_max_clamped_with_small_int_still_fits",
            ),
            # Pins the intentional conservative behavior: all-integer data means MAX(scale(val))
            # returns 0, but we fall back to DEFAULT_NUMERIC_SCALE rather than freezing the delta
            # column at scale=0 — because the source column is unconstrained and a future sync
            # could legitimately carry fractional digits the delta column wouldn't be able to
            # hold. See the matching comment in postgres.py:_get_table.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 42::numeric)",
                    "INSERT INTO test_probe_scale VALUES (2, 1000::numeric)",
                ],
                38,
                DEFAULT_NUMERIC_SCALE,
                pa.decimal128(38, DEFAULT_NUMERIC_SCALE),
                id="integer_only_data_falls_back_to_default",
            ),
            # 8 integer digits + 30 fractional digits = 38 total, which is the `decimal128`
            # precision budget. Must fit without escalating.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 12345678.012345678901234567890123456789::numeric)",
                ],
                38,
                30,
                pa.decimal128(38, 30),
                id="total_exactly_at_decimal128_budget_fits",
            ),
            # 9 integer digits + 30 fractional digits = 39 total, one digit past the `decimal128`
            # budget. The column must escalate precision past 38 so `build_pyarrow_decimal_type`
            # promotes to `decimal256`; staying at (38, 30) would silently lose the leading integer
            # digit when the data is later cast to arrow.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 123456789.012345678901234567890123456789::numeric)",
                ],
                39,
                30,
                pa.decimal256(39, 30),
                id="integer_overflow_escalates_precision_past_38",
            ),
            # 10 integer digits + 32 fractional digits = 42 total. Scale is at MAX_NUMERIC_SCALE,
            # integer side is over budget. Must escalate precision to cover both dimensions.
            pytest.param(
                [
                    "INSERT INTO test_probe_scale VALUES (1, 1234567890.12345678901234567890123456789012::numeric)",
                ],
                42,
                MAX_NUMERIC_SCALE,
                pa.decimal256(42, MAX_NUMERIC_SCALE),
                id="both_dimensions_exceed_budget_escalates_precision",
            ),
        ],
    )
    def test_unconstrained_numeric_probe_dimensions(
        self,
        inserts: list[str],
        expected_precision: int,
        expected_scale: int,
        expected_arrow_type: pa.DataType,
    ):
        """Unconstrained `numeric` columns probe both fractional scale and integer digits so the
        resulting decimal type has enough precision to hold the observed data. When total digits
        exceed `decimal128`'s 38-digit budget, precision must escalate past 38 so
        `build_pyarrow_decimal_type` promotes the column to `decimal256` (which delta-rs will then
        collapse to `string` at write). Freezing at `decimal128(38, scale)` silently truncates
        either fractional digits (original bug pre-PR) or integer digits (regression introduced by
        the single-dimension probe)."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_probe_scale (id INTEGER PRIMARY KEY, val NUMERIC)")
            for insert_sql in inserts:
                dj_cursor.execute(insert_sql)

            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_probe_scale",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == expected_precision
            assert val_col.numeric_scale == expected_scale
            # Guard the full schema conversion too — catches regressions where precision/scale
            # look right on the PostgreSQLColumn but the arrow type flips (e.g. decimal128 vs
            # decimal256). The expected type is explicit per case rather than derived from
            # `build_pyarrow_decimal_type(precision, scale)` so each case locks in its intended
            # arrow width at the parameter level.
            assert val_col.to_arrow_field().type == expected_arrow_type

    @pytest.mark.django_db
    def test_constrained_numeric_skips_probe(self):
        """Columns declared with explicit precision/scale use those values directly, no data probe."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_constrained_numeric (id INTEGER PRIMARY KEY, val NUMERIC(10, 2))"
            )
            # Even though there's no data, the declared scale is used — no probe attempted.
            table = _get_table(dj_cursor, "public", "test_get_table_constrained_numeric", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == 10
            assert val_col.numeric_scale == 2

    @pytest.mark.django_db
    def test_constrained_numeric_zero_scale_survives_schema_conversion(self):
        """Declared `NUMERIC(X, 0)` columns must be convertible to an arrow schema without tripping
        the legacy truthy-check guard in `PostgreSQLColumn.to_arrow_field`."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_get_table_zero_scale (id INTEGER PRIMARY KEY, val NUMERIC(10, 0))")
            table = _get_table(dj_cursor, "public", "test_get_table_zero_scale", logger)  # type: ignore[arg-type]
            val_col = next(c for c in table.columns if c.name == "val")
            assert val_col.numeric_precision == 10
            assert val_col.numeric_scale == 0
            # Must not raise — the full schema conversion is the actual regression surface.
            arrow_schema = table.to_arrow_schema()
            assert pa.types.is_decimal(arrow_schema.field("val").type)

    @pytest.mark.django_db
    def test_unconstrained_numeric_on_view_skips_probe(self):
        """`MAX(scale(col))` on a regular view forces the view definition to execute, which
        can be arbitrarily expensive for join/aggregate views. The probe is skipped for views
        regardless of the caller's probe flag, and falls back to DEFAULT_NUMERIC_SCALE.
        The downstream `_process_batch` fallback chain handles scale inference at row time."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_view_unconstrained_base (id INTEGER PRIMARY KEY, val NUMERIC)"
            )
            dj_cursor.execute(
                "INSERT INTO test_get_table_view_unconstrained_base VALUES (1, 0.84497449830783164117::numeric)"
            )
            dj_cursor.execute(
                "CREATE VIEW test_get_table_view_unconstrained AS SELECT * FROM test_get_table_view_unconstrained_base"
            )
            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_get_table_view_unconstrained",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            assert table.type == "view"
            val_col = next(c for c in table.columns if c.name == "val")
            # Probe was skipped for the view → default scale, even though the base table has
            # scale-20 data that a probe would have found.
            assert val_col.numeric_scale == DEFAULT_NUMERIC_SCALE

    @pytest.mark.django_db
    def test_unconstrained_numeric_multiple_columns_probed_together(self):
        """Multiple unconstrained numeric columns are probed in a single aggregation query."""
        logger = structlog.get_logger()

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(
                "CREATE TABLE test_get_table_multi_numeric "
                "(id INTEGER PRIMARY KEY, a NUMERIC, b NUMERIC, c NUMERIC(5, 2))"
            )
            dj_cursor.execute(
                "INSERT INTO test_get_table_multi_numeric VALUES "
                "(1, 0.12345::numeric, 0.1234567890::numeric, 1.23::numeric(5,2))"
            )
            table = _get_table(
                dj_cursor,  # type: ignore[arg-type]
                "public",
                "test_get_table_multi_numeric",
                logger,
                probe_unconstrained_numeric_scale=True,
            )
            cols_by_name = {c.name: c for c in table.columns}
            assert cols_by_name["a"].numeric_scale == 5
            assert cols_by_name["b"].numeric_scale == 10
            # Constrained column is untouched.
            assert cols_by_name["c"].numeric_precision == 5
            assert cols_by_name["c"].numeric_scale == 2


class TestBuildQueryUpperBound:
    def test_includes_inclusive_upper_bound(self):
        q = _build_query(
            "public",
            "t",
            should_use_incremental_field=True,
            table_type="table",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=datetime(2026, 1, 1),
            upper_bound_inclusive=datetime(2026, 1, 2),
        )
        rendered = q.as_string()
        assert '"created_at" > ' in rendered
        assert '"created_at" <= ' in rendered
        assert 'ORDER BY "created_at" ASC' in rendered

    def test_skips_upper_bound_when_not_provided(self):
        q = _build_query(
            "public",
            "t",
            should_use_incremental_field=True,
            table_type="table",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=datetime(2026, 1, 1),
        )
        rendered = q.as_string()
        assert '"created_at" <= ' not in rendered
        assert 'ORDER BY "created_at" ASC' in rendered


class TestPartitionBoundsForRange:
    @pytest.mark.parametrize(
        "partbound,field_type,expected",
        [
            (
                "FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')",
                IncrementalFieldType.Date,
                (date(2026, 1, 1), date(2026, 2, 1)),
            ),
            (
                "FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-02-01 00:00:00')",
                IncrementalFieldType.DateTime,
                (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
            ),
            ("FOR VALUES FROM (100) TO (200)", IncrementalFieldType.Integer, (100, 200)),
            ("FOR VALUES FROM (MINVALUE) TO ('2026-01-01')", IncrementalFieldType.Date, None),
            ("FOR VALUES FROM ('2026-01-01') TO (MAXVALUE)", IncrementalFieldType.Date, None),
            ("DEFAULT", IncrementalFieldType.Date, None),
            ("FOR VALUES IN ('a', 'b')", IncrementalFieldType.Date, None),
            ("FOR VALUES WITH (modulus 4, remainder 0)", IncrementalFieldType.Integer, None),
        ],
    )
    def test_parses(self, partbound, field_type, expected):
        child = ChildPartition(oid=1, schema="public", name="p", partbound=partbound)
        assert partition_bounds_for_range(child, field_type) == expected


class TestDeriveUpperBound:
    def test_prefers_range_hi_when_available(self):
        bounds = [(date(2026, 1, 1), date(2026, 2, 1)), (date(2026, 2, 1), date(2026, 3, 1))]
        assert derive_upper_bound(IncrementalFieldType.Date, bounds) == date(2026, 3, 1)

    @freeze_time("2026-04-20T12:00:00Z")
    def test_uses_now_for_datetime_without_bounds(self):
        out = derive_upper_bound(IncrementalFieldType.DateTime, [])
        assert out == datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

    def test_returns_none_for_numeric_without_bounds(self):
        assert derive_upper_bound(IncrementalFieldType.Integer, []) is None
        assert derive_upper_bound(IncrementalFieldType.Numeric, []) is None


class TestShouldPreserveAscSort:
    def test_true_for_range_on_incremental_field(self):
        strat = PartitionStrategy(strategy="r", key_columns=("created_at",))
        assert should_preserve_asc_sort(strat, "created_at") is True

    def test_false_for_range_on_different_field(self):
        strat = PartitionStrategy(strategy="r", key_columns=("region",))
        assert should_preserve_asc_sort(strat, "created_at") is False

    def test_false_for_hash_partitioning(self):
        strat = PartitionStrategy(strategy="h", key_columns=("id",))
        assert should_preserve_asc_sort(strat, "id") is False

    def test_true_without_strategy_info(self):
        assert should_preserve_asc_sort(None, "created_at") is True


class TestIsSupportedIncrementalTypeForWindow:
    @pytest.mark.parametrize(
        "field_type,expected",
        [
            (IncrementalFieldType.Date, True),
            (IncrementalFieldType.DateTime, True),
            (IncrementalFieldType.Timestamp, True),
            (IncrementalFieldType.Integer, True),
            (IncrementalFieldType.Numeric, True),
            (IncrementalFieldType.ObjectID, False),
            (None, False),
        ],
    )
    def test_matrix(self, field_type, expected):
        assert is_supported_incremental_type_for_window(field_type) is expected


class TestListChildPartitionsAndStrategy:
    @pytest.mark.django_db
    def test_lists_children_and_strategy(self):
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_lcp_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_lcp_2026_01 PARTITION OF test_lcp_parent "
                "FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_lcp_2026_02 PARTITION OF test_lcp_parent "
                "FOR VALUES FROM ('2026-02-01') TO ('2026-03-01')"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_lcp_parent")
            names = {c.name for c in children}
            assert names == {"test_lcp_2026_01", "test_lcp_2026_02"}
            # All children have parseable range bounds
            for c in children:
                assert partition_bounds_for_range(c, IncrementalFieldType.Date) is not None

            strat = get_partition_strategy(cast(Any, dj_cursor), "public", "test_lcp_parent")
            assert strat is not None
            assert strat.strategy == "r"
            assert strat.key_columns == ("created_at",)

    @pytest.mark.django_db
    def test_returns_none_for_non_partitioned(self):
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_lcp_regular (id SERIAL PRIMARY KEY, data TEXT)")
            assert get_partition_strategy(cast(Any, dj_cursor), "public", "test_lcp_regular") is None
            assert list_child_partitions(cast(Any, dj_cursor), "public", "test_lcp_regular") == []


# ---- Fake connection infrastructure for deterministic iterate_date_windows tests ----


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeCursor:
    """Minimal psycopg cursor stand-in.

    Each invocation of iterate_date_windows opens a fresh cursor; `script` is a
    list of per-cursor behaviors. A behavior is one of:
      - list[tuple]  → rows returned from fetchmany, then []
      - list whose last element is an Exception → those rows are returned from
        fetchmany, then the exception is raised on the next fetch (models a drop
        mid-stream, after some chunks have already been yielded)
      - Exception instance → raised from execute()
    """

    def __init__(self, owner: "_FakeConnection", behaviour):
        self.owner = owner
        self.behaviour = behaviour
        self.description = [mock.Mock(name="col1"), mock.Mock(name="col2")]
        self.description[0].name = "id"
        self.description[1].name = "val"
        self._rows_remaining: list = []
        self._fetch_error: Exception | None = None
        self._executed = False

    def execute(self, query):
        self.owner.executed_queries.append(query)
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        rows = list(self.behaviour)
        if rows and isinstance(rows[-1], Exception):
            self._fetch_error = rows.pop()
        self._rows_remaining = rows
        self._executed = True

    def fetchmany(self, n: int):
        if not self._executed:
            return []
        batch, self._rows_remaining = self._rows_remaining[:n], self._rows_remaining[n:]
        if not batch and self._fetch_error is not None:
            raise self._fetch_error
        return batch

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConnection:
    def __init__(self, owner: "_FakeConnectionFactory"):
        self.owner = owner
        self.executed_queries: list = []

    def cursor(self, *args, **kwargs):
        # Pop the next behaviour off the factory's script
        behaviour = self.owner.script.pop(0) if self.owner.script else []
        cur = _FakeCursor(self, behaviour)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def closed(self):
        return False


class _FakeConnectionFactory:
    def __init__(self, script: list):
        self.script = script
        self.connections_opened = 0
        self.connections: list[_FakeConnection] = []

    def __call__(self) -> _FakeConnection:
        self.connections_opened += 1
        conn = _FakeConnection(self)
        self.connections.append(conn)
        return conn

    def all_executed_queries(self) -> list[str]:
        return [
            q.as_string() if hasattr(q, "as_string") else str(q) for c in self.connections for q in c.executed_queries
        ]


def _arrow_schema() -> pa.Schema:
    fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("val", pa.int64())]
    return pa.schema(fields)


def _build_fake_query(lo, hi):
    return sql.SQL("SELECT * FROM t WHERE x > {lo} AND x <= {hi}").format(lo=sql.Literal(lo), hi=sql.Literal(hi))


def _run_windows(script, **overrides):
    factory = _FakeConnectionFactory(script)
    kwargs: dict[str, Any] = {
        "get_connection": cast(Any, factory),
        "build_windowed_query": _build_fake_query,
        "schema": "public",
        "table_name": "t",
        "incremental_field": "x",
        "incremental_field_type": IncrementalFieldType.Date,
        "db_incremental_field_last_value": date(2026, 1, 1),
        "child_partitions": [],
        "chunk_size": 1000,
        "arrow_schema": _arrow_schema(),
        "logger": structlog.get_logger(),
        "initial_window": timedelta(days=1),
        "clock": _FakeClock(),
        "sleeper": lambda _s: None,
    }
    kwargs.update(overrides)
    # Give the test a deterministic finite range by forcing upper via a time-based field
    # + partition bounds argument. Tests that need an explicit upper pass child_partitions.
    return list(iterate_date_windows(**kwargs)), factory


class TestIterateDateWindowsFake:
    def test_single_window_yields_rows(self):
        # One partition covering one day → one window, 3 rows
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        tables, factory = _run_windows(
            script=[[(1, 10), (2, 20), (3, 30)]],
            child_partitions=[child],
        )
        assert factory.connections_opened == 1
        total = sum(t.num_rows for t in tables)
        assert total == 3

    def test_handles_naive_cursor_against_aware_partition_bounds(self):
        # Pipeline can persist the incremental cursor as a naive datetime, but
        # partition bounds parsed from the catalog are always UTC-aware. The
        # walker must coerce naive->aware before comparing or Python raises
        # `can't compare offset-naive and offset-aware datetimes`.
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01 00:00:00') TO ('2026-01-02 00:00:00')",
        )
        factory = _FakeConnectionFactory([[(1, 10)]])
        tables = list(
            iterate_date_windows(
                get_connection=cast(Any, factory),
                build_windowed_query=_build_fake_query,
                schema="public",
                table_name="t",
                incremental_field="x",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value=datetime(2025, 12, 31, 23, 59, 59),  # naive!
                child_partitions=[child],
                chunk_size=1000,
                arrow_schema=_arrow_schema(),
                logger=structlog.get_logger(),
                initial_window=timedelta(days=1),
                clock=_FakeClock(),
                sleeper=lambda _s: None,
            )
        )
        assert sum(t.num_rows for t in tables) == 1

    def test_walks_multiple_windows(self):
        # Two partitions, each 1 day; with initial_window=1 day, expect two windows.
        children = [
            ChildPartition(
                oid=1,
                schema="public",
                name="p1",
                partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
            ),
            ChildPartition(
                oid=2,
                schema="public",
                name="p2",
                partbound="FOR VALUES FROM ('2026-01-02') TO ('2026-01-03')",
            ),
        ]
        tables, factory = _run_windows(
            script=[[(1, 10)], [(2, 20)]],
            child_partitions=children,
            db_incremental_field_last_value=date(2026, 1, 1),
        )
        assert factory.connections_opened == 2
        assert sum(t.num_rows for t in tables) == 2

    def test_shrinks_and_retries_on_query_canceled(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        # QueryCanceled once -> shrink + retry -> succeeds -> walker may continue
        # through the remaining range. We only care that retries happened and rows came back.
        script = [psycopg.errors.QueryCanceled("timeout"), [(1, 10)], [], []]
        tables, factory = _run_windows(script=script, child_partitions=[child])
        assert factory.connections_opened >= 2
        assert sum(t.num_rows for t in tables) == 1

    def test_raises_query_timeout_after_budget_exhausted(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        # Fail every attempt; iterator must raise QueryTimeoutException.
        script = [psycopg.errors.QueryCanceled("timeout")] * (WINDOW_MAX_QUERY_CANCELED_RETRIES + 2)
        with pytest.raises(QueryTimeoutException):
            list(
                iterate_date_windows(
                    get_connection=cast(Any, _FakeConnectionFactory(script)),
                    build_windowed_query=_build_fake_query,
                    schema="public",
                    table_name="t",
                    incremental_field="x",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2026, 1, 1),
                    child_partitions=[child],
                    chunk_size=1000,
                    arrow_schema=_arrow_schema(),
                    logger=structlog.get_logger(),
                    initial_window=timedelta(days=1),
                    clock=_FakeClock(),
                    sleeper=lambda _s: None,
                )
            )

    def test_raises_after_max_serialization_retries_on_replica(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        conflict_err = psycopg.errors.SerializationFailure("due to conflict with recovery")
        script = [conflict_err] * (WINDOW_MAX_SERIALIZATION_RETRIES + 2)

        with pytest.raises(psycopg.errors.SerializationFailure):
            list(
                iterate_date_windows(
                    get_connection=cast(Any, _FakeConnectionFactory(script)),
                    build_windowed_query=_build_fake_query,
                    schema="public",
                    table_name="t",
                    incremental_field="x",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2026, 1, 1),
                    child_partitions=[child],
                    chunk_size=1000,
                    arrow_schema=_arrow_schema(),
                    logger=structlog.get_logger(),
                    initial_window=timedelta(days=1),
                    clock=_FakeClock(),
                    sleeper=lambda _s: None,
                    using_read_replica=True,
                )
            )

    def test_reconnects_and_retries_window_on_connection_drop_before_rows(self):
        # A mid-stream drop on the windowed read path used to escape uncaught and fail the whole
        # activity (ProtocolViolation "server conn crashed?"). When it fires before any chunk of the
        # window is yielded, replaying the window is safe, so the walker reconnects and resumes.
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        script = [psycopg.errors.ProtocolViolation("server conn crashed?"), [(1, 10)], [], []]
        tables, factory = _run_windows(
            script=script,
            child_partitions=[child],
            is_connection_dropped=_is_connection_dropped_error,
        )
        assert factory.connections_opened >= 2
        assert sum(t.num_rows for t in tables) == 1

    def test_reraises_connection_drop_after_rows_yielded(self):
        # Once a chunk of the window is out, replaying it would duplicate rows — so a drop mid-window
        # must propagate rather than retry.
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        script = [[(1, 10), psycopg.errors.ProtocolViolation("server conn crashed?")]]
        with pytest.raises(psycopg.errors.ProtocolViolation):
            _run_windows(
                script=script,
                child_partitions=[child],
                is_connection_dropped=_is_connection_dropped_error,
            )

    def test_raises_after_max_connection_drop_retries(self):
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        script = [psycopg.errors.ProtocolViolation("server conn crashed?")] * (WINDOW_MAX_CONNECTION_DROP_RETRIES + 2)
        with pytest.raises(psycopg.errors.ProtocolViolation):
            _run_windows(
                script=script,
                child_partitions=[child],
                is_connection_dropped=_is_connection_dropped_error,
            )

    def test_does_not_set_per_window_statement_timeout(self):
        """Critical: this is the user's explicit requirement — no tightened timeout."""
        child = ChildPartition(
            oid=1,
            schema="public",
            name="p",
            partbound="FOR VALUES FROM ('2026-01-01') TO ('2026-01-02')",
        )
        script = [[(1, 10)]]
        factory = _FakeConnectionFactory(script)
        list(
            iterate_date_windows(
                get_connection=cast(Any, factory),
                build_windowed_query=_build_fake_query,
                schema="public",
                table_name="t",
                incremental_field="x",
                incremental_field_type=IncrementalFieldType.Date,
                db_incremental_field_last_value=date(2026, 1, 1),
                child_partitions=[child],
                chunk_size=1000,
                arrow_schema=_arrow_schema(),
                logger=structlog.get_logger(),
                initial_window=timedelta(days=1),
                clock=_FakeClock(),
                sleeper=lambda _s: None,
            )
        )
        # Inspect every query issued across all opened connections — none must
        # be a `SET statement_timeout` statement. The connection-level 10-min
        # backstop set in postgres_source.get_connection is the only timeout.
        all_queries = factory.all_executed_queries()
        assert all_queries, "expected at least one query to be executed"
        assert not any("statement_timeout" in q.lower() for q in all_queries), (
            f"iterate_date_windows must not tighten statement_timeout per window; queries: {all_queries}"
        )


class TestIterateDateWindowsRealDb:
    @pytest.mark.django_db
    def test_yields_all_rows_over_partitioned_table(self):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_idw_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    val INTEGER,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_idw_p1 PARTITION OF test_idw_parent FOR VALUES FROM ('2026-01-01') TO ('2026-01-04')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_idw_p2 PARTITION OF test_idw_parent FOR VALUES FROM ('2026-01-04') TO ('2026-01-07')"
            )
            dj_cursor.execute(
                "INSERT INTO test_idw_parent (created_at, val) "
                "SELECT '2026-01-01'::date + (g % 6) * interval '1 day', g "
                "FROM generate_series(1, 60) g"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_idw_parent")
            idw_fields: list[pa.Field] = [
                pa.field("id", pa.int64()),
                pa.field("created_at", pa.date32()),
                pa.field("val", pa.int64()),
            ]
            schema = pa.schema(idw_fields)

            def get_connection():
                # Hand out the Django-bound psycopg connection. The tests run in a
                # single transaction so a fresh psycopg.connect would not see the
                # CREATE/INSERT above. Wrap Django's connection in a shim that
                # returns the same raw cursor each time and no-ops __exit__.
                return _DjangoBackedConnection(dj_cursor)

            def build_q(lo, hi):
                return _build_query(
                    "public",
                    "test_idw_parent",
                    should_use_incremental_field=True,
                    table_type="table",
                    incremental_field="created_at",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=lo,
                    upper_bound_inclusive=hi,
                )

            tables = list(
                iterate_date_windows(
                    get_connection=get_connection,
                    build_windowed_query=build_q,
                    schema="public",
                    table_name="test_idw_parent",
                    incremental_field="created_at",
                    incremental_field_type=IncrementalFieldType.Date,
                    db_incremental_field_last_value=date(2025, 12, 31),
                    child_partitions=children,
                    chunk_size=100,
                    arrow_schema=schema,
                    logger=logger,
                    initial_window=timedelta(days=1),
                )
            )
            total = sum(t.num_rows for t in tables)
            assert total == 60


class _DjangoBackedConnection:
    """Shim wrapping a Django cursor for tests that must see uncommitted rows.

    Named cursors go through the same raw psycopg cursor, so we just alias it.
    """

    def __init__(self, dj_cursor):
        self._dj_cursor = dj_cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return _DjangoBackedCursorCtx(self._dj_cursor)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _DjangoBackedCursorCtx:
    def __init__(self, dj_cursor):
        self._dj_cursor = dj_cursor

    def __enter__(self):
        return self._dj_cursor

    def __exit__(self, *args):
        return False


class TestIteratePartitionsRealDb:
    @pytest.mark.django_db
    def test_yields_all_rows(self):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("""
                CREATE TABLE test_ip_parent (
                    id BIGSERIAL,
                    created_at DATE NOT NULL,
                    val INTEGER,
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """)
            dj_cursor.execute(
                "CREATE TABLE test_ip_p1 PARTITION OF test_ip_parent FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')"
            )
            dj_cursor.execute(
                "CREATE TABLE test_ip_p2 PARTITION OF test_ip_parent FOR VALUES FROM ('2026-02-01') TO ('2026-03-01')"
            )
            dj_cursor.execute(
                "INSERT INTO test_ip_parent (created_at, val) "
                "SELECT '2026-01-01'::date + (g % 40) * interval '1 day', g "
                "FROM generate_series(1, 80) g"
            )

            children = list_child_partitions(cast(Any, dj_cursor), "public", "test_ip_parent")
            ip_fields: list[pa.Field] = [
                pa.field("id", pa.int64()),
                pa.field("created_at", pa.date32()),
                pa.field("val", pa.int64()),
            ]
            arrow_schema = pa.schema(ip_fields)

            def build_q(child_schema, child_name):
                return sql.SQL("SELECT id, created_at, val FROM {s}.{t} ORDER BY id ASC").format(
                    s=sql.Identifier(child_schema), t=sql.Identifier(child_name)
                )

            def get_connection():
                return _DjangoBackedConnection(dj_cursor)

            tables = list(
                iterate_partitions(
                    get_connection=get_connection,
                    build_partition_query=build_q,
                    schema="public",
                    table_name="test_ip_parent",
                    child_partitions=children,
                    chunk_size=100,
                    arrow_schema=arrow_schema,
                    logger=logger,
                )
            )
            assert sum(t.num_rows for t in tables) == 80


class TestRlsDetectionRealDb:
    def _create_table(self, cursor, *, rls_active: bool) -> None:
        cursor.execute("CREATE TABLE test_rls_param (id SERIAL PRIMARY KEY, user_id INTEGER)")
        if not rls_active:
            return
        cursor.execute("ALTER TABLE test_rls_param ENABLE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE test_rls_param FORCE ROW LEVEL SECURITY")
        cursor.execute("CREATE POLICY test_rls_param_policy ON test_rls_param USING (false)")
        # FORCE subjects a non-superuser owner directly; a superuser bypasses even FORCE, so observe
        # via a freshly created unprivileged role (a superuser can always create one).
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if cursor.fetchone()[0]:
            cursor.execute("CREATE ROLE test_rls_param_role NOLOGIN")
            cursor.execute("GRANT SELECT ON test_rls_param TO test_rls_param_role")
            cursor.execute("SET LOCAL ROLE test_rls_param_role")

    @pytest.mark.parametrize("rls_active,expected", [(False, False), (True, True)])
    @pytest.mark.django_db
    def test_role_subject_to_rls(self, rls_active, expected):
        logger = structlog.get_logger()
        with django_connection.cursor() as dj_cursor:
            self._create_table(dj_cursor, rls_active=rls_active)
            try:
                assert _role_subject_to_rls(cast(Any, dj_cursor), "public", "test_rls_param", logger) is expected
            finally:
                dj_cursor.execute("RESET ROLE")

    @pytest.mark.parametrize("rls_active,expected", [(False, False), (True, True)])
    @pytest.mark.django_db
    def test_rls_active_from_conn(self, rls_active, expected):
        with django_connection.cursor() as dj_cursor:
            self._create_table(dj_cursor, rls_active=rls_active)
            try:
                result = _rls_active_from_conn(
                    cast(Any, _DjangoBackedConnection(dj_cursor)), "public", ["test_rls_param"]
                )
                assert result == {"test_rls_param": expected}
            finally:
                dj_cursor.execute("RESET ROLE")

    @pytest.mark.django_db
    def test_rls_active_from_conn_runs_without_schema_or_names(self):
        # Regression: an early-return guard used to bail when no schema and no names were given,
        # silently dropping every RLS warning in multi-schema discovery. The full table list must
        # still be checked, so the table appears in the result (keyed by its qualified name).
        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute("CREATE TABLE test_rls_noschema (id SERIAL PRIMARY KEY)")
            result = _rls_active_from_conn(cast(Any, _DjangoBackedConnection(dj_cursor)), "", None)
            assert "public.test_rls_noschema" in result


# Message a DuckDB/Flight-SQL-backed Postgres-wire engine returns when `row_security_active` is
# absent — the engine accepts the connection but lacks the Postgres-only catalog function.
_FLIGHT_MISSING_FUNCTION_MSG = (
    "flight execute: rpc error: code = InvalidArgument desc = failed to prepare query: "
    "Catalog Error: Scalar Function with name row_security_active does not exist!"
)


class TestIsUnsupportedFunctionError:
    @pytest.mark.parametrize(
        "error,expected",
        [
            (psycopg.errors.InternalError(_FLIGHT_MISSING_FUNCTION_MSG), True),
            (Exception('function "row_security_active" does not exist'), True),
            (Exception("Unknown function: row_security_active"), True),
            # Real Postgres raises UndefinedFunction (SQLSTATE 42883) — recognised by type alone.
            (psycopg.errors.UndefinedFunction("function row_security_active(oid) does not exist"), True),
            # Different function missing -> not our concern, should still be captured.
            (Exception("function some_other_func does not exist"), False),
            # A genuine permission error mentioning the function must NOT be swallowed.
            (Exception("permission denied for function row_security_active"), False),
            (Exception("connection reset by peer"), False),
        ],
    )
    def test_recognises_missing_function(self, error, expected):
        assert _is_unsupported_function_error(error, "row_security_active") is expected


class TestRlsActiveFromConnErrorHandling:
    @staticmethod
    def _conn_raising(exc: Exception):
        conn = mock.MagicMock()
        conn.closed = False
        conn.broken = False
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = exc
        return conn

    def test_unsupported_function_error_is_not_captured(self):
        # A Postgres-wire engine without `row_security_active` is an expected shape: degrade to no
        # RLS warnings without flooding error tracking.
        conn = self._conn_raising(psycopg.errors.InternalError(_FLIGHT_MISSING_FUNCTION_MSG))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_not_called()

    def test_unexpected_error_is_still_captured(self):
        conn = self._conn_raising(Exception("connection reset by peer"))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_called_once()

    def test_failed_sql_transaction_is_not_captured(self):
        # This lookup shares a connection with earlier best-effort metadata queries (PK + index
        # discovery). When one of those fails on a non-Postgres engine (e.g. Redshift) its exception
        # is caught upstream but leaves the transaction aborted, so our first statement here raises
        # InFailedSqlTransaction as a downstream symptom. That's already handled, not a bug — don't
        # flood error tracking with it.
        conn = self._conn_raising(
            psycopg.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            )
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_not_called()

    @pytest.mark.parametrize("attr", ["closed", "broken"])
    def test_dropped_connection_is_not_captured(self, attr):
        # The shared connection can be dropped by an earlier best-effort probe or a transient blip
        # (SSH-tunnel hiccup, idle cull), so our `cursor()` call raises `OperationalError: the
        # connection is closed`. That's a downstream symptom the caller already degrades quietly —
        # don't flood error tracking with it.
        conn = mock.MagicMock()
        conn.closed = False
        conn.broken = False
        setattr(conn, attr, True)
        conn.cursor.side_effect = psycopg.OperationalError("the connection is closed")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.capture_exception"
        ) as capture_mock:
            result = _rls_active_from_conn(cast(Any, conn), "public", ["t"])
        assert result == {}
        capture_mock.assert_not_called()


class TestGetRowsInitialConnectRetry:
    # Regression: the main server-cursor read path opened its initial connection with a bare
    # get_connection(), so a transient "server closed the connection unexpectedly" while
    # establishing that connection escaped and failed the whole sync — even though every other
    # read path already recovers in-process via _connect_with_dropped_retry. Wrapping the initial
    # connect in the same helper makes a transient drop retry instead of aborting.
    @pytest.mark.django_db(transaction=True)
    def test_initial_connect_retries_transient_drop(self):
        table_name = "test_initial_connect_retry"
        sd = django_connection.settings_dict

        with django_connection.cursor() as dj_cursor:
            dj_cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            dj_cursor.execute(f"CREATE TABLE {table_name} (id BIGSERIAL PRIMARY KEY, val TEXT)")
            dj_cursor.execute(f"INSERT INTO {table_name} (val) SELECT 'v' || g FROM generate_series(1, 5) g")

        @contextmanager
        def tunnel():
            yield (sd["HOST"] or "localhost", int(sd["PORT"]) if sd["PORT"] else 5432)

        real_connect = psycopg.connect

        def plain_connect(*args, **kwargs):
            # The production connect passes dummy SSL cert paths ("/tmp/no.txt"); strip the SSL
            # kwargs so the read path can reach the local test DB while we exercise the retry.
            for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
                kwargs.pop(key, None)
            return real_connect(*args, **kwargs)

        logger = structlog.get_logger()

        try:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
                side_effect=plain_connect,
            ):
                response = postgres_source(
                    tunnel=tunnel,
                    user=sd["USER"] or "",
                    password=sd["PASSWORD"] or "",
                    database=sd["NAME"],
                    sslmode="prefer",
                    schema="public",
                    table_names=[table_name],
                    should_use_incremental_field=False,
                    logger=logger,
                    db_incremental_field_last_value=None,
                    team_id=1,
                )

            connect_calls = {"n": 0}

            def flaky_connect(*args, **kwargs):
                connect_calls["n"] += 1
                if connect_calls["n"] == 1:
                    # The exact production failure: a transient drop while establishing the read
                    # connection (here, the local 127.0.0.1 tunnel endpoint).
                    raise psycopg.OperationalError(
                        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
                        "server closed the connection unexpectedly"
                    )
                return plain_connect(*args, **kwargs)

            with (
                patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"),
                patch(
                    "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.psycopg.connect",
                    side_effect=flaky_connect,
                ),
            ):
                tables = list(cast(Iterable[Any], response.items()))

            assert connect_calls["n"] >= 2, "initial connect should have been retried after the transient drop"
            assert sum(table.num_rows for table in tables) == 5
        finally:
            with django_connection.cursor() as dj_cursor:
                dj_cursor.execute(f"DROP TABLE IF EXISTS {table_name}")


class TestGetRowsInitialReadDropRetry:
    # Regression: the main server-cursor read wrapped only the *connect* in
    # _connect_with_dropped_retry, so a transient drop during the server-cursor DECLARE
    # (cursor.execute) — before any row is yielded — escaped and failed the whole sync on a
    # full-table scan, which has no stable ORDER BY and so can't resume via offset_chunking. At
    # offset 0 nothing has been emitted, so re-running the read from scratch is safe and it should
    # retry in process. Once a chunk is out, replaying it would duplicate rows, so the drop must
    # still propagate.
    _DROP = "consuming input failed: SSL connection has been closed unexpectedly"

    class _Cursor:
        def __init__(self, *, batches, drop_on_execute):
            col = mock.Mock()
            col.name = "id"
            self.description = [col]
            self._batches = list(batches)
            self._drop_on_execute = drop_on_execute

        def execute(self, *args, **kwargs):
            if self._drop_on_execute:
                raise psycopg.OperationalError(TestGetRowsInitialReadDropRetry._DROP)
            return None

        def fetchmany(self, _n):
            if not self._batches:
                return []
            batch = self._batches.pop(0)
            if isinstance(batch, BaseException):
                raise batch
            return batch

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Connection:
        def __init__(self, *, batches, drop_on_execute):
            self.autocommit = False
            self.closed = False
            self.broken = False
            self.adapters = mock.Mock()
            self._batches = batches
            self._drop_on_execute = drop_on_execute

        def cursor(self, *args, **kwargs):
            # The named cursor is the streaming server cursor under test; the unnamed setup cursor
            # (SET statement_timeout) goes through the patched psycopg.Cursor and stays benign.
            if "name" in kwargs:
                return TestGetRowsInitialReadDropRetry._Cursor(
                    batches=self._batches, drop_on_execute=self._drop_on_execute
                )
            return mock.MagicMock()

        def commit(self):
            return None

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _run(self, connect_side_effect):
        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.time.sleep"),
            patch(f"{module}.psycopg.connect", side_effect=connect_side_effect) as connect_mock,
            patch(f"{module}.psycopg.Cursor", return_value=self._Cursor(batches=[], drop_on_execute=False)),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=False),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=False),
            patch(f"{module}._get_table_chunk_size", return_value=100),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["companies"],
                should_use_incremental_field=False,
                logger=structlog.get_logger(),
                db_incremental_field_last_value=None,
                team_id=1,
            )
            tables = list(cast(Iterable[Any], response.items()))
        return tables, connect_mock

    def test_retries_full_table_read_when_connection_drops_before_first_row(self):
        calls = {"n": 0}

        def connect_side_effect(*args, **kwargs):
            calls["n"] += 1
            # First read connect succeeds, but the server-cursor DECLARE drops; the retry reconnects
            # and serves the rows.
            drop_on_execute = calls["n"] == 1
            batches = [] if drop_on_execute else [[(1,), (2,), (3,)]]
            return self._Connection(batches=batches, drop_on_execute=drop_on_execute)

        tables, connect_mock = self._run(connect_side_effect)

        assert connect_mock.call_count >= 2, "the read should have been retried after the DECLARE-time drop"
        assert sum(table.num_rows for table in tables) == 3

    def test_reraises_full_table_drop_after_rows_yielded(self):
        # A drop after a chunk is already out must propagate: an unordered full-table scan can't
        # resume without duplicating rows, so the in-process retry must not swallow it.
        def connect_side_effect(*args, **kwargs):
            return self._Connection(
                batches=[[(1,), (2,)], psycopg.OperationalError(self._DROP)],
                drop_on_execute=False,
            )

        with pytest.raises(psycopg.OperationalError, match="SSL connection has been closed unexpectedly"):
            self._run(connect_side_effect)


class TestPartitionIterationConnectRetry:
    # Regression: the windowed / per-partition read paths opened each window's (or partition's)
    # connection with a bare get_connection(), so a transient drop while establishing it — the
    # observed "OperationalError: the connection is lost" raised by the setup commit() inside
    # get_connection — escaped and failed the whole activity, even though every other read path
    # already recovers in-process via _connect_with_dropped_retry. Wrapping the per-window connect
    # in the same helper makes a transient drop retry instead of aborting.

    class _BenignSetupCursor:
        # psycopg.Cursor(connection) inside get_connection, used only to SET statement_timeout.
        def execute(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _WindowCursor:
        # Named server-side cursor opened by iterate_date_windows; yields one batch then drains.
        def __init__(self, rows):
            id_col, val_col = mock.Mock(), mock.Mock()
            id_col.name, val_col.name = "id", "val"
            self.description = [id_col, val_col]
            self._rows = rows

        def execute(self, *args, **kwargs):
            return None

        def fetchmany(self, n):
            batch, self._rows = self._rows[:n], self._rows[n:]
            return batch

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _WindowConnection:
        def __init__(self, *, commit_error=None, rows=None):
            self.autocommit = False
            self.closed = False
            self.broken = False
            self.adapters = mock.Mock()
            self._commit_error = commit_error
            self._rows = rows or []

        def cursor(self, *args, **kwargs):
            if "name" in kwargs:
                return TestPartitionIterationConnectRetry._WindowCursor(list(self._rows))
            # Unnamed setup cursor (metadata probes are patched out) stays benign.
            return mock.MagicMock()

        def commit(self):
            # Reproduces the production failure: a freshly opened socket dies before the setup
            # commit, so psycopg raises "the connection is lost" from inside get_connection.
            if self._commit_error is not None:
                raise self._commit_error

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # Both branches changed by the fix are covered: get_partition_strategy=None keeps
    # use_per_partition_chunking False -> iterate_date_windows (windowed path); a range strategy
    # keyed on the incremental field flips it True -> iterate_partitions (per-partition path).
    @pytest.mark.parametrize(
        "partition_strategy",
        [
            pytest.param(None, id="windowed"),
            pytest.param(PartitionStrategy(strategy="r", key_columns=("id",)), id="per_partition"),
        ],
    )
    def test_partition_connect_retries_transient_drop_in_process(self, partition_strategy):
        @contextmanager
        def fake_tunnel():
            yield ("localhost", 5432)

        fake_table = mock.Mock()
        fake_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64()), pa.field("val", pa.int64())])
        fake_table.type = "table"
        fake_table.columns = []
        fake_table.__contains__ = mock.Mock(return_value=False)

        connect_calls = {"n": 0}

        def connect_side_effect(*args, **kwargs):
            connect_calls["n"] += 1
            if connect_calls["n"] == 1:
                # Setup connection (metadata probes are patched out).
                return TestPartitionIterationConnectRetry._WindowConnection()
            if connect_calls["n"] == 2:
                # First per-window/per-partition connect: the setup commit() inside get_connection drops.
                return TestPartitionIterationConnectRetry._WindowConnection(
                    commit_error=psycopg.OperationalError("the connection is lost")
                )
            # The retried connect succeeds and serves the rows.
            return TestPartitionIterationConnectRetry._WindowConnection(rows=[(1, 10), (2, 20), (3, 30)])

        child = ChildPartition(
            oid=1,
            schema="public",
            name="events_p1",
            partbound="FOR VALUES FROM (0) TO (100)",
        )

        module = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"
        with (
            patch(f"{module}.psycopg.connect", side_effect=connect_side_effect) as connect_mock,
            patch(
                f"{module}.psycopg.Cursor",
                side_effect=lambda _conn: TestPartitionIterationConnectRetry._BenignSetupCursor(),
            ),
            patch(f"{module}._get_table", return_value=fake_table),
            patch(f"{module}._is_read_replica", return_value=False),
            patch(f"{module}._get_primary_keys", return_value=["id"]),
            patch(f"{module}._is_partitioned_table", return_value=True),
            patch(f"{module}.list_child_partitions", return_value=[child]),
            patch(f"{module}.get_partition_strategy", return_value=partition_strategy),
            patch(f"{module}._get_table_chunk_size", return_value=1000),
            patch(f"{module}._get_rows_to_sync", return_value=10),
            patch(f"{module}._role_subject_to_rls", return_value=False),
            patch(f"{module}._get_partition_settings", return_value=None),
            patch(f"{module}.time.sleep"),
        ):
            response = postgres_source(
                tunnel=lambda: fake_tunnel(),
                user="u",
                password="p",
                database="db",
                sslmode="prefer",
                schema="public",
                table_names=["events"],
                should_use_incremental_field=True,
                logger=structlog.get_logger(),
                incremental_field="id",
                incremental_field_type=IncrementalFieldType.Integer,
                db_incremental_field_last_value=0,
                team_id=1,
            )
            # Before the fix the connect drop escaped iterate_date_windows / iterate_partitions here.
            tables = list(cast(Iterable[Any], response.items()))

        # 1 setup + 2 per-window/per-partition connects (1 dropped commit + 1 success).
        assert connect_mock.call_count == 3
        assert sum(table.num_rows for table in tables) == 3
