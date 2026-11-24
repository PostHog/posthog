"""MySQL-specific CDC error classification onto the shared ``CDCErrorCategory`` taxonomy."""

from __future__ import annotations

import pymysql
from sshtunnel import BaseSSHTunnelForwarderError

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError

ER_ACCESS_DENIED = 1045
ER_SPECIFIC_ACCESS_DENIED = 1227
ER_TABLEACCESS_DENIED = 1142
CONNECTION_ERROR_CODES = frozenset({2003, 2006, 2013})


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
    return isinstance(exc, pymysql.err.OperationalError | BaseSSHTunnelForwarderError | HostNotAllowedError)


def customer_fixable_error_message(exc: BaseException) -> str | None:
    if _code(exc) == ER_SPECIFIC_ACCESS_DENIED:
        return (
            f"The database user can't read the binary log: {exc} Run GRANT REPLICATION SLAVE, REPLICATION "
            "CLIENT, PROCESS ON *.* TO '<user>'@'%'; or switch these tables to Incremental sync, which needs "
            "only SELECT."
        )
    return None
