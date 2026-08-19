from contextlib import contextmanager
from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planetscalemysql import (
    PlanetScaleMySQLSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.planetscale_mysql import (
    PlanetScaleMySQLImplementation,
)

_CONNECT_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.planetscale_mysql."
    "_connect_with_transient_retry"
)


def _config(port: int | str = 3306) -> MySQLSourceConfig:
    # The runtime config for this source is the generated `PlanetScaleMySQLSourceConfig`; the driver
    # signatures are typed against the MySQL one it structurally matches. It deliberately has no
    # `using_ssl` or `ssh_tunnel` field, which is what these tests exercise.
    return cast(
        MySQLSourceConfig,
        PlanetScaleMySQLSourceConfig(
            host="aws.connect.psdb.cloud",
            database="my-database",
            user="user",
            password="password",
            port=cast(int, port),
            schema=None,
        ),
    )


@contextmanager
def _connect(config: MySQLSourceConfig, **kwargs: Any):
    connection = mock.MagicMock()
    with mock.patch(_CONNECT_TARGET) as connect:
        connect.return_value.__enter__.return_value = connection
        with PlanetScaleMySQLImplementation().connect(config, **kwargs) as opened:
            assert opened is connection
        yield connect.call_args.args[0]


def test_connection_always_uses_tls_and_the_olap_workload():
    with _connect(_config()) as kwargs:
        # PlanetScale mandates TLS, and Vitess' default OLTP workload caps reads at 100k rows.
        assert kwargs["ssl_ca"]
        assert kwargs["init_command"] == "SET workload = 'OLAP';"


def test_connection_verifies_the_server_certificate_and_hostname():
    with _connect(_config()) as kwargs:
        # Without these, pymysql accepts any valid certificate for any host, so anyone able to
        # redirect the connection could impersonate PlanetScale and capture the credentials.
        assert kwargs["ssl_verify_cert"] is True
        assert kwargs["ssl_verify_identity"] is True


def test_connection_details_come_from_the_config():
    with _connect(_config()) as kwargs:
        assert kwargs["host"] == "aws.connect.psdb.cloud"
        assert kwargs["database"] == "my-database"
        assert kwargs["user"] == "user"
        assert kwargs["password"] == "password"


@pytest.mark.parametrize("port", [3306, "3306"])
def test_port_is_coerced_to_int(port):
    # pymysql rejects a string port, and a config built outside `from_dict` skips the converter.
    with _connect(_config(port)) as kwargs:
        assert kwargs["port"] == 3306


def test_read_timeout_is_only_sent_when_requested():
    with _connect(_config()) as kwargs:
        assert "read_timeout" not in kwargs

    with _connect(_config(), read_timeout=600) as kwargs:
        assert kwargs["read_timeout"] == 600
