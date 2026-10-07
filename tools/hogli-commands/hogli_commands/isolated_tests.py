from __future__ import annotations

import os
import re

import pytest

from django.conf import settings
from django.db import connections

import psycopg
from infi.clickhouse_orm import Database
from psycopg import sql

_owned_namespace = pytest.StashKey[str]()


def _clickhouse() -> Database:
    return Database(
        "system",
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        verify_ssl_cert=settings.CLICKHOUSE_VERIFY,
        trust_env=False,
    )


def _clickhouse_names(database: Database) -> list[str]:
    worker = os.getenv("PYTEST_XDIST_WORKER")
    worker_pattern = re.escape("_" + worker) if worker else r"(?:_gw[0-9]+)?"
    pattern = rf"posthog_(?:test|ai_eval){worker_pattern}_{settings.TEST_RUN_ID}"
    return [name for name in database.raw("SHOW DATABASES").splitlines() if re.fullmatch(pattern, name)]


def pytest_configure(config: pytest.Config) -> None:
    config.option.reuse_db = False
    config.option.create_db = True


def _database_prefix() -> str:
    run_id = settings.TEST_RUN_ID
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise RuntimeError("Private database cleanup requires a valid test run ID")
    prefix = f"test_posthog_{run_id}"
    worker = os.getenv("PYTEST_XDIST_WORKER")
    if worker:
        if not re.fullmatch(r"gw[0-9]+", worker):
            raise RuntimeError("Private database cleanup requires a valid pytest worker ID")
        prefix += f"_{worker}"
    return prefix


def _connect() -> psycopg.Connection[tuple[str]]:
    database = settings.DATABASES["default"]
    return psycopg.connect(
        dbname="postgres",
        host=database["HOST"],
        port=database["PORT"],
        user=database["USER"],
        password=database["PASSWORD"],
        autocommit=True,
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    prefix = _database_prefix()
    default = settings.DATABASES["default"]
    for database in settings.DATABASES.values():
        if any(database.get(key) != default.get(key) for key in ("HOST", "PORT", "USER", "PASSWORD")):
            raise pytest.UsageError("--isolated requires PostgreSQL aliases on the same local server and credentials")
    with _connect() as connection:
        names = connection.execute("SELECT datname FROM pg_database").fetchall()
        if any(name == prefix or name.startswith(prefix + "_") for (name,) in names):
            raise pytest.UsageError(f"Private database namespace already exists: {prefix}")
    if _clickhouse_names(_clickhouse()):
        raise pytest.UsageError(f"Private ClickHouse namespace already exists: {prefix}")
    session.config.stash[_owned_namespace] = prefix


def pytest_sessionfinish(session: pytest.Session) -> None:
    prefix = session.config.stash.get(_owned_namespace, None)
    if prefix is None:
        return
    connections.close_all()
    failures: list[str] = []
    try:
        with _connect() as connection:
            names = connection.execute("SELECT datname FROM pg_database").fetchall()
            for (name,) in names:
                if name == prefix or name.startswith(prefix + "_"):
                    try:
                        connection.execute(sql.SQL("DROP DATABASE {};").format(sql.Identifier(name)))
                    except Exception as exc:
                        failures.append(f"{name}: {exc}")
    except Exception as exc:
        failures.append(f"{prefix}: {exc}")
    try:
        database = _clickhouse()
        for name in _clickhouse_names(database):
            try:
                database.raw(f"DROP DATABASE IF EXISTS {name} SYNC")
            except Exception as exc:
                failures.append(f"{name}: {exc}")
    except Exception as exc:
        failures.append(f"ClickHouse namespace {prefix}: {exc}")
    if failures:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line("Private database cleanup incomplete: " + "; ".join(failures), yellow=True)
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
