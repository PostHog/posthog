"""Isolated test runs: the name `hogli test --isolated` hands to pytest, and cleanup of the databases they keep.

posthog/settings/data_stores.py turns POSTHOG_TEST_ISOLATION=<name> into the database names
test_posthog_iso_<name> (Postgres, plus its _persons and product databases) and posthog_test_iso_<name>
(ClickHouse), with an xdist suffix such as _gw0 when pytest-xdist runs. The databases stay after the run,
because reusing them is what makes the next run fast, so `hogli test:isolated:clean` drops them on request.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

import click

ISOLATION_ENV_VAR = "POSTHOG_TEST_ISOLATION"

# Postgres truncates identifiers at 63 bytes. The longest derived name is
# test_posthog_iso_<name>_warehouse_sources_queue_gw99, which leaves 16 characters for the name.
MAX_NAME_LENGTH = 16

# The name has no separators, so the first underscore after it starts a suffix of the same run.
_POSTGRES_DATABASE = re.compile(r"test_posthog_iso_(?P<name>[a-z0-9]+)(?:_[a-z0-9_]+)?")
_CLICKHOUSE_DATABASE = re.compile(r"posthog_test_iso_(?P<name>[a-z0-9]+)(?:_gw\d+)?")

# Both match posthog/test/isolated_databases.py: a running isolated run sets this application_name, and
# holds an advisory lock on hashtext(<lock prefix><its Postgres test database>) for as long as it runs.
_RUNNING_APPLICATION_NAME_PREFIX = "posthog-test-isolation:"
_RUN_LOCK_PREFIX = "posthog-test-isolation:"


def isolation_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9]", "", raw.lower())[:MAX_NAME_LENGTH]
    if not name:
        raise click.UsageError(f"An isolation name needs at least one letter or digit, and {raw!r} has none.")
    return name


@dataclass(frozen=True)
class IsolatedDatabases:
    name: str
    postgres: tuple[str, ...]
    clickhouse: tuple[str, ...]
    running: bool


def group_isolated_databases(
    postgres: Iterable[str], clickhouse: Iterable[str], running: Iterable[str]
) -> list[IsolatedDatabases]:
    by_name: dict[str, tuple[list[str], list[str]]] = {}
    for database in sorted(postgres):
        if match := _POSTGRES_DATABASE.fullmatch(database):
            by_name.setdefault(match["name"], ([], []))[0].append(database)
    for database in sorted(clickhouse):
        if match := _CLICKHOUSE_DATABASE.fullmatch(database):
            by_name.setdefault(match["name"], ([], []))[1].append(database)
    running_names = set(running)
    return [
        IsolatedDatabases(name, tuple(pg), tuple(ch), name in running_names)
        for name, (pg, ch) in sorted(by_name.items())
    ]


def select_for_drop(groups: list[IsolatedDatabases], names: Iterable[str], drop_all: bool) -> list[IsolatedDatabases]:
    if drop_all:
        return [group for group in groups if not group.running]
    by_name = {group.name: group for group in groups}
    selected = []
    for name in dict.fromkeys(isolation_name(raw) for raw in names):
        group = by_name.get(name)
        if group is None:
            raise click.UsageError(f"No isolated test databases are named {name!r}.")
        if group.running:
            raise click.UsageError(f"An isolated test run named {name!r} is running, so its databases stay.")
        selected.append(group)
    return selected


def isolation_lock_keys(group: IsolatedDatabases) -> set[str]:
    # ClickHouse-only workers hold a lock even when their Postgres database has never been created.
    databases = {f"test_posthog_iso_{group.name}", *group.postgres} | {
        database.replace("posthog_test_iso_", "test_posthog_iso_", 1) for database in group.clickhouse
    }
    return {f"{_RUN_LOCK_PREFIX}{database}" for database in databases}


@click.command(
    name="test:isolated:clean",
    help=(
        "List or drop the test databases that `hogli test --isolated` keeps between runs.\n\n"
        "With no arguments, list them. Pass names to drop those, or --all to drop every isolated set. "
        "Databases of a run in progress are never dropped. The shared test databases never match."
    ),
)
@click.argument("names", nargs=-1)
@click.option("--all", "drop_all", is_flag=True, help="Drop every isolated set that is not in use.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
def isolated_clean(names: tuple[str, ...], drop_all: bool, yes: bool) -> None:
    import psycopg  # noqa: PLC0415 — keeps the database driver off hogli's startup path
    from psycopg import sql  # noqa: PLC0415 — keeps the database driver off hogli's startup path

    if names and drop_all:
        raise click.UsageError("Pass names or --all, not both.")

    clickhouse = _ClickHouse()
    with psycopg.connect(_postgres_url(), dbname="postgres", autocommit=True) as connection:
        postgres_names = [row[0] for row in connection.execute("SELECT datname FROM pg_database").fetchall()]
        running = [
            row[0].removeprefix(_RUNNING_APPLICATION_NAME_PREFIX)
            for row in connection.execute(
                "SELECT DISTINCT application_name FROM pg_stat_activity WHERE starts_with(application_name, %s)",
                (_RUNNING_APPLICATION_NAME_PREFIX,),
            ).fetchall()
        ]
        groups = group_isolated_databases(postgres_names, clickhouse.databases(), running)

        if not groups:
            click.echo("No isolated test databases.")
            return
        if not names and not drop_all:
            for group in groups:
                _echo_group(group)
            click.echo("\nDrop them with `hogli test:isolated:clean <name>` or `--all`.")
            return

        selected = select_for_drop(groups, names, drop_all)
        if not selected:
            click.echo("Every isolated set is in use; nothing to drop.")
            return
        for group in selected:
            _echo_group(group)
        if not yes and not click.confirm(f"\nDrop the databases of {len(selected)} isolated run(s)?", default=False):
            raise SystemExit(1)

        for group in selected:
            # A run that starts after the pg_stat_activity snapshot above would lose its ClickHouse database,
            # so hold its locks while dropping. A run that starts now stops at its own lock instead.
            locked = True
            for key in sorted(isolation_lock_keys(group)):
                row = connection.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()
                if row != (True,):
                    locked = False
                    break
            if locked:
                for database in group.postgres:
                    connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
                for database in group.clickhouse:
                    clickhouse.drop(database)
                click.secho(f"Dropped {group.name}", fg="green")
            else:
                click.secho(f"Skipped {group.name}: a test run with that name just started", fg="yellow")
            connection.execute("SELECT pg_advisory_unlock_all()")


def _echo_group(group: IsolatedDatabases) -> None:
    status = " (running)" if group.running else ""
    click.secho(f"{group.name}{status}", bold=True)
    for database in group.postgres:
        click.echo(f"  postgres    {database}")
    for database in group.clickhouse:
        click.echo(f"  clickhouse  {database}")


def _postgres_url() -> str:
    # Same default as posthog/settings/data_stores.py when DATABASE_URL is unset.
    return os.environ.get("DATABASE_URL", "postgres://posthog:posthog@db:5432/posthog")


class _ClickHouse:
    def __init__(self) -> None:
        self._url = f"http://{os.environ.get('CLICKHOUSE_HOST', 'localhost')}:8123/"
        self._auth = (os.environ.get("CLICKHOUSE_USER", "default"), os.environ.get("CLICKHOUSE_PASSWORD", ""))

    def databases(self) -> list[str]:
        return self._query("SELECT name FROM system.databases").splitlines()

    def drop(self, database: str) -> None:
        # SYNC removes the replicated tables' Keeper metadata now instead of after the Atomic engine's delay.
        self._query(f"DROP DATABASE IF EXISTS `{database}` SYNC")

    def _query(self, query: str) -> str:
        import requests  # noqa: PLC0415 — keeps the HTTP client off hogli's startup path

        response = requests.post(self._url, data=query.encode(), auth=self._auth, timeout=60)
        response.raise_for_status()
        return response.text
