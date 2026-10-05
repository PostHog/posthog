import socket
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import psycopg
from parameterized import parameterized
from psycopg import errors as pg_errors

from posthog.models.integration import Integration

from products.warehouse_sources.backend.presentation.destination_connection_check import (
    FAILURE_MESSAGES,
    CheckFailure,
    DestinationConnectionCheckError,
    _query_deadline,
    check_postgres_destination,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError

MODULE = "products.warehouse_sources.backend.presentation.destination_connection_check"


def _integration(**config_overrides: Any) -> Integration:
    return Integration(
        kind=Integration.IntegrationKind.POSTGRESQL,
        config={"host": "db.example.com", "port": 5432, "user": "writer", "ssl_mode": "require", **config_overrides},
        sensitive_config={"password": "hunter2"},
    )


def _connection(*, fetches: list[tuple[Any, ...] | None], execute_error: Exception | None = None) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetches
    if execute_error is not None:
        cursor.execute.side_effect = execute_error
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor_mock = cursor
    return connection


def test_query_deadline_interrupts_the_connection_socket() -> None:
    connection = MagicMock()
    connection.pgconn.socket = 42
    timer = MagicMock()

    with (
        patch(f"{MODULE}.threading.Timer", return_value=timer) as timer_constructor,
        patch(f"{MODULE}.socket.socket") as socket_constructor,
        _query_deadline(connection, 5),
    ):
        timer_constructor.call_args.args[1]()

    timer_constructor.assert_called_once_with(5, timer_constructor.call_args.args[1])
    timer.start.assert_called_once_with()
    timer.cancel.assert_called_once_with()
    timer.join.assert_called_once_with()
    socket_constructor.assert_called_once_with(fileno=42)
    socket_constructor.return_value.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    socket_constructor.return_value.detach.assert_called_once_with()


class TestCheckPostgresDestination:
    def test_a_usable_destination_passes(self) -> None:
        connection = _connection(fetches=[(True,), (True,)])

        with (
            patch(
                f"{MODULE}.pinned_host_kwargs",
                return_value={"host": "db.example.com", "hostaddr": "203.0.113.10"},
            ) as pinned_host,
            patch(f"{MODULE}.psycopg.connect", return_value=connection) as connect,
        ):
            check_postgres_destination(_integration(), {"database": "analytics", "schema": "posthog"})

        pinned_host.assert_called_once_with("db.example.com", port=5432, connect_timeout=5, team_id=None)
        assert connect.call_args.kwargs["dbname"] == "analytics"
        assert connect.call_args.kwargs["hostaddr"] == "203.0.113.10"
        assert connect.call_args.kwargs["connect_timeout"] == 5
        assert connect.call_args.kwargs["options"] == "-c statement_timeout=5000"
        assert connect.call_args.kwargs["autocommit"] is True
        statements = [call.args[0] for call in connection.cursor_mock.execute.call_args_list]
        assert "has_schema_privilege" in statements[-1]

    @parameterized.expand(
        [
            ("existing_schema_with_privilege", [(True,), (True,)], "has_schema_privilege", None),
            (
                "existing_schema_without_privilege",
                [(True,), (False,)],
                "has_schema_privilege",
                CheckFailure.MISSING_PRIVILEGE,
            ),
            ("new_schema_with_database_privilege", [(False,), (True,)], "has_database_privilege", None),
            (
                "new_schema_without_database_privilege",
                [(False,), (False,)],
                "has_database_privilege",
                CheckFailure.MISSING_PRIVILEGE,
            ),
        ]
    )
    def test_the_create_privilege_check(
        self,
        _name: str,
        fetches: list[tuple[Any, ...] | None],
        expected_function: str,
        expected_failure: CheckFailure | None,
    ) -> None:
        connection = _connection(fetches=fetches)

        with patch(f"{MODULE}.psycopg.connect", return_value=connection):
            if expected_failure is None:
                check_postgres_destination(_integration(), {})
            else:
                with pytest.raises(DestinationConnectionCheckError) as raised:
                    check_postgres_destination(_integration(), {})
                assert raised.value.failure == expected_failure

        assert expected_function in connection.cursor_mock.execute.call_args_list[-1].args[0]

    @parameterized.expand(
        [
            ("connection_refused", psycopg.OperationalError("connection refused"), CheckFailure.UNREACHABLE),
            ("network_unreachable", psycopg.OperationalError("Network is unreachable"), CheckFailure.UNREACHABLE),
            ("timeout", pg_errors.ConnectionTimeout("timeout expired"), CheckFailure.UNREACHABLE),
            ("bad_password", pg_errors.InvalidPassword("password authentication failed"), CheckFailure.AUTHENTICATION),
            (
                "rejected_user",
                pg_errors.InvalidAuthorizationSpecification("no pg_hba.conf entry"),
                CheckFailure.AUTHENTICATION,
            ),
            (
                "unknown_database",
                pg_errors.InvalidCatalogName('database "nope" does not exist'),
                CheckFailure.UNKNOWN_DATABASE,
            ),
            ("denied_by_server", pg_errors.InsufficientPrivilege("permission denied"), CheckFailure.MISSING_PRIVILEGE),
        ]
    )
    def test_connection_failures_map_to_one_message_without_driver_text(
        self, _name: str, error: Exception, expected_failure: CheckFailure
    ) -> None:
        with patch(f"{MODULE}.psycopg.connect", side_effect=error):
            with pytest.raises(DestinationConnectionCheckError) as raised:
                check_postgres_destination(_integration(), None)

        assert raised.value.failure == expected_failure
        assert str(raised.value) == FAILURE_MESSAGES[expected_failure]
        for secret in ("hunter2", "writer", "db.example.com"):
            assert secret not in str(raised.value)

    def test_an_unsafe_resolved_host_is_classified_as_unreachable(self) -> None:
        with patch(f"{MODULE}.pinned_host_kwargs", side_effect=HostNotAllowedError("blocked")):
            with pytest.raises(DestinationConnectionCheckError) as raised:
                check_postgres_destination(_integration(), None)

        assert raised.value.failure == CheckFailure.UNREACHABLE

    def test_a_failure_while_running_queries_is_classified(self) -> None:
        connection = _connection(fetches=[], execute_error=pg_errors.InsufficientPrivilege("permission denied"))

        with patch(f"{MODULE}.psycopg.connect", return_value=connection):
            with pytest.raises(DestinationConnectionCheckError) as raised:
                check_postgres_destination(_integration(), None)

        assert raised.value.failure == CheckFailure.MISSING_PRIVILEGE

    @parameterized.expand(
        [
            ("no_cert", {"ssl_mode": "require"}, "/tmp/posthog/batch-exports/MISSING.crt", False),
            ("system_cert", {"ssl_mode": "require", "ssl_root_cert": "system"}, "system", False),
            ("pasted_cert", {"ssl_mode": "verify-ca", "ssl_root_cert": "CERT-DATA"}, None, True),
        ]
    )
    def test_the_root_certificate_is_passed_as_a_file(
        self, _name: str, overrides: dict[str, str], expected_path: str | None, is_temp_file: bool
    ) -> None:
        seen: dict[str, Any] = {}

        @contextmanager
        def _fake_connect(**kwargs: Any):
            seen["path"] = kwargs["sslrootcert"]
            if is_temp_file:
                with open(kwargs["sslrootcert"]) as cert_file:
                    seen["contents"] = cert_file.read()
            yield _connection(fetches=[(True,), (True,)])

        with patch(f"{MODULE}.psycopg.connect", side_effect=lambda **kwargs: _fake_connect(**kwargs)):
            check_postgres_destination(_integration(**overrides), None)

        if is_temp_file:
            assert seen["contents"] == "CERT-DATA"
        else:
            assert seen["path"] == expected_path
