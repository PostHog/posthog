"""MySQL-specific CDC error classification onto the shared ``CDCErrorCategory`` taxonomy."""

from __future__ import annotations

import pymysql
from sshtunnel import BaseSSHTunnelForwarderError

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.binlog import BinlogDisabledError

ER_ACCESS_DENIED = 1045
ER_SPECIFIC_ACCESS_DENIED = 1227
ER_TABLEACCESS_DENIED = 1142
# Can't connect, unknown host, server gone away, lost connection, TLS handshake failed.
CONNECTION_ERROR_CODES = frozenset({2003, 2005, 2006, 2013, 2026})


def _code(exc: BaseException) -> int | None:
    if isinstance(exc, pymysql.err.MySQLError) and exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def classify_mysql_cdc_error(exc: BaseException) -> CDCErrorCategory | None:
    if isinstance(exc, BaseSSHTunnelForwarderError):
        return CDCErrorCategory.SSH_TUNNEL_FAILED
    if isinstance(exc, HostNotAllowedError):
        return CDCErrorCategory.HOST_UNREACHABLE
    code = _code(exc)
    if code == ER_ACCESS_DENIED:
        return CDCErrorCategory.AUTH_FAILED
    if code in (ER_SPECIFIC_ACCESS_DENIED, ER_TABLEACCESS_DENIED):
        return CDCErrorCategory.PERMISSION_DENIED
    if code in CONNECTION_ERROR_CODES:
        return CDCErrorCategory.CONNECTION_FAILED
    return None


def is_connection_error(exc: BaseException) -> bool:
    # pymysql raises OperationalError for most server errors, our own SQL bugs included, so match the code.
    if isinstance(exc, pymysql.err.InterfaceError | BaseSSHTunnelForwarderError | HostNotAllowedError):
        return True
    return _code(exc) in CONNECTION_ERROR_CODES | {ER_ACCESS_DENIED}


def customer_fixable_error_message(exc: BaseException) -> str | None:
    if isinstance(exc, BinlogDisabledError):
        return (
            "Binary logging is off on the source database. Turn it back on (log_bin, with binlog_format=ROW), "
            "then resume CDC. On RDS and Aurora, turn on automated backups."
        )
    if _code(exc) == ER_SPECIFIC_ACCESS_DENIED:
        return (
            f"The database user can't read the binary log: {exc} Run GRANT REPLICATION SLAVE, REPLICATION "
            "CLIENT, PROCESS ON *.* TO '<user>'@'%'; or switch these tables to Incremental sync, which needs "
            "only SELECT."
        )
    return None
