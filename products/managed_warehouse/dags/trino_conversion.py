from collections.abc import Mapping

import dagster
import psycopg
from psycopg import sql

from posthog.dags.common import JobOwners
from posthog.dags.events_backfill_to_duckling import (
    DUCKLAKE_ALIAS,
    EVENTS_TRINO_COLUMN_TYPES,
    PERSONS_TRINO_COLUMN_TYPES,
    _DuckgresSession,
    _resolve_duckling_target,
    table_exists,
)
from posthog.dataclasses import frozen

from products.managed_warehouse.backend.facade.team_state import resolve_groups_table
from products.managed_warehouse.dags.groups_backfill import GROUPS_TRINO_COLUMN_TYPES

# The names that DuckDB DESCRIBE reports for the Trino types of the backfill exports.
TRINO_TO_DUCKDB_TYPES = {
    "bigint": "BIGINT",
    "integer": "INTEGER",
    "smallint": "SMALLINT",
    "boolean": "BOOLEAN",
    "varchar": "VARCHAR",
    "timestamp(6) with time zone": "TIMESTAMP WITH TIME ZONE",
}

# The in-place type changes of DuckLake that end in a signed type. DuckLake changes UINTEGER only to UBIGINT and
# UBIGINT to no type, so a column of either type needs a rebuild.
PROMOTIONS = frozenset(
    {
        ("TINYINT", "SMALLINT"),
        ("TINYINT", "INTEGER"),
        ("TINYINT", "BIGINT"),
        ("SMALLINT", "INTEGER"),
        ("SMALLINT", "BIGINT"),
        ("INTEGER", "BIGINT"),
        ("UTINYINT", "SMALLINT"),
        ("UTINYINT", "INTEGER"),
        ("UTINYINT", "BIGINT"),
        ("USMALLINT", "INTEGER"),
        ("USMALLINT", "BIGINT"),
    }
)


class DucklingTrinoConversionConfig(dagster.Config):
    team_id: int
    dry_run: bool = True


@frozen
class TableConversionPlan:
    table: str
    missing: bool
    widen: Mapping[str, str]
    rebuild: Mapping[str, str]


def plan_table_conversion(
    table: str, actual: Mapping[str, str] | None, expected_trino: Mapping[str, str]
) -> TableConversionPlan:
    if actual is None:
        return TableConversionPlan(table=table, missing=True, widen={}, rebuild={})
    widen: dict[str, str] = {}
    rebuild: dict[str, str] = {}
    for column, trino_type in expected_trino.items():
        if trino_type not in TRINO_TO_DUCKDB_TYPES:
            raise ValueError(f"The Trino type {trino_type} of column {column} has no DuckDB type mapped")
        target = TRINO_TO_DUCKDB_TYPES[trino_type]
        current = actual.get(column, "missing")
        if current == target:
            continue
        if (current, target) in PROMOTIONS:
            widen[column] = target
        else:
            rebuild[column] = current
    return TableConversionPlan(table=table, missing=False, widen=widen, rebuild=rebuild)


def _describe(conn: psycopg.Connection[tuple[object, ...]], table: str) -> dict[str, str] | None:
    if not table_exists(conn, DUCKLAKE_ALIAS, "posthog", table):
        return None
    rows = conn.execute(sql.SQL("DESCRIBE {}").format(sql.Identifier(DUCKLAKE_ALIAS, "posthog", table))).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _widen_column(conn: psycopg.Connection[tuple[object, ...]], table: str, column: str, target: str) -> None:
    # The session can replay this operation after a lost connection, and a repeated ALTER writes a new column version.
    if (_describe(conn, table) or {}).get(column) == target:
        return
    conn.execute(
        sql.SQL("ALTER TABLE {} ALTER COLUMN {} SET DATA TYPE {}").format(
            sql.Identifier(DUCKLAKE_ALIAS, "posthog", table), sql.Identifier(column), sql.SQL(target)
        )
    )


def _summarize(
    context: dagster.OpExecutionContext, team_id: int, dry_run: bool, plans: Mapping[str, TableConversionPlan]
) -> str:
    verb = "would widen" if dry_run else "widened"
    lines = []
    next_steps = []
    for kind, plan in plans.items():
        if plan.missing:
            lines.append(f"{kind} ({plan.table}): table does not exist, so Trino creates it with the right types")
            continue
        lines.append(
            f"{kind} ({plan.table}): {verb} {dict(plan.widen) or 'nothing'}; needs a rebuild: {dict(plan.rebuild) or 'no'}"
        )
        if plan.rebuild and kind != "events":
            job = f"duckling_{kind}_backfill_job"
            next_steps.append(
                f"Rebuild {kind}: run {job} for partition {team_id} with rebuild_mismatched_table: true, with the org on the Trino flag"
            )
    summary = "\n".join([*lines, *next_steps])
    context.log.info(f"Trino conversion summary for team {team_id}:\n{summary}")
    return summary


@dagster.op(tags={"owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value})
def duckling_trino_conversion(context: dagster.OpExecutionContext, config: DucklingTrinoConversionConfig) -> None:
    target = _resolve_duckling_target(config.team_id)
    tables = {
        "events": (target.events_table, EVENTS_TRINO_COLUMN_TYPES),
        "persons": (target.persons_table, PERSONS_TRINO_COLUMN_TYPES),
        "groups": (resolve_groups_table(config.team_id), GROUPS_TRINO_COLUMN_TYPES),
    }
    plans: dict[str, TableConversionPlan] = {}
    session = _DuckgresSession(context, target)
    try:
        for kind, (table, expected) in tables.items():

            def describe(conn: psycopg.Connection[tuple[object, ...]], table: str = table) -> dict[str, str] | None:
                return _describe(conn, table)

            plan = plan_table_conversion(table, session.run(f"describe {kind}", describe), expected)
            plans[kind] = plan
            context.log.info(f"Conversion plan for {kind}: {plan}")
            if config.dry_run or not plan.widen:
                continue
            for column, column_type in plan.widen.items():

                def widen(
                    conn: psycopg.Connection[tuple[object, ...]],
                    table: str = table,
                    column: str = column,
                    column_type: str = column_type,
                ) -> None:
                    _widen_column(conn, table, column, column_type)

                session.run(f"widen {table}.{column}", widen)
            after = session.run(f"describe {kind}", describe) or {}
            wrong = {col: after.get(col) for col, ty in plan.widen.items() if after.get(col) != ty}
            if wrong:
                raise ValueError(f"{table} still has other types than the plan: {wrong}")
    finally:
        session.close()
    summary = _summarize(context, config.team_id, config.dry_run, plans)
    if plans["events"].rebuild:
        raise ValueError(
            f"The events table {plans['events'].table} needs a rebuild that a snapshot run cannot do: "
            f"{dict(plans['events'].rebuild)}"
        )
    context.add_output_metadata({"summary": summary})


@dagster.job(
    description="Widens the unsigned columns of a team's duckling tables in place, so Trino can register files",
    tags={"owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value},
)
def duckling_trino_conversion_job() -> None:
    duckling_trino_conversion()
