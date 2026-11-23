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

    errors: list[str] = []
    errors.extend(_check_binlog_settings(conn))
    errors.extend(_check_grants(conn))
    errors.extend(_check_retention(conn))
    errors.extend(_check_tables_have_primary_keys(conn, resolve_tables(tables, database)))
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
        conn, ["log_bin", "binlog_format", "binlog_row_image", "binlog_row_metadata", "binlog_transaction_compression"]
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
    return errors


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
    """RDS and Aurora keep their own binlog retention, which overrides the server variable."""
    return bool(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA = 'mysql' AND ROUTINE_NAME = 'rds_show_configuration'",
        )
    )


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
    try:
        rds = is_rds(conn)
        hours = _rds_retention_hours(conn) if rds else retention_hours(conn)
    except pymysql.err.MySQLError:
        return []
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
