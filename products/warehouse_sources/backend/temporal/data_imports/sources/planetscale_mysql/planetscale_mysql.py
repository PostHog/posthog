from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings

import pymysql

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    _MYSQL_SAFE_CONVERSIONS,
    MySQLImplementation,
    _connect_with_transient_retry,
)

# Vitess' default OLTP workload caps a SELECT at 100,000 rows and aborts it after 20 seconds,
# which no full table extract survives. OLAP lifts both limits for reads.
_VITESS_OLAP_INIT_COMMAND = "SET workload = 'OLAP';"


class PlanetScaleMySQLImplementation(MySQLImplementation):
    """MySQL driver specialized for PlanetScale's Vitess endpoints.

    Everything except the connection itself is plain MySQL, so only `connect` is overridden:
    PlanetScale terminates TLS on every connection and offers no SSH tunnel, and Vitess needs
    the OLAP workload hint before it will stream a whole table.
    """

    @contextmanager
    def connect(
        self,
        config: MySQLSourceConfig,
        *,
        read_timeout: int | None = None,
    ) -> Iterator[pymysql.Connection]:
        ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        # PlanetScale has no SSH tunnel option, so this resolves to the configured host and
        # port. It is reused for the shared connection logging that wraps every SQL source.
        with self._ssh_tunnel_endpoint(config) as (host, port):
            kwargs: dict[str, Any] = {
                "host": host,
                # pymysql rejects a non-int port; config.port arrives as a string when the config
                # is built directly rather than through the int-coercing from_dict.
                "port": int(port),
                "database": config.database,
                "user": config.user,
                "password": config.password,
                "connect_timeout": 10,
                "ssl_ca": ssl_ca,
                # PlanetScale serves a publicly trusted certificate for the connect host, so both
                # chain and hostname verification can be required. Without `ssl_verify_identity`
                # pymysql accepts any valid certificate, which lets anyone able to redirect the
                # connection impersonate PlanetScale and capture these credentials.
                "ssl_verify_cert": True,
                "ssl_verify_identity": True,
                "conv": _MYSQL_SAFE_CONVERSIONS,
                "init_command": _VITESS_OLAP_INIT_COMMAND,
            }
            if read_timeout is not None:
                kwargs["read_timeout"] = read_timeout
            with _connect_with_transient_retry(kwargs) as conn:
                yield conn
