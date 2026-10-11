import socket

import pytest
from unittest import mock

import psycopg

from posthog.models.integration import Integration

from products.batch_exports.backend.facade.destinations.postgres import PostgreSQLClient, PostgreSQLConnectionError
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DESTINATION_CONFIGURATION_ERROR_MARKER,
    MISSING_INTEGRATION_DETAIL,
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers import (
    postgres,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    ACCESS_RULE_DETAIL,
    AUTHENTICATION_FAILED_DETAIL,
    HOST_NOT_FOUND_DETAIL,
    IPV6_ONLY_HOST_DETAIL,
    NETWORK_UNREACHABLE_DETAIL,
    UNKNOWN_DATABASE_DETAIL,
    PostgresDestinationWriter,
    connect_configuration_error_detail,
    host_configuration_error_detail,
)

HOST = "db.example.com"
V4 = "192.0.2.10"
V6 = "2001:db8::10"


def _attempt_failed(reason: str, address: str = V4) -> str:
    return f'connection failed: connection to server at "{HOST}" ({address}), port 5432 failed: {reason}'


def _addrinfo(*addresses: str) -> list[tuple]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 5432, 0, 0) if ":" in address else (address, 5432),
        )
        for address in addresses
    ]


def _ctx(integration_id: int | None = 1) -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run",
        destination_id="destination",
        destination_type="Postgres",
        destination_name="Prod",
        table_name="orders",
        sync_type="full_refresh",
        integration_id=integration_id,
    )


class _FixedClientWriter(PostgresDestinationWriter):
    def __init__(self, host: str) -> None:
        super().__init__(_ctx())
        self._host = host

    async def _make_client(self) -> PostgreSQLClient:
        return PostgreSQLClient(
            user="posthog", password="secret", host=self._host, port=5432, database="postgres", ssl_mode="prefer"
        )


async def _open(writer: PostgresDestinationWriter) -> None:
    async with writer._client():
        pass


class TestConnectConfigurationErrorDetail:
    @pytest.mark.parametrize(
        ("_name", "err", "expected"),
        [
            (
                "ipv6_unreachable",
                psycopg.OperationalError(_attempt_failed("Network is unreachable", V6)),
                NETWORK_UNREACHABLE_DETAIL,
            ),
            (
                "wrong_password",
                psycopg.OperationalError(_attempt_failed('FATAL:  password authentication failed for user "loader"')),
                AUTHENTICATION_FAILED_DETAIL,
            ),
            (
                "unknown_role",
                psycopg.OperationalError(_attempt_failed('FATAL:  role "loader" does not exist')),
                AUTHENTICATION_FAILED_DETAIL,
            ),
            (
                "no_access_rule",
                psycopg.OperationalError(_attempt_failed('FATAL:  no pg_hba.conf entry for host "198.51.100.7"')),
                ACCESS_RULE_DETAIL,
            ),
            (
                "unknown_database",
                psycopg.OperationalError(_attempt_failed('FATAL:  database "analytics" does not exist')),
                UNKNOWN_DATABASE_DETAIL,
            ),
            ("invalid_password_class", psycopg.errors.InvalidPassword("rejected"), AUTHENTICATION_FAILED_DETAIL),
            ("invalid_catalog_class", psycopg.errors.InvalidCatalogName("missing"), UNKNOWN_DATABASE_DETAIL),
            (
                "last_attempt_rejected_the_password",
                psycopg.OperationalError(
                    _attempt_failed('FATAL:  password authentication failed for user "loader"')
                    + "\nMultiple connection attempts failed. All failures were:\n- "
                    + _attempt_failed("Network is unreachable", V6)
                ),
                AUTHENTICATION_FAILED_DETAIL,
            ),
            ("connect_timeout", psycopg.errors.ConnectionTimeout("connection timeout expired"), None),
            (
                "last_attempt_timed_out_after_unreachable_ipv6",
                psycopg.OperationalError(
                    _attempt_failed("timeout expired")
                    + "\nMultiple connection attempts failed. All failures were:\n- "
                    + _attempt_failed("Network is unreachable", V6)
                    + "\n- "
                    + _attempt_failed("timeout expired")
                ),
                None,
            ),
            ("connection_reset", psycopg.OperationalError(_attempt_failed("Connection reset by peer")), None),
            (
                "server_shutting_down",
                psycopg.OperationalError(_attempt_failed("FATAL:  the database system is shutting down")),
                None,
            ),
            (
                "too_many_clients",
                psycopg.OperationalError(_attempt_failed("FATAL:  sorry, too many clients already")),
                None,
            ),
            (
                "server_closed_connection",
                psycopg.OperationalError(_attempt_failed("server closed the connection unexpectedly")),
                None,
            ),
            ("not_a_psycopg_error", RuntimeError("Network is unreachable"), None),
        ],
    )
    def test_classifies_connect_errors(self, _name: str, err: Exception, expected: str | None) -> None:
        assert connect_configuration_error_detail(err) == expected


class TestHostConfigurationErrorDetail:
    @pytest.mark.parametrize(
        ("_name", "host", "resolution", "ipv6_route", "expected"),
        [
            ("ipv6_only_without_route", HOST, _addrinfo(V6), False, IPV6_ONLY_HOST_DETAIL),
            ("ipv6_only_with_route", HOST, _addrinfo(V6), True, None),
            ("dual_stack_without_route", HOST, _addrinfo(V6, V4), False, None),
            ("ipv4_only_without_route", HOST, _addrinfo(V4), False, None),
            ("ipv6_literal_without_route", V6, None, False, IPV6_ONLY_HOST_DETAIL),
            ("bracketed_ipv6_literal_without_route", f"[{V6}]", None, False, IPV6_ONLY_HOST_DETAIL),
            ("ipv4_literal_without_route", V4, None, False, None),
            ("unix_socket", "/var/run/postgresql", None, False, None),
            (
                "name_does_not_exist",
                HOST,
                socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
                True,
                HOST_NOT_FOUND_DETAIL,
            ),
            (
                "resolver_temporarily_failing",
                HOST,
                socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"),
                True,
                None,
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_classifies_the_host(
        self,
        _name: str,
        host: str,
        resolution: list[tuple] | Exception | None,
        ipv6_route: bool,
        expected: str | None,
    ) -> None:
        lookup = (
            mock.Mock(side_effect=resolution)
            if isinstance(resolution, Exception)
            else mock.Mock(return_value=resolution)
        )
        with (
            mock.patch("socket.getaddrinfo", lookup),
            mock.patch.object(postgres, "has_ipv6_route", return_value=ipv6_route),
        ):
            assert await host_configuration_error_detail(host, 5432) == expected

        if resolution is None:
            lookup.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_resolver_that_hangs_leaves_the_decision_to_connect(self) -> None:
        with (
            mock.patch.object(postgres, "_resolve", side_effect=TimeoutError),
            mock.patch.object(postgres, "has_ipv6_route", return_value=False),
        ):
            assert await host_configuration_error_detail(HOST, 5432) is None


class TestWriterClient:
    @pytest.mark.parametrize(
        ("_name", "integration_id"),
        [
            ("no_integration", None),
            ("integration_deleted", 42),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_missing_integration_is_a_configuration_error(self, _name: str, integration_id: int | None) -> None:
        writer = PostgresDestinationWriter(_ctx(integration_id))

        with (
            mock.patch.object(Integration.objects, "aget", side_effect=Integration.DoesNotExist),
            mock.patch.object(psycopg.AsyncConnection, "connect") as connect,
            pytest.raises(DestinationConfigurationError) as caught,
        ):
            await _open(writer)

        assert str(caught.value) == f"Prod: {DESTINATION_CONFIGURATION_ERROR_MARKER}. {MISSING_INTEGRATION_DETAIL}"
        connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_ipv6_only_host_fails_without_connecting(self) -> None:
        with (
            mock.patch("socket.getaddrinfo", return_value=_addrinfo(V6)),
            mock.patch.object(postgres, "has_ipv6_route", return_value=False),
            mock.patch.object(psycopg.AsyncConnection, "connect") as connect,
            pytest.raises(DestinationConfigurationError) as caught,
        ):
            await _open(_FixedClientWriter(HOST))

        assert IPV6_ONLY_HOST_DETAIL in str(caught.value)
        connect.assert_not_called()

    @pytest.mark.parametrize(
        ("_name", "error", "expected_error", "expected_attempts"),
        [
            (
                "configuration_error_stops_at_once",
                psycopg.OperationalError(_attempt_failed('FATAL:  password authentication failed for user "loader"')),
                DestinationConfigurationError,
                1,
            ),
            (
                "transient_error_keeps_its_retries",
                psycopg.OperationalError(_attempt_failed("FATAL:  sorry, too many clients already")),
                PostgreSQLConnectionError,
                5,
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_connect_retries_only_transient_errors(
        self, _name: str, error: Exception, expected_error: type[Exception], expected_attempts: int
    ) -> None:
        with (
            mock.patch("socket.getaddrinfo", return_value=_addrinfo(V4)),
            mock.patch.object(psycopg.AsyncConnection, "connect", side_effect=error) as connect,
            mock.patch("asyncio.sleep", new_callable=mock.AsyncMock),
            pytest.raises(expected_error),
        ):
            await _open(_FixedClientWriter(HOST))

        assert connect.call_count == expected_attempts

    @pytest.mark.asyncio
    async def test_an_error_inside_the_connection_is_not_reclassified(self) -> None:
        connection = mock.AsyncMock()
        connection.__aenter__.return_value = connection
        failure = PostgreSQLConnectionError("Not connected")

        with (
            mock.patch("socket.getaddrinfo", return_value=_addrinfo(V4)),
            mock.patch.object(psycopg.AsyncConnection, "connect", return_value=connection),
            pytest.raises(PostgreSQLConnectionError) as caught,
        ):
            async with _FixedClientWriter(HOST)._client():
                raise failure

        assert caught.value is failure
