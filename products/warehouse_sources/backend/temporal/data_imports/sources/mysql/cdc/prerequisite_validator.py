"""CDC prerequisite validator for MySQL.

Checks whether a MySQL server can serve its row-based binary log to PostHog. Returns a list of
user-facing error messages (empty = all checks passed).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pymysql

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.errors import CONNECTION_ERROR_CODES

# Column names in the binlog's row metadata arrived in 8.0.1 (`binlog_row_metadata`).
MIN_MYSQL_VERSION = (8, 0, 1)
MIN_RETENTION_HOURS = 24
RECOMMENDED_RETENTION_HOURS = 168

_REQUIRED_GRANTS = ("REPLICATION SLAVE", "REPLICATION CLIENT", "PROCESS")
_GLOBAL_GRANT = re.compile(r"^GRANT (?P<privileges>.+?) ON \*\.\* TO ", re.IGNORECASE)


@frozen
class QualifiedTable:
    database: str
    table: str


def validate_cdc_prerequisites(conn: pymysql.Connection, tables: list[str], database: str | None) -> list[str]:
    """Validate that the server is ready for CDC.

    ``database`` is the database the source reads. None when the source reads every database, because
    discovery then names each table ``database.table``.
    """
    version_errors = _check_version(conn)
    if version_errors:
        # Everything below reads variables an unsupported server may not have.
        return version_errors

    resolved = resolve_tables(tables, database)
    errors: list[str] = []
    errors.extend(_check_binlog_settings(conn))
    errors.extend(_check_binlog_filters(conn, {table.database for table in resolved} or {database or ""}))
    errors.extend(_check_grants(conn))
    errors.extend(_check_retention(conn))
    errors.extend(_check_tables_have_primary_keys(conn, resolved))
    return errors


def resolve_tables(tables: Iterable[str], database: str | None) -> list[QualifiedTable]:
    resolved = []
    for name in tables:
        if database is None and "." in name:
            db, table = name.split(".", 1)
            resolved.append(QualifiedTable(database=db, table=table))
        else:
            resolved.append(QualifiedTable(database=database or "", table=name))
    return resolved


def _scalar(conn: pymysql.Connection, query: str, args: Any = None) -> Any:
    with conn.cursor() as cur:
        cur.execute(query, args)
        row = cur.fetchone()
    return row[0] if row else None


def _variables(conn: pymysql.Connection, names: Iterable[str]) -> dict[str, str]:
    names = list(names)
    with conn.cursor() as cur:
        cur.execute(
            f"SHOW GLOBAL VARIABLES WHERE Variable_name IN ({', '.join(['%s'] * len(names))})",
            names,
        )
        return {str(name).lower(): str(value) for name, value in cur.fetchall()}


def _check_version(conn: pymysql.Connection) -> list[str]:
    version = str(_scalar(conn, "SELECT VERSION()") or "")
    if "mariadb" in version.lower():
        return ["Change data capture doesn't support MariaDB yet. Use Incremental or Full refresh sync instead."]
    numbers = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if numbers is None:
        return [f"Could not determine the MySQL version (the server reported {version!r})."]
    if tuple(int(part) for part in numbers.groups()) < MIN_MYSQL_VERSION:
        return [
            f"Change data capture needs MySQL 8.0.1 or later (the server runs {version}). "
            "Upgrade MySQL, or use Incremental or Full refresh sync instead."
        ]
    return []


def _check_binlog_settings(conn: pymysql.Connection) -> list[str]:
    values = _variables(
        conn,
        [
            "log_bin",
            "binlog_format",
            "binlog_row_image",
            "binlog_row_metadata",
            "binlog_transaction_compression",
            "binlog_row_value_options",
        ],
    )
    if values.get("log_bin", "").upper() not in ("ON", "1"):
        return [
            "Binary logging is off. Turn it on (log_bin), with binlog_format=ROW, binlog_row_image=FULL and "
            "binlog_row_metadata=FULL. On RDS and Aurora, turn on automated backups and set them in the "
            "parameter group."
        ]
    expected = {"binlog_format": "ROW", "binlog_row_image": "FULL", "binlog_row_metadata": "FULL"}
    errors = [
        f"{name} is {values.get(name) or 'not set'}, but change data capture needs {required}. Set "
        f"{name}={required} (on RDS and Aurora, in the parameter group), then check again."
        for name, required in expected.items()
        if values.get(name, "").upper() != required
    ]
    # Compressed transactions carry their rows inside one payload event, which the reader can't decode.
    if values.get("binlog_transaction_compression", "").upper() in ("ON", "1"):
        errors.append(
            "binlog_transaction_compression is ON, but change data capture can't read compressed transactions. "
            "Set binlog_transaction_compression=OFF, then check again."
        )
    # A partial JSON update logs only the changed paths, not the document the table holds.
    if "PARTIAL_JSON" in values.get("binlog_row_value_options", "").upper():
        errors.append(
            "binlog_row_value_options is PARTIAL_JSON, but change data capture needs whole JSON documents. "
            "Set binlog_row_value_options to an empty value, then check again."
        )
    return errors


def _check_binlog_filters(conn: pymysql.Connection, databases: set[str]) -> list[str]:
    """Databases the server leaves out of the binlog (``binlog-do-db`` / ``binlog-ignore-db``)."""
    with conn.cursor() as cur:
        try:
            cur.execute("SHOW BINARY LOG STATUS")
        except pymysql.err.ProgrammingError:
            cur.execute("SHOW MASTER STATUS")
        columns = [str(column[0]).lower() for column in cur.description or []]
        row = cur.fetchone()
    if row is None:
        return []
    status = dict(zip(columns, row))
    do_db = {name.strip() for name in str(status.get("binlog_do_db") or "").split(",") if name.strip()}
    ignore_db = {name.strip() for name in str(status.get("binlog_ignore_db") or "").split(",") if name.strip()}
    excluded = sorted(db for db in databases if db and (db in ignore_db or (do_db and db not in do_db)))
    if not excluded:
        return []
    return [
        f"The server leaves these databases out of the binary log, so their changes can't be captured: "
        f"{', '.join(excluded)}. Remove them from binlog-ignore-db, or add them to binlog-do-db."
    ]


def _check_grants(conn: pymysql.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW GRANTS FOR CURRENT_USER()")
        grants = [str(row[0]) for row in cur.fetchall()]
    held: set[str] = set()
    for grant in grants:
        if match := _GLOBAL_GRANT.match(grant):
            held.update(privilege.strip().upper() for privilege in match.group("privileges").split(","))
    if "ALL PRIVILEGES" in held:
        return []
    missing = [grant for grant in _REQUIRED_GRANTS if grant not in held]
    if not missing:
        return []
    return [
        f"The database user is missing {', '.join(missing)}. Run: GRANT REPLICATION SLAVE, REPLICATION CLIENT, "
        "PROCESS ON *.* TO '<user>'@'%'; Granting these through a role only works when the role is active by "
        "default."
    ]


def is_rds(conn: pymysql.Connection) -> bool:
    """RDS and Aurora keep their own binlog retention, which overrides the server variable.

    Read from server variables, which every user can read, unlike the RDS procedures' catalog rows.
    """
    values = _variables(conn, ["basedir", "aurora_version"])
    return "rdsdbbin" in values.get("basedir", "") or "aurora_version" in values


def retention_hours(conn: pymysql.Connection) -> float | None:
    """How long the server keeps binlog files, in hours. None when it never purges them on a timer."""
    if is_rds(conn):
        return _rds_retention_hours(conn)
    seconds = int(_variables(conn, ["binlog_expire_logs_seconds"]).get("binlog_expire_logs_seconds") or 0)
    return seconds / 3600 if seconds else None


def _rds_retention_hours(conn: pymysql.Connection) -> float:
    with conn.cursor() as cur:
        cur.execute("CALL mysql.rds_show_configuration")
        rows = cur.fetchall()
        # A CALL leaves a trailing status result that must be read before the next statement.
        while cur.nextset():
            pass
    for row in rows:
        if str(row[0]).lower() == "binlog retention hours" and row[1] not in (None, "", "NULL"):
            return float(row[1])
    # RDS defaults it to NULL, which purges each file as soon as no replica needs it.
    return 0.0


def _check_retention(conn: pymysql.Connection) -> list[str]:
    rds = is_rds(conn)
    try:
        hours = _rds_retention_hours(conn) if rds else retention_hours(conn)
    except pymysql.err.MySQLError as e:
        if e.args and e.args[0] in CONNECTION_ERROR_CODES:
            raise
        grant = " Run: GRANT EXECUTE ON PROCEDURE mysql.rds_show_configuration TO '<user>'@'%';" if rds else ""
        return [f"Couldn't read how long the server keeps binary logs: {e}.{grant}"]
    if hours is None or hours >= MIN_RETENTION_HOURS:
        return []
    if rds:
        fix = (
            "On RDS and Aurora, run: CALL mysql.rds_set_configuration('binlog retention hours', "
            f"{RECOMMENDED_RETENTION_HOURS});"
        )
    else:
        fix = (
            f"Set binlog_expire_logs_seconds to at least {RECOMMENDED_RETENTION_HOURS * 3600} "
            f"({RECOMMENDED_RETENTION_HOURS} hours)."
        )
    return [
        f"The server keeps binary logs for {hours:g} hours. Change data capture needs at least "
        f"{MIN_RETENTION_HOURS} hours, so a paused or failing sync doesn't lose changes. {fix}"
    ]


def _check_tables_have_primary_keys(conn: pymysql.Connection, tables: list[QualifiedTable]) -> list[str]:
    if not tables:
        return []
    clauses = " OR ".join(["(TABLE_SCHEMA = %s AND TABLE_NAME = %s)"] * len(tables))
    args = [part for table in tables for part in (table.database, table.table)]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT TABLE_SCHEMA, TABLE_NAME FROM information_schema.TABLE_CONSTRAINTS "
            f"WHERE CONSTRAINT_TYPE = 'PRIMARY KEY' AND ({clauses})",
            args,
        )
        keyed = {(str(db), str(name)) for db, name in cur.fetchall()}
    missing = [f"{t.database}.{t.table}" for t in tables if (t.database, t.table) not in keyed]
    if not missing:
        return []
    return [
        f"These tables have no primary key, which change data capture needs to merge changes: {', '.join(missing)}. "
        "Add a primary key, or use Full refresh sync for them."
    ]
